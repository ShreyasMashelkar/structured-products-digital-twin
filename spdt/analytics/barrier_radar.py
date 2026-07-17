"""Barrier proximity analytics: model-implied touch and terminal probabilities.

The live desk's most-watched numbers: how close is spot to each note's knock-in or
autocall level, and what is the model-implied chance of getting there. Closed-form
under GBM (reflection principle for the running extremum), so the radar is cheap
enough to re-mark on every tick. Continuous monitoring — a conservative (higher)
touch probability versus the notes' discrete observation schedule.
"""

from __future__ import annotations

from math import erf, exp, log, sqrt


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def barrier_hit_probability(
    spot: float, barrier: float, tau: float, sigma: float, r: float, q: float
) -> float:
    """P(spot touches ``barrier`` before ``tau``) under GBM, either direction."""
    if spot <= 0.0 or barrier <= 0.0:
        return 0.0
    down = barrier < spot
    if barrier == spot:
        return 1.0
    if tau <= 0.0 or sigma <= 0.0:
        return 0.0  # no time or no noise left — an untouched barrier stays untouched
    nu = r - q - 0.5 * sigma * sigma
    v = sigma * sqrt(tau)
    m = log(barrier / spot)  # signed log-distance to the barrier
    if down:  # P(min ≤ m), m < 0
        return _ncdf((m - nu * tau) / v) + exp(2.0 * nu * m / (sigma * sigma)) * _ncdf(
            (m + nu * tau) / v
        )
    return _ncdf((-m + nu * tau) / v) + exp(2.0 * nu * m / (sigma * sigma)) * _ncdf(
        (-m - nu * tau) / v
    )


def terminal_above_probability(
    spot: float, level: float, t: float, sigma: float, r: float, q: float
) -> float:
    """P(S_t ≥ level) under GBM — the model-implied autocall chance at one observation."""
    if spot <= 0.0 or level <= 0.0:
        return 0.0
    if t <= 0.0 or sigma <= 0.0:
        return 1.0 if spot >= level else 0.0
    nu = r - q - 0.5 * sigma * sigma
    return _ncdf((log(spot / level) + nu * t) / (sigma * sqrt(t)))
