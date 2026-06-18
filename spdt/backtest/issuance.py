"""Historical backtesting: roll issuance on *realised* paths (L7).

A backtest is **not** a risk-neutral pricing exercise. Layer 4 prices under the risk-neutral
measure (drift ``r−q``) for fair value; this layer asks a different question — "had we issued
a fresh note every month, what would actually have happened?" — and answers it on the path
that *realised*, under the real-world drift ``μ``. Conflating the two is a classic error.

We slide an issuance window along one realised series, strike each note at that day's spot,
and evaluate its life (autocall / coupon / knock-in) deterministically on the realised path.
For a single underlying there is no survivorship bias; a multi-name version would need
point-in-time universe membership (otherwise autocall frequency is inflated).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np

from spdt.products.catalog import Autocallable


def generate_realized_series(
    n_days: int, *, s0: float = 100.0, mu: float = 0.08, sigma: float = 0.2, seed: int = 0,
    days_per_year: int = 252,
) -> np.ndarray:
    """One realised daily price path under the **real-world** drift ``μ`` (not ``r−q``)."""
    rng = np.random.default_rng(seed)
    dt = 1.0 / days_per_year
    shocks = (mu - 0.5 * sigma * sigma) * dt + sigma * np.sqrt(dt) * rng.standard_normal(n_days)
    return s0 * np.exp(np.concatenate([[0.0], np.cumsum(shocks)]))


@dataclass(frozen=True)
class IssuanceOutcome:
    """What one issued note actually did over its realised life."""

    autocalled: bool
    autocall_period: int | None  # observation index of early redemption, else None
    coupon_income: float
    principal: float
    total_payoff: float
    capital_loss: float  # notional − principal when held to maturity below the knock-in


def _evaluate_on_path(note: Autocallable, obs_spots: np.ndarray) -> IssuanceOutcome:
    """Run the autocallable's economics on a single realised observation path."""
    s0 = note.initial_fixing if note.initial_fixing is not None else float(obs_spots[0])
    n = note.notional
    missed = 0.0
    coupon_income = 0.0
    last = len(obs_spots) - 1

    for i, spot in enumerate(obs_spots):
        if spot >= note.coupon_barrier * s0:
            coupon = (missed + 1.0) * note.coupon_rate * n if note.memory else note.coupon_rate * n
            coupon_income += coupon
            missed = 0.0
        elif note.memory:
            missed += 1.0
        if i < last and spot >= note.autocall_level * s0:
            return IssuanceOutcome(True, i, coupon_income, n, coupon_income + n, 0.0)

    s_t = float(obs_spots[-1])
    if s_t <= note.knock_in * s0:
        principal = n * s_t / s0
        loss = n - principal
    else:
        principal, loss = n, 0.0
    return IssuanceOutcome(False, None, coupon_income, principal, coupon_income + principal, loss)


def roll_issuance(
    series: np.ndarray,
    note: Autocallable,
    *,
    issuance_step_days: int = 21,
    days_per_year: int = 252,
) -> list[IssuanceOutcome]:
    """Issue ``note`` every ``issuance_step_days`` along ``series`` and evaluate each life."""
    obs_days = [round(t * days_per_year) for t in note.observation_times]
    life = obs_days[-1]
    outcomes: list[IssuanceOutcome] = []
    for start in range(0, len(series) - life, issuance_step_days):
        struck = dataclasses.replace(note, initial_fixing=float(series[start]))
        obs_spots = np.array([series[start + d] for d in obs_days])
        outcomes.append(_evaluate_on_path(struck, obs_spots))
    return outcomes
