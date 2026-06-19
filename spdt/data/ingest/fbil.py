"""FBIL rate inputs: build calibrating instruments from published benchmarks (design doc §2.2).

FBIL (Financial Benchmarks India) publishes the daily T-bill curve (91/182/364-day) and the
MIBOR-OIS par rates that anchor the rupee risk-free curve. This module turns those published
quotes into :class:`~spdt.data.curate.rate_bootstrap.RateInstrument` objects ready for the
bootstrap; the short end (≤1y) comes in as simple-interest T-bills, the longer end as OIS par
swaps.

The *values* still have to be sourced — pass them in from FBIL's daily file (a fetch
analogous to the NSE bhavcopy downloader). This helper owns the term-structure construction,
which is the part the pricing curve actually depends on.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

from spdt.data.curate.rate_bootstrap import RateInstrument


def fbil_instruments(
    anchor: date,
    *,
    tbill_yields: Mapping[int, float],
    ois_par_rates: Mapping[float, float],
) -> list[RateInstrument]:
    """Assemble bootstrap instruments from FBIL T-bill yields and OIS par rates.

    ``tbill_yields`` is keyed by tenor in **days** (e.g. ``{91: 0.0665, 182: 0.067}``);
    ``ois_par_rates`` by tenor in **years** (e.g. ``{1: 0.067, 2: 0.068, 5: 0.069}``).
    """
    instruments = [
        RateInstrument(anchor + timedelta(days=days), rate, kind="zero")
        for days, rate in tbill_yields.items()
    ]
    instruments += [
        RateInstrument(anchor + timedelta(days=round(365 * years)), rate, kind="ois")
        for years, rate in ois_par_rates.items()
    ]
    return sorted(instruments, key=lambda x: x.maturity)
