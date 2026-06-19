"""Local-stochastic-volatility model with particle leverage calibration (L4).

    dS = (r−q)·S dt + L(S,t)·√v·S dW₁,   dv = κ(θ−v) dt + ξ√v dW₂,   d⟨W₁,W₂⟩ = ρ dt

LSV is the production standard: a Heston-like stochastic variance ``v`` multiplied by a
**leverage function** ``L(S,t)`` chosen so the model reprices the *entire* vanilla surface.
The Markovian-projection / particle identity is::

    L²(S,t) = σ_Dupire²(S,t) / E[v_t | S_t = S]

so the effective local variance ``L²·E[v|S]`` equals the Dupire local variance by construction.
We calibrate the conditional expectation **on the fly** (McKean particle method): at each step
the simulated cloud is binned by spot, ``E[v|S]`` is the per-bin mean, and the leverage is read
off immediately — no separate calibration pass. The variance is advanced with the Andersen QE
scheme; the spot is a correlated log-Euler step.

Because it matches local vol but adds genuine vol-of-vol dynamics, LSV agrees with the pure
local-vol model on vanillas yet **disagrees on forward-smile-sensitive exotics** (autocallables)
— that gap is exactly the LSV − LV model reserve (L11).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, log

import numpy as np
from numpy.typing import NDArray

from spdt.pricing.models.localvol import LocalVolFn


def _conditional_mean_v(spots: NDArray, v: NDArray, n_bins: int) -> NDArray:
    """E[v | S] estimated by binning the particle cloud on spot quantiles."""
    edges = np.quantile(spots, np.linspace(0.0, 1.0, n_bins + 1))
    idx = np.clip(np.digitize(spots, edges[1:-1]), 0, n_bins - 1)
    totals = np.bincount(idx, weights=v, minlength=n_bins)
    counts = np.bincount(idx, minlength=n_bins)
    means = np.where(counts > 0, totals / np.maximum(counts, 1), v.mean())
    return means[idx]


@dataclass(frozen=True)
class LSVModel:
    """Local-stochastic-vol dynamics with on-the-fly particle leverage."""

    spot: float
    r: float
    q: float
    v0: float
    kappa: float
    theta: float
    xi: float
    rho: float
    local_vol: LocalVolFn  # σ_Dupire(S, t) from the calibrated surface
    seed: int = 0
    n_bins: int = 50
    leverage_floor: float = 0.1
    leverage_cap: float = 10.0

    def simulate(
        self, times: NDArray[np.float64], normals: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        """Simulate spot paths, calibrating the leverage against the cloud at each step."""
        n = normals.shape[0]
        rng = np.random.default_rng(self.seed)
        kappa, theta, xi, rho = self.kappa, self.theta, self.xi, self.rho
        psi_c = 1.5

        log_s = np.full(n, log(self.spot))
        v = np.full(n, self.v0)
        columns = [np.full(n, self.spot)]

        for j in range(times.size - 1):
            t = float(times[j])
            dt = times[j + 1] - t
            spots = np.exp(log_s)

            # Leverage: L(S,t) = σ_LV(S,t) / sqrt(E[v|S]); effective local vol matches Dupire.
            cond_v = np.maximum(_conditional_mean_v(spots, v, self.n_bins), 1e-8)
            sigma_lv = np.asarray(self.local_vol(spots, t), dtype=float)
            leverage = np.clip(
                sigma_lv / np.sqrt(cond_v), self.leverage_floor, self.leverage_cap
            )

            # Variance: Andersen QE step.
            e = exp(-kappa * dt)
            m = theta + (v - theta) * e
            s2 = (
                v * xi * xi * e / kappa * (1.0 - e)
                + theta * xi * xi / (2.0 * kappa) * (1.0 - e) ** 2
            )
            psi = s2 / np.maximum(m * m, 1e-300)
            zv = rng.standard_normal(n)
            u = rng.random(n)

            quad_mask = psi <= psi_c
            inv_psi = 1.0 / np.where(quad_mask, psi, 1.0)
            root = np.sqrt(np.maximum(2.0 * inv_psi - 1.0, 0.0))
            b2 = 2.0 * inv_psi - 1.0 + np.sqrt(2.0 * inv_psi) * root
            a = m / (1.0 + b2)
            v_quad = a * (np.sqrt(np.maximum(b2, 0.0)) + zv) ** 2

            p = (psi - 1.0) / (psi + 1.0)
            beta = (1.0 - p) / np.maximum(m, 1e-300)
            tail = np.log(np.maximum((1.0 - p) / np.maximum(1.0 - u, 1e-300), 1e-300)) / beta
            v_next = np.where(quad_mask, v_quad, np.where(u <= p, 0.0, tail))

            # Spot: correlated log-Euler with the leverage-scaled instantaneous vol.
            z_perp = rng.standard_normal(n)
            dw1 = rho * zv + np.sqrt(1.0 - rho * rho) * z_perp
            sig_eff = leverage * np.sqrt(np.maximum(v, 0.0))
            log_s = (
                log_s
                + (self.r - self.q - 0.5 * sig_eff * sig_eff) * dt
                + sig_eff * np.sqrt(dt) * dw1
            )
            v = v_next
            columns.append(np.exp(log_s))

        return np.column_stack(columns)

    def discount(self, t: float) -> float:
        return exp(-self.r * t)
