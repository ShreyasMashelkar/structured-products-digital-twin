"""Tests for the NSE corporate-bond ingest — parse traded yields, derive spread-over-OIS.

Fixture-tested like every other source; the real file format gets a reconciliation pass
when first downloaded (columns marked in the module).
"""

from datetime import date
from math import exp

import pytest

from spdt.core.types import Curve, year_fraction
from spdt.data.ingest.nse_bonds import BondTrade, bond_implied_spreads, parse_bond_trades

_CSV = """SYMBOL,SERIES,ISSUER,COUPON,MATURITY,WAP,WAY,TRADES
HDFCB26,YL,HDFC BANK LIMITED,7.80,30-Jul-2026,101.20,7.95,12
HDFCB28,YL,HDFC BANK LIMITED,8.05,30-Jul-2028,100.10,8.40,7
JUNK,XX,BAD ROW,,,,-,
NABARD27,YL,NABARD,7.40,15-Mar-2027,99.80,7.55,3
"""

_ANCHOR = date(2026, 7, 10)


def _flat_ois(rate=0.065):
    pillars = tuple(date(2026 + i, 7, 30) for i in range(4))
    dfs = {p: exp(-rate * year_fraction(_ANCHOR, p)) for p in pillars}
    return Curve(anchor=_ANCHOR, pillars=pillars, discount_factors=dfs)


def test_parse_skips_malformed_rows_and_normalizes():
    trades = parse_bond_trades(_CSV)
    assert len(trades) == 3  # junk row dropped
    hdfc26 = trades[0]
    assert isinstance(hdfc26, BondTrade)
    assert hdfc26.issuer == "HDFC BANK LIMITED"
    assert hdfc26.maturity == date(2026, 7, 30)
    assert hdfc26.yield_pct == pytest.approx(7.95)


def test_spreads_are_yield_minus_ois_at_matching_tenor():
    trades = parse_bond_trades(_CSV)
    spreads = bond_implied_spreads(trades, _flat_ois(0.065), issuer="HDFC BANK LIMITED")
    assert set(spreads) == {date(2026, 7, 30), date(2028, 7, 30)}
    assert spreads[date(2026, 7, 30)] == pytest.approx(0.0795 - 0.065, abs=1e-3)
    assert spreads[date(2028, 7, 30)] == pytest.approx(0.084 - 0.065, abs=1e-3)


def test_issuer_filter_and_empty_result():
    trades = parse_bond_trades(_CSV)
    assert bond_implied_spreads(trades, _flat_ois(), issuer="NOBODY") == {}
