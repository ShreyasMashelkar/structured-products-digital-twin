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
