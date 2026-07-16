"""Futures-implied dividend yield — replace the flat assumption with an observed input.

Under cost-of-carry, ``F = S·exp((r − q)·T)``, so a traded index future implies the
market's own dividend expectation: ``q = r − ln(F/S)/T``. With a live futures quote (XTS)
and the FBIL rate this turns the snapshot's dividend yield from an assumption into a
derived market observable.
"""

from __future__ import annotations

from math import log

# Sane bounds for an implied *index* dividend yield: outside these the futures quote is
# bad (stale, crossed, wrong contract), not a real dividend signal.
_Q_MIN, _Q_MAX = -0.05, 0.10


def implied_dividend_yield(spot: float, futures_price: float, t_years: float, r: float) -> float:
    """Invert cost-of-carry for ``q``. Raises on degenerate inputs or implausible output."""
    if spot <= 0.0 or futures_price <= 0.0 or t_years <= 0.0:
        raise ValueError("implied dividend needs positive spot, futures price and maturity")
    q = r - log(futures_price / spot) / t_years
    if not _Q_MIN <= q <= _Q_MAX:
        raise ValueError(
            f"implausible implied dividend yield {q:.2%} — check the futures quote"
        )
    return q
