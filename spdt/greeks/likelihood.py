"""Likelihood-ratio (score) Greeks (L5).

Differentiate the *density* instead of the payoff:
``∂Price/∂θ = E[Payoff · ∂log p/∂θ]``. Because the payoff is left untouched, this works for
**discontinuous payoffs** (digitals, barriers) where the pathwise method fails — at the cost
of higher variance (the score weight blows up the estimator's variance, especially for short
maturities and small vols).

For GBM, ``log S_T`` is normal with mean ``log S₀ + (r−q−½σ²)T`` and variance ``σ²T``; the
score with respect to ``S₀`` is ``Z / (S₀·σ·√T)``, giving the delta estimator below.
"""

from __future__ import annotations

from math import exp, sqrt

import numpy as np

from spdt.pricing.mc.rng import standard_normals
from spdt.pricing.models import BlackScholes


def lr_digital_delta(
    model: BlackScholes,
    strike: float,
    expiry: float,
    is_call: bool = True,
    payout: float = 1.0,
    *,
    n_paths: int = 200_000,
    seed: int = 0,
) -> float:
    """Likelihood-ratio delta of a cash-or-nothing digital — where pathwise gives nothing."""
    s0, r, q, sigma = model.spot, model.r, model.q, model.sigma
    sqrt_t = sqrt(expiry)
    z = standard_normals(n_paths, 1, seed=seed)[:, 0]
    s_t = s0 * np.exp((r - q - 0.5 * sigma * sigma) * expiry + sigma * sqrt_t * z)
    disc = exp(-r * expiry)

    hit = (s_t > strike) if is_call else (s_t < strike)
    payoff = payout * hit.astype(float)
    score = z / (s0 * sigma * sqrt_t)  # ∂log p / ∂S₀
    return disc * float(np.mean(payoff * score))
