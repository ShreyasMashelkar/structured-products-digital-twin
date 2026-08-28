"""Integration smoke tests for the FastAPI desk service (webapp/server.py).

Covers the HTTP glue that the unit tests don't: the desk payload shape, the live structuring
and pricing endpoints, the TTL-cache refresh, and the optional API-token gate. Uses a small
desk build so the suite stays fast.
"""

import pytest
from fastapi.testclient import TestClient

import webapp.server as server


@pytest.fixture(scope="module", autouse=True)
def _small_desk():
    """Build a small desk (4 notes / 4k paths) so the HTTP tests stay fast."""
    original = server.build_desk_data
    server.build_desk_data = lambda **kw: original(n_notes=4, n_paths=4000, **kw)
    server._cache.payload = None
    server._cache.built_at = 0.0
    yield
    server.build_desk_data = original


@pytest.fixture(scope="module")
def client():
    return TestClient(server.app)


def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_desk_payload_shape(client):
    d = client.get("/api/desk").json()
    for key in ("positions", "net_greeks", "surface", "stress", "reserves", "data_source"):
        assert key in d
    assert d["data_source"] == "synthetic"


def test_price_endpoint_returns_greeks_and_scenarios(client):
    r = client.post(
        "/api/price",
        json={"product_type": "brc", "notional": 100, "observation_times": [0.5, 1.0],
              "params": {"coupon_rate": 0.06, "knock_in": 0.7, "strike": 1.0}},
    )
    assert r.status_code == 200
    body = r.json()
    assert "greeks" in body and "scenarios" in body and body["pv"] > 0


