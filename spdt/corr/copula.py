"""Copula samplers for correlated multi-asset shocks (corr framework).

The Gaussian copula correlates increments via the Cholesky factor of the correlation matrix.
The **t-copula** adds tail dependence through one extra chi-square mixing variable — important
for worst-of products because equities crash *together*, which the Gaussian copula understates
(its tail dependence is zero). Inputs are assumed already PSD (repair with
:func:`spdt.corr.psd.nearest_correlation` first).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def gaussian_correlated_normals(
    corr: NDArray, n_paths: int, n_steps: int, rng: np.random.Generator
) -> NDArray[np.float64]:
    """Standard normals correlated across assets: shape ``(n_paths, n_steps, n_assets)``."""
    chol = np.linalg.cholesky(np.asarray(corr, dtype=float))
    z = rng.standard_normal((n_paths, n_steps, chol.shape[0]))
    return z @ chol.T


def t_correlated_normals(
    corr: NDArray, n_paths: int, n_steps: int, dof: float, rng: np.random.Generator
) -> NDArray[np.float64]:
    """t-copula draws (standardised to unit variance) with tail dependence via ``dof``."""
    gaussian = gaussian_correlated_normals(corr, n_paths, n_steps, rng)
    chi2 = rng.chisquare(dof, size=(n_paths, n_steps, 1))
    t = gaussian * np.sqrt(dof / chi2)
    return t * np.sqrt((dof - 2.0) / dof) if dof > 2.0 else t  # rescale to unit variance
