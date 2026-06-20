"""Adjoint algorithmic differentiation: all Greeks in one reverse pass (L5).

The point of AAD: one forward pass plus one reverse pass yields **all** input sensitivities
at a small constant multiple of a single price, *independent of the number of inputs* — which
is how a desk gets thousands of Greeks for thousands of trades overnight. We run the
Black-Scholes price through the hand-rolled tape in :mod:`spdt.greeks.aad.tape` to demonstrate
the mechanism on one product.
"""

from __future__ import annotations

from math import exp, sqrt

import numpy as np

from spdt.greeks.aad.tape import Var, backward, v_exp, v_log, v_norm_cdf, v_sqrt
from spdt.greeks.aad.vec import Node
from spdt.greeks.aad import vec
from spdt.pricing.mc.rng import standard_normals
from spdt.products.catalog import Autocallable
from spdt.pricing.models import BlackScholes


def bs_vanilla_aad(
    spot: float, strike: float, t: float, r: float, q: float, sigma: float, is_call: bool
) -> tuple[float, dict[str, float]]:
    """Black-Scholes price **and** all first-order Greeks from one reverse pass.

    Returns ``(price, {"delta", "vega", "rho", "epsilon", "dPrice_dT"})`` where ``delta`` is
    ∂P/∂S, ``vega`` ∂P/∂σ, ``rho`` ∂P/∂r and ``epsilon`` ∂P/∂q (dividend sensitivity).
    """
    s = Var(spot)
    k = Var(strike)
    tau = Var(t)
    rate = Var(r)
    div = Var(q)
    vol = Var(sigma)

    vol_sqrt_t = vol * v_sqrt(tau)
    d1 = (v_log(s / k) + (rate - div + vol * vol * 0.5) * tau) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    disc_s = s * v_exp(div * tau * -1.0)
    disc_k = k * v_exp(rate * tau * -1.0)
    if is_call:
        price = disc_s * v_norm_cdf(d1) - disc_k * v_norm_cdf(d2)
    else:
        price = disc_k * v_norm_cdf(d2 * -1.0) - disc_s * v_norm_cdf(d1 * -1.0)

    backward(price)
    return price.value, {
        "delta": s.grad,
        "vega": vol.grad,
        "rho": rate.grad,
        "epsilon": div.grad,
        "dPrice_dT": tau.grad,
    }


def _gbm_spot_nodes(
    model: BlackScholes, grid: np.ndarray, normals: np.ndarray
) -> tuple[Node, Node, list[Node]]:
    """Tape GBM spots on ``grid`` as Nodes of the inputs ``(s0, sigma)``.

    Returns ``(s0_node, sigma_node, [S_t Node per grid date after t=0])``. The exact GBM step
    is differentiated through, so a reverse pass over any payoff of these spots gives the
    pathwise sensitivities to spot and vol.
    """
    s0 = Node(model.spot)
    sigma = Node(model.sigma)
    r, q = model.r, model.q
    dt = np.diff(grid)
    cum: Node = Node(np.zeros(normals.shape[0]))
    spots: list[Node] = []
    for j in range(dt.size):
        incr = sigma * sigma * (-0.5 * dt[j]) + sigma * (sqrt(dt[j]) * normals[:, j]) + (r - q) * dt[j]
        cum = cum + incr
        spots.append(s0 * vec.v_exp(cum))
    return s0, sigma, spots


def call_aad_greeks(
    model: BlackScholes, strike: float, expiry: float, *, n_paths: int = 200_000, seed: int = 0
) -> dict[str, float]:
    """Pathwise ``delta``/``vega`` of a European call via reverse-mode AAD over the MC payoff.

    A smooth payoff where pathwise is unbiased, so AAD, the pathwise estimator and a CRN bump
    must all agree — the design doc's headline three-way cross-check, here on the MC graph.
    """
    z = standard_normals(n_paths, 1, seed=seed)
    s0n, sigman, s_t = _gbm_spot_nodes(model, np.array([0.0, expiry]), z)
    payoff = vec.v_maximum(s_t[-1] - strike, 0.0)
    price = vec.v_sum_mean(payoff) * exp(-model.r * expiry)
    vec.backward(price)
    return {"delta": float(s0n.grad), "vega": float(sigman.grad)}


def autocallable_aad_greeks(
    note: Autocallable, model: BlackScholes, *, n_paths: int = 200_000, seed: int = 0
) -> dict[str, float]:
    """Pathwise ``delta``/``vega`` of the **autocallable** via reverse-mode AAD over the MC graph.

    This is the design doc's W10 deliverable: the hand-rolled adjoint run on the flagship
    exotic, not a vanilla. The note must be *struck* (``initial_fixing`` set) so the barriers
    are fixed levels — otherwise the payoff is scale-invariant in spot and the delta is
    structurally zero. Coupon/autocall triggers are digital, so (like any pathwise estimator)
    AAD captures the continuous knock-in participation and is blind to the barrier Diracs.
    """
    if note.initial_fixing is None:
        raise ValueError("AAD delta needs a struck note (set initial_fixing)")
    k0 = float(note.initial_fixing)
    n = note.notional
    grid = np.array([0.0, *note.observation_times])
    z = standard_normals(n_paths, len(note.observation_times), seed=seed)
    s0n, sigman, spots = _gbm_spot_nodes(model, grid, z)

    pv: Node = Node(np.zeros(n_paths))
    alive: np.ndarray = np.ones(n_paths, dtype=bool)
    last = len(note.observation_times) - 1
    for i, t in enumerate(note.observation_times):
        spot = spots[i]
        sv = spot.value
        disc = exp(-model.r * t)
        pays = alive & (sv >= note.coupon_barrier * k0)
        pv = pv + Node(disc * pays.astype(float) * note.coupon_rate * n)  # fixed cash ⇒ const
        if i < last:
            called = alive & (sv >= note.autocall_level * k0)
            pv = pv + Node(disc * called.astype(float) * n)  # par redemption ⇒ const
            alive = alive & ~called
        else:
            ki = sv <= note.knock_in * k0
            # Knocked-in principal n·S_T/K0 is the only spot/vol-dependent term ⇒ the source of
            # delta and vega; the un-knocked par is a constant.
            ki_frac = (alive & ki).astype(float)
            par = (alive & ~ki).astype(float)
            principal = spot * (disc * ki_frac * (n / k0)) + Node(disc * par * n)
            pv = pv + principal
    price = vec.v_sum_mean(pv)
    vec.backward(price)
    return {"delta": float(s0n.grad), "vega": float(sigman.grad)}


__all__ = ["autocallable_aad_greeks", "bs_vanilla_aad", "call_aad_greeks"]
