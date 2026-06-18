"""Closed-form Black-Scholes vanilla prices — the Monte-Carlo benchmarks (L4).

Spot-based ``(S, K, T, r, q, σ)`` convention (as opposed to the forward-based Black-76 used
for IV inversion in L1): the pricing engine works from spot and a flat ``r/q`` so MC and
closed form share identical inputs, which is what makes the convergence test meaningful.
"""

from __future__ import annotations

from math import erf, exp, log, sqrt


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _d1_d2(spot: float, strike: float, t: float, r: float, q: float, sigma: float):
    vol = sigma * sqrt(t)
    d1 = (log(spot / strike) + (r - q + 0.5 * sigma * sigma) * t) / vol
    return d1, d1 - vol


def bs_vanilla(
    spot: float, strike: float, t: float, r: float, q: float, sigma: float, is_call: bool
) -> float:
    """European vanilla price under Black-Scholes."""
    if t <= 0.0 or sigma <= 0.0:
        intrinsic = max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)
        return exp(-r * t) * intrinsic
    d1, d2 = _d1_d2(spot, strike, t, r, q, sigma)
    disc_s = spot * exp(-q * t)
    disc_k = strike * exp(-r * t)
    if is_call:
        return disc_s * _norm_cdf(d1) - disc_k * _norm_cdf(d2)
    return disc_k * _norm_cdf(-d2) - disc_s * _norm_cdf(-d1)
