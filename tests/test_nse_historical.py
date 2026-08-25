"""Legacy NSE bhavcopy parsing (network-free): pre-UDiFF schema → RawMarketData.

The round-trip that matters is the implied spot: the legacy archive has no ``UndrlygPric``
column, so spot is backed out of the near index future. If that inversion is wrong every
log-moneyness downstream is shifted and the whole historical surface is silently biased.
"""

from datetime import date
from math import exp

import pandas as pd
import pytest

from spdt.core.types import SourceTag
from spdt.data.curate import invert_chain
from spdt.data.curate.bs_inversion import bs_price
from spdt.data.ingest.nse_historical import (
    UDIFF_CUTOVER,
    bhavcopy_source_for,
    legacy_bhavcopy_url,
    parse_legacy_bhavcopy,
)

AS_OF = date(2020, 3, 23)
EXPIRY = date(2020, 4, 30)
SPOT = 7578.0
RATE, DIV, VOL = 0.065, 0.013, 0.55  # COVID-era vol, deliberately far from a calm default

_TAU = (EXPIRY - AS_OF).days / 365.0


def _sample_bhavcopy() -> pd.DataFrame:
    """A DataFrame mimicking the real legacy F&O bhavcopy schema and content."""
    forward = SPOT * exp((RATE - DIV) * _TAU)
    discount = exp(-RATE * _TAU)
    rows = [
        # Near index future — the row spot is recovered from.
        {"INSTRUMENT": "FUTIDX", "SYMBOL": "NIFTY", "EXPIRY_DT": "30-Apr-2020",
         "STRIKE_PR": 0.0, "OPTION_TYP": "XX", "SETTLE_PR": forward, "OPEN_INT": 5_000_000},
    ]
    for strike in (6500.0, 7000.0, 7500.0, 8000.0, 8500.0, 9000.0):
        for opt, is_call in (("CE", True), ("PE", False)):
            rows.append(
                {"INSTRUMENT": "OPTIDX", "SYMBOL": "NIFTY", "EXPIRY_DT": "30-Apr-2020",
                 "STRIKE_PR": strike, "OPTION_TYP": opt,
                 "SETTLE_PR": bs_price(forward, strike, _TAU, VOL, discount, is_call),
                 "OPEN_INT": 100_000}
            )
    # Noise that must be filtered: another name, and a zero settlement print.
    rows.append({"INSTRUMENT": "OPTSTK", "SYMBOL": "RELIANCE", "EXPIRY_DT": "30-Apr-2020",
                 "STRIKE_PR": 1000.0, "OPTION_TYP": "CE", "SETTLE_PR": 50.0, "OPEN_INT": 1000})
    rows.append({"INSTRUMENT": "OPTIDX", "SYMBOL": "NIFTY", "EXPIRY_DT": "30-Apr-2020",
                 "STRIKE_PR": 20000.0, "OPTION_TYP": "CE", "SETTLE_PR": 0.0, "OPEN_INT": 0})
    return pd.DataFrame(rows)


def _parse() -> "object":
    return parse_legacy_bhavcopy(
        _sample_bhavcopy(), AS_OF, "NIFTY",
        risk_free_rate=RATE, funding_spread=0.012, dividend_yield=DIV,
    )


def test_url_has_the_legacy_uppercase_month_format():
    assert legacy_bhavcopy_url(AS_OF).endswith(
        "/DERIVATIVES/2020/MAR/fo23MAR2020bhav.csv.zip"
    )


def test_spot_is_recovered_from_the_near_future():
    """The whole point of this source: no UndrlygPric column, so invert F = S·e^((r−q)τ)."""
    assert _parse().spot == pytest.approx(SPOT, rel=1e-9)


def test_only_this_underlyings_priced_options_survive():
    raw = _parse()
    assert len(raw.option_chain) == 12  # 6 strikes × {CE, PE}; RELIANCE and the 0.0 print dropped
    assert all(q.expiry == EXPIRY and q.settlement_price > 0.0 for q in raw.option_chain)
    assert raw.source is SourceTag.OBSERVED


def test_inverted_vols_round_trip_to_the_vol_the_prints_were_made_at():
    """Spot → forward → IV must return the 55% the sample was priced at, or spot is wrong."""
    raw = _parse()
    from spdt.data import build_snapshot

    snapshot = build_snapshot(raw)
    points = invert_chain(raw, snapshot.ois_curve)
    assert points, "no quote inverted"
    assert all(p.implied_vol == pytest.approx(VOL, abs=5e-3) for p in points)


def test_source_selection_follows_the_udiff_cutover():
    from spdt.data.ingest.nse_bhavcopy import NseBhavcopySource
    from spdt.data.ingest.nse_historical import NseHistoricalSource

    assert isinstance(bhavcopy_source_for(AS_OF), NseHistoricalSource)
    assert isinstance(bhavcopy_source_for(UDIFF_CUTOVER), NseBhavcopySource)
