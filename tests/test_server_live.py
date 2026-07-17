"""Integration tests for the live-desk endpoints (Phase 5): snapshot info, hedge
recommendations, paper execution blotter, and alerts — the pieces built in Phases 6/8/12
exposed over HTTP. Uses a small synthetic desk build; no network, no credentials.

Note: the hedge/execution/alert endpoints share module-level state (paper broker, alert
engine), so tests in this file build on each other in order.
"""

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import webapp.server as server


@pytest.fixture(scope="module", autouse=True)
def _small_desk(tmp_path_factory):
    original = server.build_desk_data
    server.build_desk_data = lambda **kw: original(n_notes=4, n_paths=4000, **kw)
    server._cache.payload = None
    server._cache.built_at = 0.0
    server._paper = server.PaperBroker()
    server._alert_engine = server.AlertEngine()
    server._recommendations.clear()
    server._hedge_specs.clear()
    server._PAPER_STATE_PATH = str(tmp_path_factory.mktemp("paper") / "paper_state.pkl")
    server._DESK_HISTORY_PATH = str(tmp_path_factory.mktemp("history") / "desk_history.jsonl")
    server._autohedge.update(enabled=False, last_proposal=None, last_error=None)
    yield
    server.build_desk_data = original


@pytest.fixture(scope="module")
def client():
    return TestClient(server.app)


def _future():
    return {"instrument_id": 101, "segment": 2, "symbol": "NIFTY-FUT",
            "bid": 24000.0, "ask": 24001.0, "ltp": 24000.5,
            "quote_timestamp": datetime.now(timezone.utc).isoformat(), "lot_size": 1}


def test_live_snapshot_reports_source_and_spot(client):
    body = client.get("/api/live/snapshot").json()
    assert body["data_source"] == "synthetic"
    assert body["spot"] > 0
    assert body["underlying"] == "NIFTY"
    assert "as_of" in body and "desk_age_s" in body


def test_hedge_recommend_execute_blotter_roundtrip(client):
    r = client.post("/api/hedges/recommend", json={"book_delta": 150.0, "future": _future()})
    assert r.status_code == 200
    rec = r.json()
    assert rec["approval_state"] == "PROPOSED"
    assert rec["orders"] == [{"instrument_id": 101, "segment": 2, "symbol": "NIFTY-FUT",
                              "side": "SELL", "qty": 150.0}]
    assert rec["expected_greeks"]["delta"] == 0.0

    listed = client.get("/api/hedges/recommendations").json()
    assert listed[-1]["recommendation_id"] == rec["recommendation_id"]

    r2 = client.post("/api/execution/execute",
                     json={"recommendation_id": rec["recommendation_id"]})
    assert r2.status_code == 200
    assert r2.json()["orders"][0]["status"] == "FILLED"

    blotter = client.get("/api/execution/blotter").json()
    assert blotter["positions"]["2:101"]["qty"] == -150.0
    assert len(blotter["fills"]) == 1
    assert blotter["orders"][0]["side"] == "SELL"

    # Idempotent retry returns the original result without another fill.
    retry = client.post("/api/execution/execute",
                        json={"recommendation_id": rec["recommendation_id"]})
    assert retry.json() == r2.json()
    assert len(client.get("/api/execution/blotter").json()["fills"]) == 1


def test_execute_unknown_recommendation_is_404(client):
    r = client.post("/api/execution/execute", json={"recommendation_id": "nope"})
    assert r.status_code == 404


def test_execute_revalidates_quote_age(client):
    rec = client.post(
        "/api/hedges/recommend", json={"book_delta": 10.0, "future": _future()}
    ).json()
    state = server._recommendations[rec["recommendation_id"]]
    for key, quote in state.quotes.items():
        state.quotes[key] = dataclasses.replace(
            quote, timestamp=datetime.now(timezone.utc) - timedelta(minutes=5)
        )
    before = len(client.get("/api/execution/blotter").json()["fills"])
    response = client.post(
        "/api/execution/execute", json={"recommendation_id": rec["recommendation_id"]}
    )
    assert response.status_code == 409
    assert len(client.get("/api/execution/blotter").json()["fills"]) == before


def test_recommend_defaults_to_desk_book_greeks(client):
    desk_delta = client.get("/api/desk").json()["net_greeks"]["delta"]
    rec = client.post("/api/hedges/recommend", json={"future": _future()}).json()
    assert rec["current_greeks"]["delta"] == pytest.approx(desk_delta)


