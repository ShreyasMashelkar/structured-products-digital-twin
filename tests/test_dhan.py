"""Tests for the DhanHQ option-chain source — parsing is pure, the network POST is mocked.

Live Dhan access needs a private token, so CI tests the parse on fixtures shaped like the v2 API and
stubs ``DhanSource._post`` (so no network and no credentials are needed).
"""

from datetime import date

import pytest

from spdt.core.types import SourceTag
from spdt.data.ingest.dhan import DhanSource, build_raw_market_data, parse_chain_legs

_AS_OF = date(2026, 6, 22)
_EXP1, _EXP2 = "2026-06-25", "2026-07-30"


def _chain(spot):
    return {"data": {"last_price": spot, "oc": {
        "24000.000000": {"ce": {"last_price": 250.0, "implied_volatility": 12.1},
                         "pe": {"last_price": 180.0, "implied_volatility": 13.0}},
        "24100.000000": {"ce": {"last_price": 190.0}, "pe": {"last_price": 0.0}},  # unpriced PE dropped
    }}, "status": "success"}


def test_parse_chain_legs_keeps_priced_legs_only():
    legs = parse_chain_legs(_chain(24050.0)["data"]["oc"], date(2026, 6, 25))
    # 24000 CE+PE priced, 24100 CE priced, 24100 PE zero → dropped ⇒ 3 quotes
    assert len(legs) == 3
    assert {(q.strike, q.is_call) for q in legs} == {(24000.0, True), (24000.0, False), (24100.0, True)}
    assert all(q.expiry == date(2026, 6, 25) for q in legs)


def test_build_raw_market_data_tags_observed_and_rejects_empty():
    legs = parse_chain_legs(_chain(24050.0)["data"]["oc"], date(2026, 6, 25))
    raw = build_raw_market_data(24050.0, legs, _AS_OF, risk_free_rate=0.065,
                                funding_spread=0.012, dividend_yield=0.013)
    assert raw.spot == 24050.0 and raw.source is SourceTag.OBSERVED and len(raw.option_chain) == 3
    with pytest.raises(ValueError):
        build_raw_market_data(24050.0, [], _AS_OF, risk_free_rate=0.065,
                              funding_spread=0.012, dividend_yield=0.013)


def test_fetch_unions_nearest_expiries(monkeypatch):
    """fetch() lists expiries, calls the chain for the nearest N, and unions their legs — mocked."""
    src = DhanSource(client_id="X", access_token="Y", n_expiries=2, rate_limit_s=0.0)
    calls: list[tuple[str, dict]] = []

    def fake_post(path, body):
        calls.append((path, body))
        if path.endswith("expirylist"):
            return {"data": ["2026-05-01", _EXP1, _EXP2], "status": "success"}  # past one filtered out
        return _chain(24013.1)

    monkeypatch.setattr(src, "_post", fake_post)
    raw = src.fetch(_AS_OF, "NIFTY")
    assert raw.spot == 24013.1
    assert len(raw.option_chain) == 6  # 3 legs × 2 expiries
    assert {q.expiry for q in raw.option_chain} == {date(2026, 6, 25), date(2026, 7, 30)}
    assert sum(1 for p, _ in calls if p.endswith("/optionchain")) == 2  # only the 2 future expiries


def test_fetch_without_credentials_raises():
    src = DhanSource(client_id=None, access_token=None)
    with pytest.raises(RuntimeError, match="credentials"):
        src.fetch(_AS_OF, "NIFTY")
