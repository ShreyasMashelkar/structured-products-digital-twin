"""Generate a realistic desk of structured notes (L8).

Produces a deterministic, varied book of autocallables — spread over coupons, barriers and
maturities — so the book/replay machinery has a credible population to mark and risk-manage.
A real generator would also mix BRCs and capital-protected notes across underlyings; this
slice keeps to the flagship autocallable on one name.
"""

from __future__ import annotations

import numpy as np

from spdt.book.book import Trade
from spdt.products.catalog import Autocallable


def generate_autocallable_book(
    n: int, *, initial_fixing: float, underlying: str = "NIFTY", seed: int = 0
) -> list[Trade]:
    """A deterministic book of ``n`` autocallables struck at ``initial_fixing``."""
    rng = np.random.default_rng(seed)
    trades: list[Trade] = []
    for i in range(n):
        maturity = float(rng.choice([1.0, 1.5, 2.0]))
        n_obs = round(maturity * 4)  # quarterly observations
        observation_times = tuple((j + 1) * 0.25 for j in range(n_obs))
        knock_in = round(float(rng.uniform(0.50, 0.70)), 4)
        note = Autocallable(
            notional=100.0,
            observation_times=observation_times,
            coupon_rate=round(float(rng.uniform(0.015, 0.04)), 4),
            autocall_level=1.0,
            coupon_barrier=round(float(rng.uniform(0.70, 0.90)), 4),
            knock_in=knock_in,
            memory=bool(rng.integers(0, 2)),
            initial_fixing=initial_fixing,
        )
        trades.append(Trade(f"NOTE-{i:03d}", note, underlying=underlying))
    return trades
