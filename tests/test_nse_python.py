"""Tests for the nsepython live option-chain source — parsing is pure, the fetch is mocked.

Live NSE access can't run in CI (NSE blocks non-browser / datacenter traffic), so we test the parse
on a fixture shaped like ``nse_optionchain_scrapper`` output and stub the network call.
"""

from datetime import date

import pytest

from spdt.core.types import SourceTag
from spdt.data.ingest.nse_python import NsePythonSource, parse_option_chain

_AS_OF = date(2026, 6, 22)
_PAYLOAD = {
    "records": {
        "underlyingValue": 22000.0,
        "data": [
            {"strikePrice": 21500, "expiryDate": "26-Jun-2026",
             "CE": {"lastPrice": 600.0}, "PE": {"lastPrice": 55.0}},
            {"strikePrice": 22000, "expiryDate": "26-Jun-2026",
             "CE": {"lastPrice": 300.0}, "PE": {"lastPrice": 280.0}},
            {"strikePrice": 22500, "expiryDate": "26-Jun-2026",
             "CE": {"lastPrice": 120.0}, "PE": {"lastPrice": 0.0}},  # PE unpriced → dropped
        ],
    }
}


def test_parse_option_chain_maps_spot_and_priced_legs():
    raw = parse_option_chain(_PAYLOAD, _AS_OF, "NIFTY", risk_free_rate=0.065,
                             funding_spread=0.012, dividend_yield=0.013)
    assert raw.spot == 22000.0
    assert raw.source is SourceTag.OBSERVED
    # 3 calls + 2 puts (the zero-priced put is dropped)
    assert len(raw.option_chain) == 5
    assert all(q.expiry == date(2026, 6, 26) for q in raw.option_chain)
    calls = [q for q in raw.option_chain if q.is_call]
    assert {q.strike for q in calls} == {21500.0, 22000.0, 22500.0}
    assert raw.ois_zero_rates  # flat fallback rate populated at the chain's expiry


def test_parse_rejects_empty_or_unpriced_chain():
    with pytest.raises(ValueError):
        parse_option_chain({"records": {"underlyingValue": 22000.0, "data": []}},
                           _AS_OF, "NIFTY", risk_free_rate=0.065, funding_spread=0.012,
                           dividend_yield=0.013)


def test_fetch_uses_nsepython_scrapper(monkeypatch):
    """NsePythonSource.fetch calls nse_optionchain_scrapper and parses its result — network stubbed."""
    import nsepython

    monkeypatch.setattr(nsepython, "nse_optionchain_scrapper", lambda underlying: _PAYLOAD)
    raw = NsePythonSource().fetch(_AS_OF, "NIFTY")
    assert raw.spot == 22000.0 and len(raw.option_chain) == 5
