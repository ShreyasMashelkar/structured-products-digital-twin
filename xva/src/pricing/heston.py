"""
Heston stochastic-volatility model.

The Heston (1993) model makes variance itself a mean-reverting stochastic
process correlated with the spot, so the implied-vol smile arises from the
*dynamics* rather than being frozen. This is what distinguishes a deep equity
model from a GBM-with-static-smile approximation: the smile evolves, forward
smiles are non-trivial, and exposure picks up genuine vol-of-vol tail risk.

Dynamics (risk-neutral):
    dS = (r - q) S dt + √v · S dW_S
    dv = κ(θ - v) dt + ξ √v dW_v
    corr(dW_S, dW_v) = ρ

This module provides:
  - semi-analytic European pricing via the characteristic function
    (the numerically stable "Little Heston Trap" form, Albrecher et al. 2007),
  - calibration of (v0, κ, θ, ξ, ρ) to an implied-vol smile,
  - an Andersen (2008) Quadratic-Exponential (QE) Monte Carlo scheme that
    keeps variance non-negative and is the production standard.

Pure NumPy / SciPy. References: Heston (1993); Albrecher et al. (2007),
"The little Heston trap"; Andersen (2008), "Efficient simulation of the
Heston stochastic volatility model".
"""

import numpy as np
from scipy.integrate import quad
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from src.pricing.equity_options import bsm_price, implied_vol


@dataclass
class HestonParams:
    v0: float       # initial variance
    kappa: float    # mean-reversion speed
    theta: float    # long-run variance
    xi: float       # vol-of-vol
    rho: float      # spot/vol correlation

    def feller(self) -> bool:
        """Feller condition 2κθ ≥ ξ² (variance stays strictly positive)."""
        return 2 * self.kappa * self.theta >= self.xi ** 2


# ── characteristic function (Little Heston Trap form) ───────────────────────
def _cf_logspot(u: complex, S0: float, r: float, q: float, T: float,
                p: HestonParams) -> complex:
    """Characteristic function of x_T = ln S_T under the risk-neutral measure."""
    kappa, theta, xi, rho, v0 = p.kappa, p.theta, p.xi, p.rho, p.v0
    iu = 1j * u
    a = kappa - rho * xi * iu
    d = np.sqrt(a ** 2 + (xi ** 2) * (iu + u ** 2))
    # "little trap" g (numerically stable branch)
    g = (a - d) / (a + d)
    edt = np.exp(-d * T)
    C = (kappa * theta / xi ** 2) * ((a - d) * T - 2.0 * np.log((1 - g * edt) / (1 - g)))
    D = ((a - d) / xi ** 2) * ((1 - edt) / (1 - g * edt))
    return np.exp(iu * (np.log(S0) + (r - q) * T) + C + D * v0)


def heston_price(S0: float, K: float, T: float, r: float, q: float,
                 p: HestonParams, call: bool = True,
                 u_max: float = 200.0) -> float:
    """
    Semi-analytic European option price under Heston.

    Uses C = S0 e^{-qT} P1 - K e^{-rT} P2 with both risk-neutral probabilities
    obtained from the single log-spot characteristic function.
    """
    if T <= 0:
        intrinsic = max(S0 - K, 0.0) if call else max(K - S0, 0.0)
        return intrinsic
    lnK = np.log(K)
    cf0 = _cf_logspot(-1j, S0, r, q, T, p)   # = E[S_T] e^{...} normaliser for P1

    def integrand_P2(u):
        val = np.exp(-1j * u * lnK) * _cf_logspot(u, S0, r, q, T, p) / (1j * u)
        return val.real

    def integrand_P1(u):
        val = (np.exp(-1j * u * lnK) * _cf_logspot(u - 1j, S0, r, q, T, p)
               / (1j * u * cf0))
        return val.real

    P2 = 0.5 + (1.0 / np.pi) * quad(integrand_P2, 1e-8, u_max, limit=200)[0]
    P1 = 0.5 + (1.0 / np.pi) * quad(integrand_P1, 1e-8, u_max, limit=200)[0]

    call_px = S0 * np.exp(-q * T) * P1 - K * np.exp(-r * T) * P2
    if call:
        return max(call_px, 0.0)
    # put-call parity
    return max(call_px - S0 * np.exp(-q * T) + K * np.exp(-r * T), 0.0)


def heston_implied_vol(S0: float, K: float, T: float, r: float, q: float,
                       p: HestonParams, call: bool = True) -> float:
    """Black-Scholes implied vol of the Heston price (model smile)."""
    px = heston_price(S0, K, T, r, q, p, call)
    return implied_vol(px, S0, K, T, r, q, call)