def test_scenario_override_cannot_suppress_canonical_alert(client, monkeypatch):
    monkeypatch.setattr(server, "_DELTA_LIMIT", 0.0)
    client.post("/api/hedges/recommend", json={"book_delta": 0.0, "future": _future()})
    alerts = client.get("/api/alerts").json()
    (delta_alert,) = [a for a in alerts["open"] if a["metric"] == "delta"]
    assert delta_alert["severity"] == "CRITICAL" and delta_alert["status"] == "OPEN"

    client.post(f"/api/alerts/{delta_alert['id']}/ack")
    refreshed = client.get("/api/alerts").json()
    assert [a["status"] for a in refreshed["open"] if a["id"] == delta_alert["id"]] == ["ACKNOWLEDGED"]
    assert len(refreshed["history"]) >= 1


def test_payoff_explorer_returns_client_view(client):
    r = client.post("/api/explorer", json={
        "product_type": "brc", "notional": 100, "observation_times": [0.5, 1.0],
        "params": {"coupon_rate": 0.03, "knock_in": 0.7, "strike": 1.0},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["pv"] > 0
    assert len(body["payoff"]) >= 10  # fine terminal-level sweep for the diagram
    assert {"terminal_level", "payment_pct"} <= set(body["payoff"][0])
    outcomes = body["outcomes"]
    assert 0.0 <= outcomes["prob_loss_pct"] <= 100.0
    assert [c["time"] for c in body["coupon_schedule"]] == [0.5, 1.0]
    assert body["coupon_schedule"][0]["amount_pct"] == pytest.approx(3.0)
    assert body["summary"] and isinstance(body["summary"][0], str)
    assert "model-implied" in body["disclaimer"]


def test_payoff_explorer_capital_protected_has_no_coupons(client):
    r = client.post("/api/explorer", json={
        "product_type": "capital_protected", "notional": 100, "maturity": 1.0,
        "params": {"protection": 1.0, "participation": 1.2, "strike": 1.0},
    })
    body = r.json()
    assert body["coupon_schedule"] == []
    assert body["outcomes"]["prob_loss_pct"] == 0.0


def test_option_chain_endpoint_serves_priced_rows(client):
    r = client.get("/api/live/option-chain")
    assert r.status_code == 200
    body = r.json()
    rows = body["rows"]
    assert rows and {"expiry", "strike", "type", "price", "moneyness", "iv"} <= set(rows[0])
    assert all(row["type"] in ("CE", "PE") for row in rows)
    assert all(0.7 <= row["moneyness"] <= 1.3 for row in rows)
    assert any(row["iv"] is not None for row in rows)  # inverted IVs attached
    assert len({row["expiry"] for row in rows}) <= 4  # nearest expiries only
    assert body["as_of"] and body["data_source"] == "synthetic"


def test_broker_state_not_connected_without_credentials(client, monkeypatch):
    monkeypatch.delenv("SPDT_XTS_INTERACTIVE_APP_KEY", raising=False)
    monkeypatch.delenv("SPDT_XTS_INTERACTIVE_SECRET", raising=False)
    body = client.get("/api/broker/state").json()
    assert body["connected"] is False
    assert "credentials" in body["reason"]


def test_broker_state_reconciles_paper_vs_broker(client, monkeypatch):
    from spdt.execution.xts import BrokerPosition, MarginState

    class FakeBroker:
        app_key, secret, token = "K", "S", "T"

        def login(self):
            pass

        def orders(self):
            return []

        def trades(self):
            return []

        def positions(self):
            return [BrokerPosition(symbol="NIFTY-FUT", exchange_instrument_id=101,
                                   qty=-75.0, buy_avg_price=0.0, sell_avg_price=24010.0)]

        def margins(self):
            return MarginState(cash_available=5e5, margin_utilized=1.2e5,
                               net_margin_available=3.8e5)

    monkeypatch.setattr(server, "_broker_client", lambda: FakeBroker())
    body = client.get("/api/broker/state").json()
    assert body["connected"] is True
    assert body["margins"]["cash_available"] == 5e5
    row = next(r for r in body["reconciliation"] if r["instrument_id"] == 101)
    assert row["broker_qty"] == -75.0
    assert row["paper_qty"] == -150.0  # from the earlier paper execution in this module
    assert row["difference"] == pytest.approx(75.0)


def test_execution_attribution_endpoint(client):
    r = client.post("/api/execution/attribution", json={"marks": {"2:101": 24000.5}})
    assert r.status_code == 200
    body = r.json()
    row = next(x for x in body["rows"] if x["instrument_id"] == 101)
    assert row["qty"] == -150.0
    assert row["unrealized_pnl"] is not None and row["net_pnl"] is not None
    assert "spread_cost" in body["totals"]


def test_invalid_zero_vega_option_returns_422(client):
    future = _future()
    option = {**future, "instrument_id": 202, "symbol": "NIFTY-OPT", "vega": 0.0}
    response = client.post("/api/hedges/recommend", json={
        "book_delta": 10.0, "book_vega": 100.0, "future": future, "option": option,
    })
    assert response.status_code == 422


def test_live_quote_needs_the_xts_feed(client):
    r = client.get("/api/live/quote")
    assert r.status_code == 409
    assert "SPDT_SOURCE=xts" in r.json()["detail"]


def test_live_quote_serves_front_future(client, monkeypatch):
    from datetime import date

    from spdt.data.ingest.xts import InstrumentRef, Quote

    front = InstrumentRef(exchange_segment=2, exchange_instrument_id=61093, symbol="NIFTY",
                          description="NIFTY26JULFUT", series="FUTIDX",
                          instrument_type="FUTIDX",
                          expiry=date.today() + timedelta(days=7), lot_size=65)
    far = dataclasses.replace(front, exchange_instrument_id=61094,
                              expiry=date.today() + timedelta(days=35))
    spread_like = dataclasses.replace(front, exchange_instrument_id=61095,
                                      expiry=date.today() - timedelta(days=1))  # expired

    class FakeXts:
        token = "TOK"

        def instruments(self, segment, **kw):
            assert segment == "NSEFO"
            return [far, front, spread_like]

        def quotes(self, refs, *, now=None, max_age_s=None):
            (ref,) = refs
            assert ref is front  # nearest live expiry wins
            return [Quote(instrument=ref, ltp=24103.7, bid=24101.0, ask=24103.7,
                          bid_qty=65.0, ask_qty=130.0,
                          timestamp=datetime.now(timezone.utc) - timedelta(seconds=12),
                          stale=False)]

    monkeypatch.setattr(server, "_LIVE", True)
    monkeypatch.setattr(server, "_SOURCE", "xts")
    monkeypatch.setattr(server, "_xts_quote_client", FakeXts())
    body = client.get("/api/live/quote").json()
    assert body["instrument_id"] == 61093 and body["lot_size"] == 65
    assert body["bid"] == 24101.0 and body["stale"] is False
    assert body["age_s"] == pytest.approx(12, abs=2)


def test_nse_session_window():
    from zoneinfo import ZoneInfo

    ist = ZoneInfo("Asia/Kolkata")
    assert server._in_nse_session(datetime(2026, 7, 16, 10, 30, tzinfo=ist))   # Thu mid-session
    assert server._in_nse_session(datetime(2026, 7, 16, 9, 15, tzinfo=ist))    # open
    assert not server._in_nse_session(datetime(2026, 7, 16, 9, 14, tzinfo=ist))
    assert not server._in_nse_session(datetime(2026, 7, 16, 15, 36, tzinfo=ist))
    assert not server._in_nse_session(datetime(2026, 7, 18, 10, 30, tzinfo=ist))  # Saturday


def test_live_ticks_needs_the_xts_feed(client):
    r = client.get("/api/live/ticks")
    assert r.status_code == 409


def test_fetch_tick_returns_spot_and_front_future(monkeypatch):
    from datetime import date

    from spdt.data.ingest.xts import InstrumentRef, Quote

    index = InstrumentRef(exchange_segment=1, exchange_instrument_id=26000, symbol="NIFTY 50")
    front = InstrumentRef(exchange_segment=2, exchange_instrument_id=61093, symbol="NIFTY",
                          description="NIFTY26JULFUT", series="FUTIDX",
                          instrument_type="FUTIDX",
                          expiry=date.today() + timedelta(days=7), lot_size=65)
    ts = datetime.now(timezone.utc) - timedelta(seconds=3)

    class FakeXts:
        token = "TOK"

        def indexes(self, segment=1):
            return [index]

        def instruments(self, segment, **kw):
            return [front]

        def quotes(self, refs, *, now=None, max_age_s=None):
            out = []
            for ref in refs:
                ltp = 24072.75 if ref.exchange_segment == 1 else 24103.7
                out.append(Quote(instrument=ref, ltp=ltp, bid=ltp - 1, ask=ltp + 1,
                                 bid_qty=65.0, ask_qty=65.0, timestamp=ts, stale=False))
            return out

    monkeypatch.setattr(server, "_xts_quote_client", FakeXts())
    monkeypatch.setattr(server, "_tick_refs", None)  # force re-resolve against the fake
    tick = server._fetch_tick()
    assert tick["spot"] == 24072.75
    assert tick["future"]["ltp"] == 24103.7 and tick["future"]["description"] == "NIFTY26JULFUT"
    assert tick["stale"] is False and tick["age_s"] == pytest.approx(3, abs=2)
    # refs are cached for the day — a second call must not re-resolve
    assert server._tick_refs is not None and server._tick_refs[0] == date.today()


def test_fetch_tick_inverts_live_atm_straddle_vol(monkeypatch):
    from datetime import date
    from math import exp

    from spdt.data.curate.bs_inversion import bs_price
    from spdt.data.ingest.xts import InstrumentRef, Quote
    from spdt.core.types import year_fraction

    model = server._desk()["model"]
    spot, strike, sigma = 24000.0, 24000.0, 0.15
    expiry = date.today() + timedelta(days=7)
    tau = year_fraction(date.today(), expiry)
    fwd = spot * exp((model["r"] - model["q"]) * tau)
    disc = exp(-model["r"] * tau)
    prices = {
        26000: spot,
        61093: fwd,
        45001: bs_price(fwd, strike, tau, sigma, disc, True),
        45002: bs_price(fwd, strike, tau, sigma, disc, False),
    }

    index = InstrumentRef(exchange_segment=1, exchange_instrument_id=26000, symbol="NIFTY 50")
    fo = [
        InstrumentRef(exchange_segment=2, exchange_instrument_id=61093, symbol="NIFTY",
                      description="NIFTY-FUT", series="FUTIDX", instrument_type="FUTIDX",
                      expiry=expiry, lot_size=65),
        InstrumentRef(exchange_segment=2, exchange_instrument_id=45001, symbol="NIFTY",
                      series="OPTIDX", instrument_type="OPTIDX", expiry=expiry,
                      strike=strike, option_type="CE"),
        InstrumentRef(exchange_segment=2, exchange_instrument_id=45002, symbol="NIFTY",
                      series="OPTIDX", instrument_type="OPTIDX", expiry=expiry,
                      strike=strike, option_type="PE"),
    ]
    ts = datetime.now(timezone.utc)

    class FakeXts:
        token = "TOK"

        def indexes(self, segment=1):
            return [index]

        def instruments(self, segment, **kw):
            return fo

        def quotes(self, refs, *, now=None, max_age_s=None):
            return [Quote(instrument=r, ltp=prices[r.exchange_instrument_id],
                          bid=None, ask=None, bid_qty=None, ask_qty=None,
                          timestamp=ts, stale=False) for r in refs]

    monkeypatch.setattr(server, "_xts_quote_client", FakeXts())
    monkeypatch.setattr(server, "_tick_refs", None)
    monkeypatch.setattr(server, "_iv_baseline", None)
    tick = server._fetch_tick()
    assert tick["atm_iv"] == pytest.approx(sigma, abs=1e-4)
    assert tick["dvol"] == pytest.approx(0.0, abs=1e-9)  # first tick after a mark = baseline

    # vol moves: richer straddle → positive dvol against the unchanged baseline
    prices[45001] = bs_price(fwd, strike, tau, 0.18, disc, True)
    prices[45002] = bs_price(fwd, strike, tau, 0.18, disc, False)
    tick = server._fetch_tick()
    assert tick["dvol"] == pytest.approx(0.03, abs=1e-4)


def test_executed_hedges_fold_into_desk_risk(client):
    """Runs last on purpose: it moves the shared paper position, which the broker
    reconciliation and attribution tests above pin at -150."""
    before = client.get("/api/desk").json()["net_greeks"]["delta"]
    rec = client.post("/api/hedges/recommend",
                      json={"book_delta": 40.0, "future": _future()}).json()
    client.post("/api/execution/execute",
                json={"recommendation_id": rec["recommendation_id"]})
    after = client.get("/api/desk").json()["net_greeks"]["delta"]
    assert after == pytest.approx(before - 40.0)
    # A fresh default-sized recommendation must see the hedged book, not re-hedge it.
    rec2 = client.post("/api/hedges/recommend", json={"future": _future()}).json()
    assert rec2["current_greeks"]["delta"] == pytest.approx(after)


def test_option_hedges_are_remarked_off_the_desk_model(client):
    from datetime import date

    from spdt.hedging.recommend import vanilla_spot_greeks

    d = client.get("/api/desk").json()
    before = d["net_greeks"]
    strike = d["spot"] * 1.02
    option = {**_future(), "instrument_id": 880001, "symbol": "NIFTY-OPT",
              "delta": 0.5, "vega": 40.0, "strike": strike,
              "expiry": (date.today() + timedelta(days=90)).isoformat(),
              "option_type": "CE"}
    rec = client.post("/api/hedges/recommend", json={
        "book_delta": 0.0, "book_vega": 400.0, "future": _future(), "option": option,
    }).json()
    client.post("/api/execution/execute", json={"recommendation_id": rec["recommendation_id"]})

    qty = client.get("/api/execution/blotter").json()["positions"]["2:880001"]["qty"]
    assert qty == -10.0  # -book_vega / option unit vega
    m = d["model"]
    vol = server._chain_vol(d, strike, date.today() + timedelta(days=90), True)
    g = vanilla_spot_greeks(d["spot"], strike, 90 / 365, vol, m["r"], m["q"], True)
    after = client.get("/api/desk").json()["net_greeks"]
    # Greeks come from the desk's own model, not the client's recommend-time numbers.
    assert after["gamma"] - before["gamma"] == pytest.approx(qty * g["gamma"], rel=1e-6)
    assert after["vanna"] - before["vanna"] == pytest.approx(qty * g["vanna"], rel=1e-6)


def test_option_terms_must_come_together(client):
    option = {**_future(), "instrument_id": 880002, "vega": 40.0, "strike": 24000.0}
    r = client.post("/api/hedges/recommend", json={
        "book_delta": 0.0, "book_vega": 400.0, "future": _future(), "option": option,
    })
    assert r.status_code == 422


def test_option_leg_greeks_default_from_desk_model(client):
    """The UI sends option terms without greeks — the server prices the leg itself."""
    from datetime import date

    from spdt.hedging.recommend import vanilla_spot_greeks

    d = client.get("/api/desk").json()
    strike, days = d["spot"] * 0.99, 45
    option = {**_future(), "instrument_id": 880003, "symbol": "NIFTY-OPT-UI",
              "strike": strike, "expiry": (date.today() + timedelta(days=days)).isoformat(),
              "option_type": "PE"}  # note: no delta/vega supplied
    rec = client.post("/api/hedges/recommend", json={
        "book_delta": 0.0, "book_vega": -50000.0, "future": _future(), "option": option,
    }).json()
    m = d["model"]
    vol = server._chain_vol(d, strike, date.today() + timedelta(days=days), False)
    g = vanilla_spot_greeks(d["spot"], strike, days / 365, vol, m["r"], m["q"], False)
    opt_order = next(o for o in rec["orders"] if o["instrument_id"] == 880003)
    assert opt_order["side"] == "BUY"  # short vega book → buy the option
    assert opt_order["qty"] == round(50000.0 / g["vega"])  # sized on model vega, lot 1


def test_chain_vol_picks_nearest_expiry_then_strike():
    from datetime import date

    d = {"model": {"atm_vol": 0.14}, "option_chain": [
        {"expiry": "2026-08-27", "strike": 24000.0, "type": "CE", "iv": 0.16},
        {"expiry": "2026-08-27", "strike": 25000.0, "type": "CE", "iv": 0.20},
        {"expiry": "2026-09-24", "strike": 24000.0, "type": "CE", "iv": 0.18},
        {"expiry": "2026-08-27", "strike": 24000.0, "type": "PE", "iv": 0.17},
        {"expiry": "2026-08-27", "strike": 24100.0, "type": "CE", "iv": None},  # no IV → skipped
    ]}
    assert server._chain_vol(d, 24050.0, date(2026, 8, 25), True) == 0.16   # front expiry, near strike
    assert server._chain_vol(d, 25200.0, date(2026, 8, 25), True) == 0.20   # wing strike
    assert server._chain_vol(d, 24000.0, date(2026, 9, 20), True) == 0.18   # back expiry
    assert server._chain_vol(d, 24000.0, date(2026, 8, 25), False) == 0.17  # puts use put IVs
    assert server._chain_vol({"model": {"atm_vol": 0.14}}, 24000.0, date(2026, 8, 25), True) == 0.14


def test_hedge_pnl_folds_into_nav(client):
    d = client.get("/api/desk").json()
    pnl = d["hedge_pnl"]
    assert pnl["total"] == pytest.approx(pnl["realized"] + pnl["unrealized"] - pnl["fees"])
    assert pnl["fees"] > 0  # this module has executed several paper hedges by now
    raw = server._desk()  # engine payload, before the hedge fold-in
    assert d["nav"] == pytest.approx(raw["nav"] + pnl["total"])
    # open futures positions mark at spot (no expiry given) → unrealized moves the NAV
    fut = client.get("/api/execution/blotter").json()["positions"]["2:101"]
    assert fut["qty"] != 0
    expected_unrealized_fut = fut["qty"] * (d["spot"] - fut["avg_price"])
    assert pnl["unrealized"] != 0 or abs(expected_unrealized_fut) < 1e-9


def test_paper_state_survives_restart(client):
    """Kill the in-memory paper book, reload from disk — positions and specs come back."""
    before = {k: p.qty for k, p in server._paper.positions.items()}
    specs_before = dict(server._hedge_specs)
    assert before and specs_before  # earlier tests executed hedges, which persisted

    server._paper = server.PaperBroker()
    server._hedge_specs.clear()
    server._load_paper_state()

    assert {k: p.qty for k, p in server._paper.positions.items()} == before
    # specs persist for every held position (recommend-only specs die with the process)
    held = {k: v for k, v in specs_before.items() if k in before}
    assert {k: server._hedge_specs.get(k) for k in held} == held
    # and the desk fold-in still works off the restored book
    assert "delta" in server._paper_hedge_greeks(client.get("/api/desk").json())


def test_barrier_radar_ranks_notes_by_proximity(client):
    d = client.get("/api/desk").json()
    body = client.get("/api/desk/radar").json()
    rows = body["rows"]
    assert rows, "the mixed book always contains barrier products"
    assert body["spot"] == pytest.approx(d["spot"])
    for row in rows:
        assert row["severity"] in ("CRITICAL", "WARNING", "INFO")
        if "ki_level" in row:
            assert 0.0 <= row["ki_hit_prob_pct"] <= 100.0
            assert row["ki_level"] < d["spot"] * 1.5
        if "autocall_level" in row:
            assert 0.0 <= row["autocall_prob_pct"] <= 100.0
            assert row["next_obs_days"] >= 0
    hit_probs = [r.get("ki_hit_prob_pct", 0.0) for r in rows]
    assert hit_probs == sorted(hit_probs, reverse=True)

    # a spot override near the worst barrier must raise its touch odds
    worst = next((r for r in rows if r.get("ki_level")), None)
    if worst:
        crashed = client.get(f"/api/desk/radar?spot={worst['ki_level'] * 1.01}").json()
        crashed_row = next(r for r in crashed["rows"] if r["trade_id"] == worst["trade_id"])
        assert crashed_row["ki_hit_prob_pct"] > worst["ki_hit_prob_pct"]
        assert crashed_row["severity"] == "CRITICAL"


def test_vol_tracker_needs_the_xts_feed(client):
    r = client.get("/api/live/vol-tracker")
    assert r.status_code == 409


def test_vol_tracker_reports_realized_vs_implied(client, monkeypatch):
    import time as _time

    import numpy as np

    from spdt.analytics.realized_vol import TRADING_SECONDS_PER_YEAR

    monkeypatch.setattr(server, "_LIVE", True)
    monkeypatch.setattr(server, "_SOURCE", "xts")
    sigma, iv, now = 0.12, 0.15, _time.time()
    rng = np.random.default_rng(3)
    dt = 2.0 / TRADING_SECONDS_PER_YEAR
    spots = 24000.0 * np.exp(np.cumsum(sigma * np.sqrt(dt) * rng.standard_normal(1800)))
    server._tick_history.clear()
    for i, s in enumerate(spots):
        server._tick_history.append((now - (1800 - i) * 2.0, float(s), iv))

    body = client.get("/api/live/vol-tracker").json()
    assert body["n_samples"] == 1800
    assert body["realized_vol"] == pytest.approx(sigma, rel=0.08)
    assert body["implied_atm_vol"] == iv
    assert body["spread"] == pytest.approx(iv - body["realized_vol"])
    assert body["series"] and {"t", "spot", "iv", "rv"} <= set(body["series"][0])
    assert len(body["series"]) <= 241
    # short-gamma book at IV > RV earns carry: sign must match the book's gamma
    carry = body.get("gamma_carry_per_day")
    gamma = client.get("/api/desk").json()["net_greeks"]["gamma"]
    if carry is not None and abs(gamma) > 1e-12:
        assert (carry > 0) == (gamma > 0)
    server._tick_history.clear()


def test_desk_history_records_builds_and_executions(client):
    body = client.get("/api/desk/history").json()
    rows = body["rows"]
    assert rows, "the module's desk build and executions must have left timeline rows"
    assert {"t", "spot", "atm_vol", "nav", "delta", "gamma", "vega", "hedge_pnl"} <= set(rows[0])
    assert [r["t"] for r in rows] == sorted(r["t"] for r in rows)
    n_before = len(rows)
    rec = client.post("/api/hedges/recommend",
                      json={"book_delta": 5.0, "future": _future()}).json()
    client.post("/api/execution/execute", json={"recommendation_id": rec["recommendation_id"]})
    assert len(client.get("/api/desk/history").json()["rows"]) == n_before + 1


def test_taylor_residual_full_reval_vs_greeks(client):
    body = client.get("/api/desk/residual?spot_mult=1.02&dvol=0.0&n_paths=4000").json()
    assert body["n_notes"] >= 1
    assert body["predicted"] == pytest.approx(sum(body["terms"].values()))
    assert body["residual"] == pytest.approx(body["actual"] - body["predicted"])
    # a 2% move is second-order territory: greeks must explain most of the reval
    assert abs(body["residual"]) <= max(0.25 * abs(body["actual"]), 1.0)
    flat = client.get("/api/desk/residual?spot_mult=1.0&dvol=0.0&n_paths=4000").json()
    assert flat["actual"] == pytest.approx(0.0, abs=1e-9)
    assert client.get("/api/desk/residual?spot_mult=9.0").status_code == 422


def test_autohedge_step_proposes_but_never_executes(client, monkeypatch):
    from datetime import date as _date

    def fake_quote(symbol):
        return {"instrument_id": 555, "segment": 2, "description": f"{symbol}-FUT-LIVE",
                "bid": 24000.0, "ask": 24001.0, "ltp": 24000.5, "lot_size": 5,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "expiry": (_date.today() + timedelta(days=10)).isoformat()}

    monkeypatch.setattr(server, "_live_quote", fake_quote)
    book_delta = server._hedged_net_greeks(server._desk())["delta"]
    assert abs(book_delta) > 1.0  # the module's executions left the paper book unflat

    server._autohedge.update(delta_threshold=abs(book_delta) * 2, last_proposal=None)
    assert server._autohedge_step() is None  # below threshold → quiet

    server._autohedge["delta_threshold"] = abs(book_delta) / 2
    proposal = server._autohedge_step()
    assert proposal is not None
    assert proposal["orders"] and proposal["book_delta"] == pytest.approx(book_delta)
    listed = client.get("/api/hedges/recommendations").json()
    assert any(r["recommendation_id"] == proposal["recommendation_id"] for r in listed)
    state = server._recommendations[proposal["recommendation_id"]]
    assert state.execution_state == "PROPOSED"  # approval-gated: never auto-executed
    assert server._autohedge_step() is None  # pending proposal → no spam

    status = client.get("/api/autohedge").json()
    assert status["last_proposal"]["recommendation_id"] == proposal["recommendation_id"]
    toggled = client.post("/api/autohedge", json={"enabled": False}).json()
    assert toggled["enabled"] is False
    server._autohedge["last_proposal"] = None
