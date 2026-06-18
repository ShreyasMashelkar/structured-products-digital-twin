"""Objective → structure proposer (L6).

Maps a plain-language client brief to a candidate :class:`~spdt.products.termsheet.TermSheet`.
This is the "front-office magic": "I want income and can stomach 30% down" becomes a Phoenix
autocallable with a knock-in near 70 and a quarterly conditional coupon. The proposed coupon
is only an indicative starting point — the structurer then solves it (or the knock-in) to par
with :func:`spdt.structurer.solver.solve_to_par`.
"""

from __future__ import annotations

from dataclasses import dataclass

from spdt.products.termsheet import TermSheet


@dataclass(frozen=True)
class ClientBrief:
    """A client's request in their own terms."""

    target_coupon: float  # desired annual coupon, e.g. 0.12
    max_downside: float  # drawdown they can stomach, e.g. 0.30 → knock-in at 70%
    maturity_years: float = 1.0
    observations_per_year: int = 4


def propose_autocallable(brief: ClientBrief, *, notional: float = 100.0) -> TermSheet:
    """Translate a brief into a Phoenix-autocallable term sheet (indicative)."""
    n_obs = round(brief.maturity_years * brief.observations_per_year)
    if n_obs < 1:
        raise ValueError("brief implies fewer than one observation")
    step = 1.0 / brief.observations_per_year
    observation_times = tuple(round((i + 1) * step, 10) for i in range(n_obs))

    knock_in = round(1.0 - brief.max_downside, 10)  # 30% down ⇒ KI at 70%
    return TermSheet(
        product_type="autocallable",
        underlyings=("NIFTY",),
        notional=notional,
        observation_times=observation_times,
        params={
            "coupon_rate": brief.target_coupon / brief.observations_per_year,  # per period
            "autocall_level": 1.0,
            "coupon_barrier": knock_in,
            "knock_in": knock_in,
            "memory": True,  # Phoenix
        },
    )
