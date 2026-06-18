"""Pathwise derivative Greeks (L5).

Differentiate the *payoff along the path*: ``∂Price/∂θ = E[∂Payoff/∂S · ∂S/∂θ]``. Unbiased
and low-variance **for Lipschitz payoffs** (vanillas), and notably cheaper-variance than
bump. It **fails for discontinuous payoffs** (digitals, barriers): the payoff's derivative is
zero almost everywhere and undefined at the jump, so the estimator misses the sensitivity
entirely — which is exactly why the likelihood-ratio method exists (see
:mod:`spdt.greeks.likelihood`).

Implemented here for the European vanilla under GBM, where the path is the single terminal
spot ``S_T = S₀·exp((r−q−½σ²)T + σ√T·Z)``.
"""

from __future__ import annotations

from math import exp, sqrt

import numpy as np

from spdt.pricing.mc.rng import standard_normals
from spdt.pricing.models import BlackScholes


def pathwise_vanilla(
    model: BlackScholes,
    strike: float,
    expiry: float,
    is_call: bool = True,
    *,
    n_paths: int = 200_000,
    seed: int = 0,
) -> dict[str, float]:
    """Pathwise ``delta`` and ``vega`` for a European vanilla under Black-Scholes."""
    s0, r, q, sigma = model.spot, model.r, model.q, model.sigma
    sqrt_t = sqrt(expiry)
    z = standard_normals(n_paths, 1, seed=seed)[:, 0]
    s_t = s0 * np.exp((r - q - 0.5 * sigma * sigma) * expiry + sigma * sqrt_t * z)
    disc = exp(-r * expiry)

    # ∂Payoff/∂S_T: +1 in-the-money for a call, −1 for a put, 0 otherwise.
    in_money = (s_t > strike) if is_call else (s_t < strike)
    payoff_deriv = np.where(in_money, 1.0 if is_call else -1.0, 0.0)

    delta = disc * float(np.mean(payoff_deriv * (s_t / s0)))  # ∂S_T/∂S₀ = S_T/S₀
    vega = disc * float(np.mean(payoff_deriv * (s_t * (sqrt_t * z - sigma * expiry))))
    return {"delta": delta, "vega": vega}
