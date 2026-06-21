"""
Quasi-Monte Carlo (Sobol) path generation + Brownian bridge.

Low-discrepancy Sobol sequences fill the unit hypercube far more uniformly
than pseudo-random draws, so Monte Carlo estimators converge at close to
O(1/N) instead of O(1/√N). Combined with a Brownian-bridge path construction
(which loads the most important variance onto the first Sobol dimensions),
this is the standard variance-reduction stack on production XVA engines.

Everything here uses only scipy.stats.qmc.Sobol (free, no GPU).

References:
    - Glasserman (2004), Monte Carlo Methods in Financial Engineering, Ch. 5
    - Joe & Kuo (2008) Sobol direction numbers (used by scipy)
"""

import numpy as np
from scipy.stats import qmc, norm
from typing import Dict


def sobol_normals(n_paths: int, n_dim: int, seed: int = 42,
                  scramble: bool = True) -> np.ndarray:
    """
    Generate standard-normal draws from a scrambled Sobol sequence.

    Args:
        n_paths: Number of paths (rounded up internally to a power of two
                 for balance, then truncated to n_paths).
        n_dim:   Number of dimensions (e.g. time steps).
        seed:    Scramble seed.
        scramble: Owen scrambling (recommended — gives valid error estimates).

    Returns:
        (n_paths, n_dim) array of N(0,1) draws.
    """
    sampler = qmc.Sobol(d=n_dim, scramble=scramble, seed=seed)
    m = int(np.ceil(np.log2(max(n_paths, 2))))
    u = sampler.random_base2(m=m)          # 2^m points, well-balanced
    u = u[:n_paths]
    # clip away exact 0/1 before the inverse-CDF
    u = np.clip(u, 1e-10, 1 - 1e-10)
    return norm.ppf(u)


def mc_normals(n_paths: int, n_dim: int, seed: int = 42) -> np.ndarray:
    """Pseudo-random N(0,1) baseline of the same shape, for comparison."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal((n_paths, n_dim))


def brownian_bridge(normals: np.ndarray, time_grid: np.ndarray) -> np.ndarray:
    """
    Construct Brownian-motion paths from independent normals via the
    Brownian bridge, so that early Sobol dimensions control the coarse
    (high-variance) shape of the path.

    Args:
        normals:   (n_paths, n_steps) standard normals (one per increment/dim).
        time_grid: (n_steps+1,) times starting at 0.

    Returns:
        (n_paths, n_steps+1) Brownian paths W with W[:,0] = 0.
    """
    n_paths, n_steps = normals.shape
    t = time_grid
    W = np.zeros((n_paths, n_steps + 1))

    # Terminal point first (dimension 0 carries the most variance)
    T = t[-1]
    W[:, -1] = np.sqrt(T) * normals[:, 0]

    # Recursive bridge fill
    def fill(lo: int, hi: int, dim: int):
        if hi - lo <= 1:
            return dim
        mid = (lo + hi) // 2
        t_lo, t_mid, t_hi = t[lo], t[mid], t[hi]
        mean = (W[:, lo] * (t_hi - t_mid) + W[:, hi] * (t_mid - t_lo)) / (t_hi - t_lo)
        std = np.sqrt((t_mid - t_lo) * (t_hi - t_mid) / (t_hi - t_lo))
        W[:, mid] = mean + std * normals[:, dim]
        dim += 1
        dim = fill(lo, mid, dim)
        dim = fill(mid, hi, dim)
        return dim

    fill(0, n_steps, 1)
    return W


def bachelier_swaption_price(forward: float, strike: float, vol: float,
                             expiry: float, annuity: float, notional: float,
                             payer: bool = True) -> float:
    """Closed-form Bachelier (normal) swaption price — the ground truth."""
    s = vol * np.sqrt(expiry)
    d = (forward - strike) / s
    if payer:
        px = (forward - strike) * norm.cdf(d) + s * norm.pdf(d)
    else:
        px = (strike - forward) * norm.cdf(-d) + s * norm.pdf(d)
    return notional * annuity * px


def convergence_demo(forward: float = 0.07, strike: float = 0.07,
                     vol: float = 0.0055, expiry: float = 2.0,
                     annuity: float = 4.0, notional: float = 500.0,
                     path_counts=(256, 512, 1024, 2048, 4096, 8192),
                     seed: int = 42) -> Dict:
    """
    Compare QMC (Sobol) vs pseudo-random MC convergence on an ATM Bachelier
    swaption, against the exact analytic price.

    The single-step payoff is max(F + vol·√T·Z - K, 0); we estimate its
    expectation and compare the absolute pricing error of MC vs QMC at each
    path count. QMC error should fall substantially faster.

    Returns dict with the analytic price and per-N errors for both methods.
    """
    analytic = bachelier_swaption_price(forward, strike, vol, expiry,
                                        annuity, notional, payer=True)
    s = vol * np.sqrt(expiry)

    rows = []
    for n in path_counts:
        # QMC (1-D Sobol)
        z_q = sobol_normals(n, 1, seed=seed).ravel()
        payoff_q = np.maximum(forward + s * z_q - strike, 0.0)
        price_q = notional * annuity * payoff_q.mean()

        # MC
        z_m = mc_normals(n, 1, seed=seed).ravel()
        payoff_m = np.maximum(forward + s * z_m - strike, 0.0)
        price_m = notional * annuity * payoff_m.mean()

        rows.append({
            'n_paths': n,
            'mc_price': price_m,
            'qmc_price': price_q,
            'mc_abs_err': abs(price_m - analytic),
            'qmc_abs_err': abs(price_q - analytic),
        })

    return {'analytic': analytic, 'rows': rows}
