"""NSE bhavcopy parsing (network-free): UDiFF schema → RawMarketData → snapshot."""

from datetime import date
from math import exp

import pandas as pd
import pytest

from spdt.core.types import SourceTag, year_fraction
from spdt.data import build_snapshot
from spdt.data.curate import invert_chain
from spdt.data.curate.bs_inversion import bs_price
from spdt.data.ingest.nse_bhavcopy import fo_bhavcopy_url, parse_fo_bhavcopy

AS_OF = date(2024, 6, 17)
EXPIRY = date(2024, 7, 25)
SPOT = 22000.0


def _sample_bhavcopy() -> pd.DataFrame:
    """A small DataFrame mimicking the real UDiFF F&O bhavcopy schema and content."""
    tau = year_fraction(AS_OF, EXPIRY)
    forward = SPOT * exp((0.065 - 0.013) * tau)
    discount = exp(-0.065 * tau)
    rows = []
    for strike in (21000.0, 22000.0, 23000.0):
        for opt, is_call in (("CE", True), ("PE", False)):
            price = bs_price(forward, strike, tau, 0.18, discount, is_call)
            rows.append(
                {"TckrSymb": "NIFTY", "OptnTp": opt, "StrkPric": strike, "XpryDt": "2024-07-25",
                 "SttlmPric": price, "UndrlygPric": SPOT, "FinInstrmTp": "IDO"}
            )
    # Noise that must be filtered out: a future (not an option), another name, a zero print.
    rows.append({"TckrSymb": "NIFTY", "OptnTp": "XX", "StrkPric": 0.0, "XpryDt": "2024-07-25",
                 "SttlmPric": 21950.0, "UndrlygPric": SPOT, "FinInstrmTp": "IDF"})
    rows.append({"TckrSymb": "RELIANCE", "OptnTp": "CE", "StrkPric": 2900.0, "XpryDt": "2024-07-25",
                 "SttlmPric": 50.0, "UndrlygPric": 2890.0, "FinInstrmTp": "STO"})
    rows.append({"TckrSymb": "NIFTY", "OptnTp": "CE", "StrkPric": 30000.0, "XpryDt": "2024-07-25",
                 "SttlmPric": 0.0, "UndrlygPric": SPOT, "FinInstrmTp": "IDO"})
    return pd.DataFrame(rows)


def test_url_has_the_udiff_format():
    assert fo_bhavcopy_url(AS_OF).endswith("BhavCopy_NSE_FO_0_0_0_20240617_F_0000.csv.zip")


def test_parser_extracts_only_the_underlyings_options():
    raw = parse_fo_bhavcopy(
        _sample_bhavcopy(), AS_OF, "NIFTY",
        risk_free_rate=0.065, funding_spread=0.012, dividend_yield=0.013,
    )
    assert raw.source is SourceTag.OBSERVED  # real data, tagged observed (not synthetic)
    assert raw.spot == SPOT
    # 3 strikes × {call, put} = 6; the future, RELIANCE, and zero-print rows are dropped.
    assert len(raw.option_chain) == 6
    assert all(q.settlement_price > 0 for q in raw.option_chain)


def test_parsed_chain_builds_a_snapshot_and_inverts():
    raw = parse_fo_bhavcopy(
        _sample_bhavcopy(), AS_OF, "NIFTY",
        risk_free_rate=0.065, funding_spread=0.012, dividend_yield=0.013,
    )
    snap = build_snapshot(raw)
    assert snap.spots["NIFTY"] == SPOT
    assert snap.ois_curve.zero_rate(EXPIRY) == pytest.approx(0.065, abs=1e-9)
    points = invert_chain(raw, snap.ois_curve)
    # The contracts were priced at 18% vol, so inversion recovers ~0.18.
    assert all(p.implied_vol == pytest.approx(0.18, abs=1e-6) for p in points)


def test_parser_raises_when_underlying_absent():
    with pytest.raises(ValueError, match="no option rows"):
        parse_fo_bhavcopy(
            _sample_bhavcopy(), AS_OF, "BANKNIFTY",
            risk_free_rate=0.065, funding_spread=0.012, dividend_yield=0.013,
        )
