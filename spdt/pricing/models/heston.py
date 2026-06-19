"""Heston stochastic-volatility model: CF vanilla pricer + QE simulation (L4).

    dS = (r−q)·S dt + √v·S dW₁,   dv = κ(θ − v) dt + ξ√v dW₂,   d⟨W₁,W₂⟩ = ρ dt

Two independent implementations that must agree:

* **Semi-analytic vanilla** via the Heston characteristic function (Albrecher's "little trap"
  form, numerically stable) and the two-integral Heston formula. This is exact up to the
  quadrature and is the benchmark.
* **Andersen QE simulation** (quadratic-exponential) for path-dependent payoffs. Euler on the
  variance is biased and can go negative; QE samples the (non-central-χ²) transition law via a
  moment-matched proxy, with the martingale-corrected log-spot update. The QE Monte-Carlo
  vanilla converging to the CF price is the headline cross-check.

The model draws its own randomness (the engine's normals only fix the path count) because QE
needs a uniform plus two normals per step, which the single-normal path interface can't carry.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, log

import numpy as np
from numpy.typing import NDArray
from scipy.integrate import quad


@dataclass(frozen=True)
class HestonModel:
    """Heston dynamics with parameters ``(v0, κ, θ, ξ, ρ)`` plus spot/rate/dividend."""

    spot: float
    r: float
    q: float
    v0: float
    kappa: float
    theta: float
    xi: float
    rho: float
    seed: int = 0

    def characteristic_function(self, u: complex, t: float) -> complex:
        """``E[exp(i·u·ln S_T)]`` — Albrecher "little trap" form (stable branch)."""
        i = 1j
        xi, kappa, theta, rho, v0 = self.xi, self.kappa, self.theta, self.rho, self.v0
        d = np.sqrt((rho * xi * i * u - kappa) ** 2 + xi * xi * (i * u + u * u))
        g = (kappa - rho * xi * i * u - d) / (kappa - rho * xi * i * u + d)
        edt = np.exp(-d * t)
        drift = i * u * (log(self.spot) + (self.r - self.q) * t)
        term_theta = (kappa * theta / (xi * xi)) * (
            (kappa - rho * xi * i * u - d) * t - 2.0 * np.log((1.0 - g * edt) / (1.0 - g))
        )
        term_v = (v0 / (xi * xi)) * (kappa - rho * xi * i * u - d) * (1.0 - edt) / (1.0 - g * edt)
        return np.exp(drift + term_theta + term_v)

    def vanilla(self, strike: float, t: float, is_call: bool = True) -> float:
        """European vanilla via the two-integral Heston formula (quadrature)."""
        forward = self.spot * exp((self.r - self.q) * t)
        ln_k = log(strike)

        def integrand(u: float, shift: complex, denom_scale: float) -> float:
            cf = self.characteristic_function(u - shift, t)
            return (np.exp(-1j * u * ln_k) * cf / (1j * u) / denom_scale).real

        p1 = 0.5 + (1.0 / np.pi) * quad(integrand, 0, 200, args=(1j, forward), limit=200)[0]
        p2 = 0.5 + (1.0 / np.pi) * quad(integrand, 0, 200, args=(0j, 1.0), limit=200)[0]
        call = self.spot * exp(-self.q * t) * p1 - strike * exp(-self.r * t) * p2
        if is_call:
            return call
        return call - self.spot * exp(-self.q * t) + strike * exp(-self.r * t)  # put-call parity

    def simulate(
        self, times: NDArray[np.float64], normals: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        """Andersen QE simulation of spot paths on ``times`` (own RNG; ``normals`` sets count)."""
        n_paths = normals.shape[0]
        rng = np.random.default_rng(self.seed)
        kappa, theta, xi, rho = self.kappa, self.theta, self.xi, self.rho
        psi_c = 1.5

        log_s = np.full(n_paths, log(self.spot))
        v = np.full(n_paths, self.v0)
        columns = [np.full(n_paths, self.spot)]

        for j in range(times.size - 1):
            dt = times[j + 1] - times[j]
            e = exp(-kappa * dt)
            m = theta + (v - theta) * e
            s2 = (
                v * xi * xi * e / kappa * (1.0 - e)
                + theta * xi * xi / (2.0 * kappa) * (1.0 - e) ** 2
            )
            psi = s2 / np.maximum(m * m, 1e-300)

            zv = rng.standard_normal(n_paths)
            u_unif = rng.random(n_paths)
            v_next = np.empty(n_paths)

            # Quadratic branch (ψ ≤ ψc): v' = a(b + Z)².
            quad_mask = psi <= psi_c
            inv_psi = 1.0 / np.where(quad_mask, psi, 1.0)
            root = np.sqrt(np.maximum(2.0 * inv_psi - 1.0, 0.0))
            b2 = 2.0 * inv_psi - 1.0 + np.sqrt(2.0 * inv_psi) * root
            a = m / (1.0 + b2)
            v_next = np.where(quad_mask, a * (np.sqrt(np.maximum(b2, 0.0)) + zv) ** 2, 0.0)

            # Exponential branch (ψ > ψc): mixture of a mass at 0 and an exponential tail.
            p = (psi - 1.0) / (psi + 1.0)
            beta = (1.0 - p) / np.maximum(m, 1e-300)
            tail = np.log(np.maximum((1.0 - p) / np.maximum(1.0 - u_unif, 1e-300), 1e-300)) / beta
            exp_val = np.where(u_unif <= p, 0.0, tail)
            v_next = np.where(quad_mask, v_next, exp_val)

            # Martingale-corrected log-spot update (Andersen, central γ1=γ2=½).
            k0 = -rho * kappa * theta * dt / xi
            k1 = 0.5 * dt * (kappa * rho / xi - 0.5) - rho / xi
            k2 = 0.5 * dt * (kappa * rho / xi - 0.5) + rho / xi
            k3 = 0.5 * dt * (1.0 - rho * rho)
            k4 = 0.5 * dt * (1.0 - rho * rho)
            zs = rng.standard_normal(n_paths)
            log_s = (
                log_s
                + (self.r - self.q) * dt
                + k0 + k1 * v + k2 * v_next
                + np.sqrt(np.maximum(k3 * v + k4 * v_next, 0.0)) * zs
            )
            v = v_next
            columns.append(np.exp(log_s))

        return np.column_stack(columns)

    def discount(self, t: float) -> float:
        return exp(-self.r * t)
