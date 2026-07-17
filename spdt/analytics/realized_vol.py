"""Realized volatility from live tick samples, annualized on a trading clock.

Quadratic-variation estimator: rv² = Σ (log S_i/S_{i-1})² over the sampled window,
annualized by elapsed *trading* seconds (252 × 6.25h days). Vol accrues in trading
time, so this is the honest comparator against an implied-vol quote; wall-clock
annualization would understate intraday realized vol by the closed-hours ratio.
"""

from __future__ import annotations

from math import log, sqrt
from typing import Sequence

TRADING_SECONDS_PER_YEAR = 252 * 6.25 * 3600.0

_MIN_SAMPLES = 8  # below this the estimate is noise, return None instead


def realized_vol(samples: Sequence[tuple[float, float]]) -> float | None:
    """Annualized realized vol from time-ordered ``(epoch_seconds, spot)`` samples."""
    if len(samples) < _MIN_SAMPLES:
        return None
    quadratic_variation = 0.0
    elapsed_s = 0.0
    for (t0, s0), (t1, s1) in zip(samples, samples[1:]):
        if t1 <= t0 or s0 <= 0.0 or s1 <= 0.0:
            continue  # clock skew or bad print — skip the increment, keep the rest
        r = log(s1 / s0)
        quadratic_variation += r * r
        elapsed_s += t1 - t0
    if elapsed_s <= 0.0 or quadratic_variation <= 0.0:
        return None
    return sqrt(quadratic_variation / (elapsed_s / TRADING_SECONDS_PER_YEAR))
