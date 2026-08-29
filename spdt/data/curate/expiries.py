"""Choosing which expiries to calibrate on.

Shared because the same mistake was available at two layers: the ingest picks which contracts
to *fetch*, the curation layer picks which of the fetched ones to *keep*, and "nearest N" is
the obvious rule at both. It is the wrong rule at both. On NIFTY the nearest four contracts
are weeklies inside a month; on SPX the nearest six span seventeen days out of a chain that
quotes to five years. Either way the calibrated surface stops short of the notes being priced
against it.
"""

from __future__ import annotations

from datetime import date as Date
from math import log

from spdt.core.types import year_fraction


def select_term_spanning_expiries(
    expiries: list[Date], as_of: Date, n: int
) -> list[Date]:
    """Pick up to ``n`` expiries spread across the term structure, not merely the nearest ``n``.

    Taking the nearest N is the obvious rule and, on NIFTY, a damaging one: the four nearest
    contracts are all weeklies inside a month, so the calibrated surface reaches ~25 days while
    the master lists expiries out to 4.8 years. Everything longer than a month then prices off
    the front-month ATM vol — a 1.5-year note valued on a 25-day smile.

    Selection is log-spaced in tenor, which keeps the front dense (where the smile has the most
    curvature and the quotes are best) while still reaching the long end.
    """
    dated = sorted({e for e in expiries if e > as_of})
    if len(dated) <= n or n <= 0:
        return dated
    if n == 1:
        return dated[:1]  # one slot: the front contract, and no spacing to compute
    taus = [year_fraction(as_of, e) for e in dated]
    lo, hi = log(taus[0]), log(taus[-1])
    picked: list[Date] = []
    for i in range(n):
        target = lo + (hi - lo) * i / (n - 1)
        best = min(
            (e for e in dated if e not in picked),
            key=lambda e: abs(log(year_fraction(as_of, e)) - target),
            default=None,
        )
        if best is not None:
            picked.append(best)
    return sorted(picked)
