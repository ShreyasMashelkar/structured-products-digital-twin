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
from typing import TYPE_CHECKING

import numpy as np

from spdt.pricing.mc.rng import standard_normals
from spdt.pricing.models import BlackScholes

if TYPE_CHECKING:
    from spdt.products.catalog import Autocallable


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


def lr_autocallable_delta(
    note: "Autocallable",
    model: BlackScholes,
    *,
    n_paths: int = 200_000,
    seed: int = 0,
) -> float:
    """Likelihood-ratio delta of the **autocallable** — the estimator that sees the barriers.

    The adjoint (:func:`spdt.greeks.aad.autocallable_aad_greeks`) differentiates the payoff, and
    the autocallable's payoff is a step function of the observation-date spots: coupon barrier,
    autocall trigger and knock-in are all indicators. Differentiating an indicator gives zero
    almost everywhere, so AAD reports only the smooth part — the knock-in participation — and is
    structurally blind to the jumps. That is the whole of the 60–73% gap measured against a
    finite-difference bump in the validation pack; it is not a bug in either method.

    This estimator differentiates the **density** instead::

        ∂Price/∂S₀ = E[ Payoff · ∂log p/∂S₀ ]

    leaving the payoff untouched, so discontinuities cost nothing. Under GBM the whole path is
    driven by the first Brownian increment's dependence on ``S₀``, and the score with respect to
    ``S₀`` at the *first* monitoring time is ``Z₁ / (S₀ σ √t₁)``; later increments are
    independent of ``S₀``, so the single score term is the complete derivative.

    The cost is variance. The score divides by ``σ√t₁``, so for a short first observation or a
    low vol the estimator is noisy — often far noisier than a bump. It is therefore a *check*
    on the bump rather than a replacement: agreement between LR and bump, where AAD cannot
    reach, is what turns two disagreeing numbers into a validated one.
    """
    if note.initial_fixing is None:
        raise ValueError("LR delta needs a struck note (set initial_fixing)")

    s0, r, q, sigma = model.spot, model.r, model.q, model.sigma
    obs = np.asarray(note.observation_times, dtype=float)
    grid = np.concatenate([[0.0], obs])
    z = standard_normals(n_paths, obs.size, seed=seed)

    # GBM spots on the observation grid, keeping the first increment's normal for the score.
    dt = np.diff(grid)
    increments = (r - q - 0.5 * sigma * sigma) * dt + sigma * np.sqrt(dt) * z
    spots = s0 * np.exp(np.cumsum(increments, axis=1))  # (n_paths, n_obs)

    payoff = _autocallable_discounted_payoff(note, spots, obs, r)
    score = z[:, 0] / (s0 * sigma * sqrt(float(obs[0])))  # ∂log p/∂S₀ via the first increment
    return float(np.mean(payoff * score))


def _autocallable_discounted_payoff(
    note: "Autocallable", spots: np.ndarray, obs: np.ndarray, r: float
) -> np.ndarray:
    """Per-path discounted cashflow total of a struck autocallable on observation-date spots."""
    k0 = float(note.initial_fixing)
    n = note.notional
    n_paths = spots.shape[0]
    alive = np.ones(n_paths, dtype=bool)
    missed = np.zeros(n_paths)
    total = np.zeros(n_paths)
    last = obs.size - 1

    for i, t in enumerate(obs):
        s = spots[:, i]
        disc = exp(-r * float(t))
        pays = alive & (s >= note.coupon_barrier * k0)
        if note.memory:
            coupon = np.where(pays, (missed + 1.0) * note.coupon_rate * n, 0.0)
            missed = np.where(pays, 0.0, np.where(alive, missed + 1.0, missed))
        else:
            coupon = np.where(pays, note.coupon_rate * n, 0.0)
        total += disc * coupon

        if i < last:
            called = alive & (s >= note.autocall_level * k0)
            total += disc * np.where(called, float(n), 0.0)
            alive = alive & ~called
        else:
            breached = s <= note.knock_in * k0
            redemption = np.where(breached, n * s / k0, float(n))
            total += disc * np.where(alive, redemption, 0.0)
    return total
