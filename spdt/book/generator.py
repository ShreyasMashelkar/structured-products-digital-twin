"""Generate a realistic desk of structured notes (L8).

Produces a deterministic, varied book of autocallables — spread over coupons, barriers and
maturities — so the book/replay machinery has a credible population to mark and risk-manage.
A real generator would also mix BRCs and capital-protected notes across underlyings; this
slice keeps to the flagship autocallable on one name.
"""

from __future__ import annotations

import numpy as np

from spdt.book.book import Trade
from spdt.products.catalog import (
    Autocallable,
    BarrierReverseConvertible,
    CapitalProtectedNote,
    ReverseConvertible,
)
from spdt.products.graph import Product


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


# Deterministic product mix, autocallable-dominant so the book stays structurally short vol
# (only the capital-protected note is long vol; it is kept sparse). The pattern cycles every 6.
_MIX = ("autocallable", "autocallable", "brc", "autocallable", "reverse_convertible",
        "capital_protected")


def _autocallable(rng, fixing: float) -> Autocallable:
    maturity = float(rng.choice([1.0, 1.5, 2.0]))
    obs = tuple((j + 1) * 0.25 for j in range(round(maturity * 4)))
    return Autocallable(
        100.0, obs, round(float(rng.uniform(0.015, 0.04)), 4), 1.0,
        round(float(rng.uniform(0.70, 0.90)), 4), round(float(rng.uniform(0.50, 0.70)), 4),
        memory=bool(rng.integers(0, 2)), initial_fixing=fixing,
    )


def generate_mixed_book(
    n: int, *, initial_fixing: float, underlying: str = "NIFTY", seed: int = 0
) -> list[Trade]:
    """A deterministic book mixing autocallables with BRCs, reverse convertibles and CPNs.

    The flagship autocallable still dominates; a sprinkling of income (BRC, reverse convertible)
    and protection (capital-protected) notes makes the blotter a realistic multi-product desk
    rather than a single-product book. All notes are struck at ``initial_fixing``.
    """
    rng = np.random.default_rng(seed)
    trades: list[Trade] = []
    for i in range(n):
        kind = _MIX[i % len(_MIX)]
        maturity = float(rng.choice([1.0, 1.5, 2.0]))
        obs = tuple((j + 1) * 0.5 for j in range(round(maturity * 2)))  # semi-annual income notes
        note: Product
        if kind == "autocallable":
            note = _autocallable(rng, initial_fixing)
        elif kind == "brc":
            # Coupons are semi-annual, but the knock-in is watched quarterly — the barrier
            # schedule is deliberately denser than (and distinct from) the coupon schedule.
            quarterly = tuple((j + 1) * 0.25 for j in range(round(maturity * 4)))
            note = BarrierReverseConvertible(
                100.0, obs, round(float(rng.uniform(0.05, 0.09)), 4),
                strike=1.0, knock_in=round(float(rng.uniform(0.60, 0.75)), 4),
                barrier_monitoring=quarterly, initial_fixing=initial_fixing,
            )
        elif kind == "reverse_convertible":
            note = ReverseConvertible(
                100.0, obs, round(float(rng.uniform(0.07, 0.11)), 4),
                strike=1.0, initial_fixing=initial_fixing,
            )
        else:  # capital_protected
            note = CapitalProtectedNote(
                100.0, maturity=float(rng.choice([1.0, 2.0, 3.0])),
                protection=1.0, participation=round(float(rng.uniform(0.6, 1.2)), 4),
                strike=1.0, cap=None,
            )
        trades.append(Trade(f"NOTE-{i:03d}", note, underlying=underlying))
    return trades
