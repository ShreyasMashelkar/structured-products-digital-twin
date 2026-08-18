"""Correlated multi-asset path generation for basket products (L4).

Exact GBM per asset (constant params ⇒ exact lognormal steps) with Cholesky-correlated
Brownian increments driven by the PSD-repaired correlation matrix. Used to price worst-of /
basket autocallables, where the payoff depends on the joint behaviour of several names.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from spdt.corr.copula import gaussian_correlated_normals


def correlated_gbm_paths(
    spots0: NDArray,
    vols: NDArray,
    corr: NDArray,
    times: NDArray,
    *,
    r: float,
    q: float = 0.0,
    n_paths: int,
    rng: np.random.Generator,
) -> NDArray[np.float64]:
    """Simulate ``(n_paths, n_times, n_assets)`` correlated GBM spots on ``times``."""
    spots0 = np.asarray(spots0, dtype=float)
    vols = np.asarray(vols, dtype=float)
    dt = np.diff(times)
    z = gaussian_correlated_normals(corr, n_paths, dt.size, rng)  # (paths, steps, assets)

    log_s = np.broadcast_to(np.log(spots0), (n_paths, spots0.size)).copy()
    out = np.empty((n_paths, times.size, spots0.size))
    out[:, 0, :] = spots0
    for i in range(dt.size):
        drift = (r - q - 0.5 * vols * vols) * dt[i]
        log_s = log_s + drift + vols * np.sqrt(dt[i]) * z[:, i, :]
        out[:, i + 1, :] = np.exp(log_s)
    return out


def correlated_local_vol_paths(
    spots0: NDArray,
    local_vols: list,
    corr: NDArray,
    times: NDArray,
    *,
    r: float,
    q: float = 0.0,
    n_paths: int,
    rng: np.random.Generator,
) -> NDArray[np.float64]:
    """Simulate ``(n_paths, n_times, n_assets)`` correlated **local-vol** spots on ``times``.

    Each asset carries its own ``σ_LV(S, t)`` (one :data:`~spdt.pricing.models.localvol.LocalVolFn`
    per name, in the order of ``spots0``); the Brownian increments are correlated across assets
    exactly as in :func:`correlated_gbm_paths`.

    This exists because the constant-vol version cannot price a worst-of honestly. A worst-of's
    knock-in sits 30–50% below spot, deep in the put wing, and that is precisely where a single
    ATM number is furthest from the market: on a liquid single name the 1-year vol at
    ``k = log(0.5)`` runs several points above ATM. Pricing the barrier at the ATM level
    understates how often it breaks.

    Unlike GBM there is no exact transition here, so ``times`` must be a *fine* grid — the
    log-Euler step is a real discretisation error, not a formality. Pass the observation dates
    alone and the vol will be held constant across each quarter.
    """
    spots0 = np.asarray(spots0, dtype=float)
    n_assets = spots0.size
    if len(local_vols) != n_assets:
        raise ValueError(f"need one local-vol function per asset; got {len(local_vols)} for {n_assets}")
    dt = np.diff(times)
    z = gaussian_correlated_normals(corr, n_paths, dt.size, rng)  # (paths, steps, assets)

    spots = np.broadcast_to(spots0, (n_paths, n_assets)).copy()
    out = np.empty((n_paths, times.size, n_assets))
    out[:, 0, :] = spots
    for i in range(dt.size):
        t = float(times[i])
        sig = np.column_stack(
            [np.asarray(local_vols[a](spots[:, a], t), dtype=float) for a in range(n_assets)]
        )
        drift = (r - q - 0.5 * sig * sig) * dt[i]
        spots = spots * np.exp(drift + sig * np.sqrt(dt[i]) * z[:, i, :])
        out[:, i + 1, :] = spots
    return out
