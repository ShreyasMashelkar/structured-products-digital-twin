"""FBIL ingestion: tenor parsing and instrument construction (network-free)."""

from datetime import date, timedelta

import pytest

from spdt.data.curate.rate_bootstrap import bootstrap_ois_curve
from spdt.data.ingest.fbil import (
    _tenor_to_days,
    instruments_from_fbil_entries,
)

ANCHOR = date(2026, 6, 11)

# A sample mirroring the live FBIL MIBOR-OIS response (rates in %, duplicated runs).
_OIS_ENTRIES = [
    {"tenorName": "1M", "rate": 5.38, "processRunDate": "2026-06-11 00:00:00"},
    {"tenorName": "3M", "rate": 5.45, "processRunDate": "2026-06-11 00:00:00"},
    {"tenorName": "6M", "rate": 5.65, "processRunDate": "2026-06-11 00:00:00"},
    {"tenorName": "1Y", "rate": 6.03, "processRunDate": "2026-06-11 00:00:00"},
    {"tenorName": "2Y", "rate": 6.21, "processRunDate": "2026-06-11 00:00:00"},
    {"tenorName": "5Y", "rate": 6.45, "processRunDate": "2026-06-11 00:00:00"},
    {"tenorName": "1Y", "rate": 6.03, "processRunDate": "2026-06-11 00:00:00"},  # dup run
]


@pytest.mark.parametrize(
    "label,days,yearly",
    [("7 Days", 7, False), ("14 Days", 14, False), ("6 Months", 182, False),
     ("1M", 30, False), ("9M", 274, False), ("1Y", 365, True), ("5Y", 1825, True)],
)
def test_tenor_parsing(label, days, yearly):
    assert _tenor_to_days(label) == (days, yearly)


def test_tenor_parsing_rejects_garbage():
    with pytest.raises(ValueError, match="tenor"):
        _tenor_to_days("overnight-ish")


def test_entries_become_instruments_with_right_kinds():
    insts = instruments_from_fbil_entries(_OIS_ENTRIES, ANCHOR)
    assert len(insts) == 6  # duplicate 1Y dropped
    by_mat = {i.maturity: i for i in insts}
    one_year = by_mat[ANCHOR + timedelta(days=365)]
    six_month = by_mat[ANCHOR + timedelta(days=182)]
    assert one_year.kind == "ois" and one_year.rate == pytest.approx(0.0603)  # yearly ⇒ swap
    assert six_month.kind == "zero"  # sub-year ⇒ money market


def test_fbil_curve_bootstraps_and_is_upward_sloping():
    insts = instruments_from_fbil_entries(_OIS_ENTRIES, ANCHOR)
    curve = bootstrap_ois_curve(ANCHOR, insts)
    z1 = curve.zero_rate(ANCHOR + timedelta(days=365))
    z5 = curve.zero_rate(ANCHOR + timedelta(days=1825))
    assert 0.05 < z1 < z5 < 0.07