def test_semistatic_uses_the_submitted_book_and_selection(client):
    payload = {
        "trades": [{
            "trade_id": "LIVE-BRC-42",
            "underlying": "NIFTY",
            "product_type": "brc",
            "notional": 100,
            "observation_times": [0.5, 1.0],
            "maturity": 1.0,
            "params": {"coupon_rate": 0.06, "knock_in": 0.8, "strike": 1.0},
            "initial_fixing": 100.0,
            "barrier_breached": False,
        }],
        "spot": 92.0,
        "sigma": 0.2,
        "r": 0.05,
        "q": 0.0,
        "selected_trade_id": "LIVE-BRC-42",
    }
    response = client.post("/api/semistatic", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["selected_trade_id"] == "LIVE-BRC-42"
    assert [row["trade_id"] for row in body["pre_unwind"]] == ["LIVE-BRC-42"]
    assert body["pre_unwind"][0]["barrier"] == pytest.approx(80.0)
    assert body["pre_unwind"][0]["barrier_type"] == "KI"
    assert body["pre_unwind"][0]["lifecycle_action"] == "Maintain static strip"
    assert body["pre_unwind"][0]["target_action_pct"] is None
    assert body["pre_unwind"][0]["monitoring"] == "2 dates"
    assert body["pre_unwind"][0]["executed_action_pct"] == 0.0
    assert body["portfolio"] and body["tracking"]
    assert "cash_delta_target_1pct" in body["risk_ladder"][0]
    assert "residual_cash_delta_1pct" in body["summary"]


def test_outcome_lab_connects_issuance_hedging_and_ccr(client):
    response = client.get("/api/outcomes")
    assert response.status_code == 200
    body = response.json()
    assert body["issuance"]["n_issuances"] > 100
    assert len(body["hedge"]["strategies"]) == 4
    assert body["case_study"]["ccr_outcome"]["decision"] in {
        "APPROVED", "REJECTED", "MANUAL_REVIEW",
    }
    assert body["case_study"]["recommendation"]
    assert body["contract_id"] == body["case_study"]["contract_id"]
    assert body["contract_id"] == body["source_trade"]["trade_id"]
    assert body["contract_id"].startswith("NOTE-")
    structure = body["case_study"]["structure"]
    assert structure["fair_coupon_before_xva_pct"] >= structure["offered_coupon_after_xva_pct"]
    assert structure["target_shortfall_pct_pt"] == pytest.approx(
        max(12.0 - structure["offered_coupon_after_xva_pct"], 0.0), abs=0.01
    )
    assert body["issuance"]["terms"].startswith("2Y")


def test_structure_endpoint_solves(client):
    r = client.post(
        "/api/structure",
        json={"target_coupon": 0.12, "max_downside": 0.3, "maturity": 1.0, "obs_per_year": 4},
    )
    assert r.status_code == 200
    assert len(r.json()["pv_curve"]) > 0


def test_xva_endpoint_charges_and_decides(client):
    """The Phase-6 governance tab: an autocallable → charge + exposure profile + decision."""
    r = client.post(
        "/api/xva",
        json={"product_type": "autocallable", "notional": 100,
              "observation_times": [0.5, 1.0, 1.5, 2.0], "maturity": 2.0,
              "params": {"coupon_rate": 0.04, "autocall_level": 1.0, "coupon_barrier": 0.8,
                         "knock_in": 0.6, "memory": True},
              "cds_spread_bps": 300.0, "recovery_rate": 0.40, "ead_limit": 1e9},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["decision"] in {"APPROVED", "REJECTED", "MANUAL_REVIEW"}
    assert b["charge"]["total"] == pytest.approx(b["charge"]["cva"] + b["charge"]["fva"])
    assert len(b["profile"]) > 0 and b["metrics"]["ead"] > 0
    # The spread sweep is monotone: a wider counterparty spread costs more CVA.
    sweep = b["spread_curve"]
    assert sweep[0]["cva"] == pytest.approx(0.0, abs=1e-3) and sweep[-1]["cva"] > sweep[0]["cva"]


def test_xva_limit_breach_rejects(client):
    """An EAD limit below the trade's own EAD must reject the trade."""
    r = client.post(
        "/api/xva",
        json={"product_type": "autocallable", "notional": 100,
              "observation_times": [0.5, 1.0, 1.5, 2.0], "maturity": 2.0,
              "params": {"coupon_rate": 0.04, "knock_in": 0.6}, "ead_limit": 0.01},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["decision"] == "REJECTED" and b["limit_status"] == "FAIL"


def test_xva_rejects_worst_of(client):
    r = client.post("/api/xva", json={"product_type": "worst_of", "notional": 100, "params": {}})
    assert r.status_code == 400


def test_xva_full_depth_payload(client):
    """The full charge (CVA+FVA+KVA+MVA−DVA), XVA risk, capital, and stress ladder are returned and
    internally consistent when the depth knobs are switched on."""
    r = client.post(
        "/api/xva",
        json={"product_type": "autocallable", "notional": 100,
              "observation_times": [0.5, 1.0, 1.5, 2.0], "maturity": 2.0,
              "params": {"coupon_rate": 0.04, "knock_in": 0.6, "autocall_level": 1.0,
                         "coupon_barrier": 0.8, "memory": True},
              "cds_spread_bps": 300.0, "cds_1y_bps": 150.0, "own_cds_bps": 120.0,
              "cost_of_capital": 0.12, "include_mva": True, "wwr_beta": 0.5, "ead_limit": 1e9},
    )
    assert r.status_code == 200
    b = r.json()
    ch = b["charge"]
    assert ch["kva"] > 0.0 and ch["mva"] > 0.0          # KVA + MVA switched on
    assert ch["total"] == pytest.approx(ch["cva"] + ch["fva"] + ch["kva"] + ch["mva"] - ch["dva"])
    assert b["sensitivities"]["cs01"] > 0.0
    assert b["capital"]["economic"] > 0.0 and b["capital"]["regulatory_bacva"] > 0.0
    assert b["capital"]["saccr_ead"] > 0.0
    cvas = [row["cva"] for row in b["stress_ladder"]]
    assert cvas == sorted(cvas)                          # stress ladder monotone in the shock


def test_xva_returns_all_in_coupon_below_base(client):
    """The headline: the endpoint re-solves the coupon to par and to par − XVA; all-in < base."""
    r = client.post(
        "/api/xva",
        json={"product_type": "autocallable", "notional": 100,
              "observation_times": [0.5, 1.0, 1.5, 2.0], "maturity": 2.0,
              "params": {"coupon_rate": 0.04, "knock_in": 0.6, "autocall_level": 1.0,
                         "coupon_barrier": 0.8, "memory": True}, "cds_spread_bps": 300.0},
    )
    a = r.json()["all_in"]
    assert a is not None and a["infeasible"] is False
    assert a["coupon_all_in_pa"] < a["coupon_base_pa"]   # XVA eats into the offerable coupon
    assert a["drop_bp"] > 0.0


def test_xva_collateral_cuts_the_charge(client):
    """Turning on a CSA leaves only the close-out gap, so the total charge falls."""
    base = {"product_type": "autocallable", "notional": 100,
            "observation_times": [0.5, 1.0, 1.5, 2.0], "maturity": 2.0,
            "params": {"coupon_rate": 0.04, "knock_in": 0.6, "autocall_level": 1.0,
                       "coupon_barrier": 0.8, "memory": True}, "cds_spread_bps": 300.0}
    uncol = client.post("/api/xva", json={**base, "collateralised": False}).json()
    col = client.post("/api/xva", json={**base, "collateralised": True}).json()
    assert col["collateralised"] is True
    assert col["charge"]["cva"] < uncol["charge"]["cva"]


def test_refresh_rebuilds(client):
    r = client.post("/api/desk/refresh")
    assert r.status_code == 200
    assert r.json()["status"] == "rebuilt"


def test_api_token_gate(client, monkeypatch):
    monkeypatch.setattr(server, "_API_TOKEN", "s3cret")
    body = {"product_type": "autocallable", "notional": 100, "observation_times": [1.0],
            "params": {"coupon_rate": 0.03, "knock_in": 0.6}}
    assert client.post("/api/price", json=body).status_code == 401
    assert client.post("/api/price", json=body, headers={"X-API-Token": "s3cret"}).status_code == 200
    assert client.get("/api/outcomes").status_code == 401
    assert client.post("/api/semistatic", json={"trades": [], "spot": 100, "sigma": .2,
                       "r": .05, "q": 0}).status_code == 401


def test_stale_desk_serves_immediately_and_revalidates_in_background(client, monkeypatch):
    import threading

    server._desk()  # ensure a payload exists
    old_payload = server._cache.payload
    monkeypatch.setattr(server, "_DESK_TTL", 0.0)  # everything is now stale

    release = threading.Event()
    marker = dict(old_payload, marker="rebuilt")

    def slow_build(**kw):
        assert release.wait(timeout=10)
        return type("D", (), {"payload": marker})()

    monkeypatch.setattr(server, "build_desk_data", slow_build)
    served = server._desk()  # must NOT block on the in-flight rebuild
    assert served is old_payload

    release.set()
    assert server._rebuild_thread is not None
    server._rebuild_thread.join(timeout=10)
    assert server._cache.payload.get("marker") == "rebuilt"
    # and once rebuilt, subsequent calls serve the fresh payload
    monkeypatch.setattr(server, "_DESK_TTL", 3600.0)
    assert server._desk().get("marker") == "rebuilt"


def test_structure_flags_a_note_that_outlives_its_volatility_data(client):
    """A 1.5y note quoted off a 60-day surface slice looked identical in the response to one
    quoted off a 2-year slice. Extrapolation is sometimes unavoidable; being silent about it
    is not."""
    r = client.post(
        "/api/structure",
        json={"target_coupon": 0.18, "max_downside": 0.2, "maturity": 1.5, "obs_per_year": 4},
    )
    assert r.status_code == 200
    b = r.json()
    assert "vol_extrapolated" in b and "vol_tau" in b
    if b["vol_tau"] is not None and b["vol_extrapolated"]:
        assert b["data_warning"] and "extrapolating" in b["data_warning"]
    # A note comfortably inside the trusted tenor must not be flagged.
    short = client.post(
        "/api/structure",
        json={"target_coupon": 0.10, "max_downside": 0.2, "maturity": 0.25, "obs_per_year": 4},
    ).json()
    if short["vol_tau"] is not None and short["vol_tau"] >= 0.30:
        assert not short["vol_extrapolated"]
        assert short["data_warning"] is None
