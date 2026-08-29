"""Tests for the futures-implied dividend yield — cost-of-carry inversion, pure math.

Also covers the XTSSource hookup: when the master has a futures contract, the fetched raw
data carries the implied yield; with no futures quote it falls back to the configured
assumption.
"""

from datetime import date
from math import exp, log

import pytest

from spdt.core.types import year_fraction
from spdt.data.curate.implied_dividend import implied_dividend_yield
from spdt.data.ingest.xts import XTSSource
# No `tests.` prefix: importing `webapp.server` puts the vendored `xva/` on sys.path, whose
# real `tests` package shadows this directory's namespace package. Plain module names resolve
# via pytest's rootless-test path insertion regardless.
from test_xts_ingest import (  # noqa: E402
    _NOW,
    _client,
    _fo_future_row,
    _fo_master_row,
    _touchline_json,
)


def test_recovers_known_yield_from_carry():
    spot, r, q, t = 24000.0, 0.065, 0.013, 0.25
    fut = spot * exp((r - q) * t)
    assert implied_dividend_yield(spot, fut, t, r) == pytest.approx(q)


def test_rejects_degenerate_inputs():
    for spot, fut, t in [(0.0, 24100.0, 0.25), (24000.0, 0.0, 0.25), (24000.0, 24100.0, 0.0)]:
        with pytest.raises(ValueError):
            implied_dividend_yield(spot, fut, t, 0.065)


def test_rejects_implausible_yield():
    # futures way below spot → implied q ≈ 43%: a bad quote, not a dividend
    with pytest.raises(ValueError, match="implausible"):
        implied_dividend_yield(24000.0, 21900.0, 0.25, 0.065)


def test_xts_source_uses_futures_implied_dividend(monkeypatch):
    client = _client()
    as_of, fut_expiry = date(2026, 7, 10), date(2026, 7, 30)
    spot, fut_price, r = 24050.0, 24098.0, 0.065
    nsefo = "\n".join([
        _fo_master_row(1, 24000, "CE"),
        _fo_master_row(2, 24000, "PE"),
        _fo_future_row(7, expiry="2026-07-30T14:30:00"),
    ])
    prices = {26000: spot, 1: 250.0, 2: 180.0, 7: fut_price}

    def fake_request(method, path, body=None):
        if path.endswith("/auth/login"):
            return {"type": "success", "result": {"token": "TOK", "userID": "U1"}}
        if "/instruments/indexlist" in path:
            return {"type": "success", "result": {"indexList": ["NIFTY 50_26000"]}}
        if path.endswith("/instruments/master"):
            return {"type": "success", "result": nsefo}
        return {"type": "success", "result": {"listQuotes": [
            _touchline_json(
                i["exchangeInstrumentID"], ltp=prices[i["exchangeInstrumentID"]],
                bid=prices[i["exchangeInstrumentID"]] - 0.5,
                ask=prices[i["exchangeInstrumentID"]] + 0.5,
                segment=i["exchangeSegment"],
            )
            for i in body["instruments"]
        ]}}

    monkeypatch.setattr(client, "_request", fake_request)
    source = XTSSource(client=client, risk_free_rate=r, clock=lambda: _NOW)
    raw = source.fetch(as_of, "NIFTY")
    expected_q = r - log(fut_price / spot) / year_fraction(as_of, fut_expiry)
    assert raw.dividend_yield == pytest.approx(expected_q)
    assert raw.dividend_yield != 0.013  # no longer the assumption


# --- the strip fit: carry from the slope, so a stale spot cannot corrupt q -------------------


def test_strip_recovers_known_carry():
    from spdt.data.curate.implied_dividend import implied_dividend_yield_from_strip

    spot, r, q = 24000.0, 0.065, 0.013
    strip = [(t, spot * exp((r - q) * t)) for t in (0.09, 0.17, 0.24)]
    assert implied_dividend_yield_from_strip(strip, r) == pytest.approx(q)


def test_strip_is_immune_to_a_stale_spot():
    """The live bug: the cash index printed ~0.2% behind the futures, and dividing that lag
    by a 32-day T turned it into a −2% 'dividend'. The slope never looks at spot."""
    from spdt.data.curate.implied_dividend import implied_dividend_yield_from_strip

    true_spot, r, q = 24136.3, 0.065, 0.013
    strip = [(t, true_spot * exp((r - q) * t)) for t in (0.0877, 0.1644, 0.2384)]

    stale_spot = true_spot * 0.998  # what the index tick actually said
    single = r - log(strip[0][1] / stale_spot) / strip[0][0]
    assert single < 0.0  # the old path: a negative dividend out of a 0.2% spot lag

    assert implied_dividend_yield_from_strip(strip, r) == pytest.approx(q)


def test_strip_needs_two_contracts_and_a_real_lever_arm():
    from spdt.data.curate.implied_dividend import implied_dividend_yield_from_strip

    with pytest.raises(ValueError, match="at least two"):
        implied_dividend_yield_from_strip([(0.1, 24100.0)], 0.065)
    # two contracts a few days apart: the slope is quote noise, not a carry
    with pytest.raises(ValueError, match="too short"):
        implied_dividend_yield_from_strip([(0.09, 24100.0), (0.10, 24110.0)], 0.065)


def test_a_negative_implied_yield_is_rejected_not_returned():
    """An index cannot pay a negative dividend. When the futures carry above the risk-free
    rate — routine in India, where the strip embeds a financing premium — the inversion is
    measuring funding, not dividends, and must not be believed."""
    from spdt.data.curate.implied_dividend import implied_dividend_yield_from_strip

    spot, r = 24000.0, 0.0526
    strip = [(t, spot * exp(0.0614 * t)) for t in (0.0877, 0.1644, 0.2384)]  # live carry
    with pytest.raises(ValueError, match="implausible"):
        implied_dividend_yield_from_strip(strip, r)
    with pytest.raises(ValueError, match="implausible"):
        implied_dividend_yield(spot, spot * exp(0.0614 * 0.25), 0.25, r)
