"""CBOE chain parsing (network-free): delayed-quote JSON → RawMarketData with two-sided markets."""

from datetime import date

import pytest

from spdt.core.types import SourceTag
from spdt.data.ingest.cboe import cboe_url, parse_chain, parse_occ_symbol
from spdt.data.ingest import RawOptionQuote

AS_OF = date(2026, 8, 17)


def _payload() -> dict:
    """A payload mimicking the real CBOE feed, including the rows that must be filtered."""
    options = [
        # Genuine two-sided markets.
        {"option": "SPX270115C07800000", "bid": 300.0, "ask": 310.0,
         "volume": 120.0, "open_interest": 4500.0, "last_trade_price": 305.0},
        {"option": "SPX270115P07800000", "bid": 280.0, "ask": 290.0,
         "volume": 90.0, "open_interest": 3900.0, "last_trade_price": 284.0},
        # LEAPS — the whole reason for this source.
        {"option": "SPX311219C08000000", "bid": 1500.0, "ask": 1560.0,
         "volume": 2.0, "open_interest": 800.0, "last_trade_price": 1530.0},
        # No bid: nobody will buy at any price, so the ask alone is not a valuation.
        {"option": "SPX270115C12000000", "bid": 0.0, "ask": 0.5,
         "volume": 0.0, "open_interest": 10.0, "last_trade_price": 0.4},
        # Already expired relative to as_of.
        {"option": "SPX260817C07700000", "bid": 60.0, "ask": 62.0,
         "volume": 5.0, "open_interest": 100.0, "last_trade_price": 61.0},
        # Malformed contract code — must be skipped, not fatal.
        {"option": "NOT-AN-OCC-SYMBOL", "bid": 1.0, "ask": 2.0,
         "volume": 1.0, "open_interest": 1.0, "last_trade_price": 1.5},
    ]
    return {"data": {"current_price": 7768.6, "close": 7768.6, "options": options}}


def test_occ_symbols_parse_to_expiry_strike_and_right():
    assert parse_occ_symbol("SPX270115C07800000") == (date(2027, 1, 15), 7800.0, True)
    assert parse_occ_symbol("SPY260817P00500000") == (date(2026, 8, 17), 500.0, False)


def test_malformed_symbols_return_none_rather_than_raising():
    """One bad row in a 30,000-row feed must not destroy the chain."""
    assert parse_occ_symbol("NOT-AN-OCC-SYMBOL") is None
    assert parse_occ_symbol("SPX279915C07800000") is None  # month 99


def test_url_uses_the_underscore_prefix_for_cash_index():
    assert cboe_url("SPX").endswith("/_SPX.json")
    assert cboe_url("SPY").endswith("/SPY.json")
    assert cboe_url("TSLA").endswith("/TSLA.json")  # single equities pass through
    with pytest.raises(ValueError, match="neither a mapped index"):
        cboe_url("not-a-ticker")


def test_only_live_two_sided_contracts_survive():
    raw = parse_chain(_payload(), "SPX", as_of=AS_OF)
    assert raw.source is SourceTag.OBSERVED
    assert raw.spot == pytest.approx(7768.6)
    strikes = {(q.expiry, q.strike, q.is_call) for q in raw.option_chain}
    assert strikes == {
        (date(2027, 1, 15), 7800.0, True),
        (date(2027, 1, 15), 7800.0, False),
        (date(2031, 12, 19), 8000.0, True),
    }


def test_mid_becomes_the_price_and_the_two_sided_market_is_retained():
    """Existing consumers see a single price; the cost models still get the real spread."""
    raw = parse_chain(_payload(), "SPX", as_of=AS_OF)
    call = next(q for q in raw.option_chain if q.strike == 7800.0 and q.is_call)
    assert call.settlement_price == pytest.approx(305.0)  # mid of 300/310
    assert (call.bid, call.ask) == (300.0, 310.0)
    assert call.spread == pytest.approx(10.0)
    assert call.relative_spread == pytest.approx(10.0 / 305.0)


def test_leaps_reach_past_five_years():
    """The tenor coverage that the NSE settlement archive could not provide."""
    raw = parse_chain(_payload(), "SPX", as_of=AS_OF)
    assert max(q.expiry for q in raw.option_chain).year == 2031


def test_a_quote_without_a_two_sided_market_reports_none_not_zero():
    """'Not published' and 'zero spread' are different claims and must not be conflated."""
    settlement_only = RawOptionQuote(
        expiry=date(2027, 1, 15), strike=7800.0, is_call=True, settlement_price=305.0
    )
    assert settlement_only.spread is None
    assert settlement_only.relative_spread is None
    assert settlement_only.mid == pytest.approx(305.0)  # falls back to the mark


def test_requiring_two_sided_can_be_relaxed():
    relaxed = parse_chain(_payload(), "SPX", as_of=AS_OF, require_two_sided=False)
    assert len(relaxed.option_chain) > 3  # the zero-bid contract now survives on last trade


def test_an_empty_chain_is_an_error_not_an_empty_snapshot():
    with pytest.raises(ValueError, match="no usable"):
        parse_chain({"data": {"current_price": 100.0, "options": []}}, "SPX", as_of=AS_OF)