def calibrate_heston(chain_df, S0: float, T: float, r: float, q: float,
                     init: Optional[HestonParams] = None) -> Tuple[HestonParams, float]:
    """
    Calibrate (v0, κ, θ, ξ, ρ) to an implied-vol smile (least squares on vols).

    Args:
        chain_df: DataFrame with 'strike' and 'implied_vol' columns.
        S0,T,r,q: spot, expiry, rate, dividend yield.
        init:     optional starting params.

    Returns:
        (HestonParams, rmse_in_vol_points).
    """
    from scipy.optimize import least_squares
    strikes = chain_df['strike'].values
    mkt_vol = chain_df['implied_vol'].values
    atm_var = float(mkt_vol[np.argmin(np.abs(strikes - S0))] ** 2)

    if init is None:
        init = HestonParams(v0=atm_var, kappa=1.5, theta=atm_var, xi=0.5, rho=-0.6)
    x0 = [init.v0, init.kappa, init.theta, init.xi, init.rho]
    # bounds: variances>0, kappa>0, xi>0, rho in (-0.99,0.99)
    lb = [1e-4, 0.1, 1e-4, 0.05, -0.99]
    ub = [1.0, 10.0, 1.0, 3.0, 0.99]

    def resid(x):
        pp = HestonParams(*x)
        model_vol = np.array([heston_implied_vol(S0, K, T, r, q, pp, True)
                              for K in strikes])
        return model_vol - mkt_vol

    sol = least_squares(resid, x0, bounds=(lb, ub), max_nfev=200, xtol=1e-8)
    p = HestonParams(*sol.x)
    rmse = float(np.sqrt(np.mean(sol.fun ** 2)))
    return p, rmse


# ── Andersen QE Monte Carlo ─────────────────────────────────────────────────
def simulate_heston_qe(S0: float, r: float, q: float, time_grid: np.ndarray,
                       p: HestonParams, n_paths: int, seed: int = 42,
                       psi_c: float = 1.5) -> Dict[str, np.ndarray]:
    """
    Andersen (2008) Quadratic-Exponential simulation of (S, v).

    The QE scheme keeps variance non-negative and is accurate even when the
    Feller condition is violated — the production-standard Heston simulator.

    Returns dict: time_grid, spot, variance.
    """
    rng = np.random.default_rng(seed)
    n_steps = len(time_grid) - 1
    kappa, theta, xi, rho = p.kappa, p.theta, p.xi, p.rho

    v = np.empty((n_paths, n_steps + 1)); v[:, 0] = p.v0
    lnS = np.empty((n_paths, n_steps + 1)); lnS[:, 0] = np.log(S0)

    # constants for the log-spot update (Andersen "central discretization")
    k0_c = lambda dt: -rho * kappa * theta * dt / xi
    k1_c = lambda dt: 0.5 * dt * (kappa * rho / xi - 0.5) - rho / xi
    k2_c = lambda dt: 0.5 * dt * (kappa * rho / xi - 0.5) + rho / xi
    k3_c = lambda dt: 0.5 * dt * (1 - rho ** 2)

    for i in range(n_steps):
        dt = time_grid[i + 1] - time_grid[i]
        vt = v[:, i]
        e = np.exp(-kappa * dt)
        m = theta + (vt - theta) * e
        s2 = (vt * xi ** 2 * e / kappa) * (1 - e) + (theta * xi ** 2 / (2 * kappa)) * (1 - e) ** 2
        psi = s2 / np.maximum(m ** 2, 1e-300)

        v_next = np.empty(n_paths)
        # QE: quadratic branch (psi <= psi_c)
        quad_mask = psi <= psi_c
        if quad_mask.any():
            inv_psi = 1.0 / psi[quad_mask]
            b2 = 2 * inv_psi - 1 + np.sqrt(2 * inv_psi) * np.sqrt(np.maximum(2 * inv_psi - 1, 0.0))
            a = m[quad_mask] / (1 + b2)
            Zv = rng.standard_normal(quad_mask.sum())
            v_next[quad_mask] = a * (np.sqrt(np.maximum(b2, 0.0)) + Zv) ** 2
        # exponential branch (psi > psi_c)
        exp_mask = ~quad_mask
        if exp_mask.any():
            pp = (psi[exp_mask] - 1) / (psi[exp_mask] + 1)
            beta = (1 - pp) / np.maximum(m[exp_mask], 1e-300)
            U = rng.random(exp_mask.sum())
            vv = np.where(U <= pp, 0.0,
                          np.log(np.maximum((1 - pp) / np.maximum(1 - U, 1e-300), 1e-300)) / beta)
            v_next[exp_mask] = vv
        v[:, i + 1] = v_next

        # log-spot update with the same dt constants
        fwd = (r - q) * dt
        Zs = rng.standard_normal(n_paths)
        lnS[:, i + 1] = (lnS[:, i] + fwd + k0_c(dt)
                         + k1_c(dt) * vt + k2_c(dt) * v_next
                         + np.sqrt(np.maximum(k3_c(dt) * (vt + v_next), 0.0)) * Zs)

    return {'time_grid': time_grid, 'spot': np.exp(lnS), 'variance': v}
