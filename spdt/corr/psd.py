"""Nearest positive-semidefinite correlation matrix — Higham (2002) (corr framework).

Estimated or stress-shocked correlation matrices are routinely **not** PSD (e.g. "set every
pairwise ρ to 0.9" produces negative eigenvalues). Feeding such a matrix to a Cholesky
factorisation gives imaginary "vols" / negative variance and breaks correlated simulation, so
before any matrix drives Monte Carlo it is projected to the nearest valid correlation matrix.
Higham's alternating-projections method finds that nearest matrix (in Frobenius norm).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def is_positive_semidefinite(matrix: NDArray, tol: float = 1e-10) -> bool:
    """True if ``matrix`` is symmetric PSD to tolerance ``tol``."""
    m = np.asarray(matrix, dtype=float)
    if not np.allclose(m, m.T, atol=1e-12):
        return False
    return float(np.linalg.eigvalsh((m + m.T) / 2).min()) >= -tol


def _project_psd(matrix: NDArray) -> NDArray:
    """Project a symmetric matrix onto the PSD cone by clipping negative eigenvalues."""
    vals, vecs = np.linalg.eigh((matrix + matrix.T) / 2)
    return (vecs * np.maximum(vals, 0.0)) @ vecs.T


def nearest_correlation(
    matrix: NDArray, *, max_iter: int = 100, tol: float = 1e-10
) -> NDArray[np.float64]:
    """Nearest correlation matrix (unit diagonal, PSD) via Higham alternating projections."""
    a = np.asarray(matrix, dtype=float)
    y = a.copy()
    delta_s = np.zeros_like(a)
    for _ in range(max_iter):
        r = y - delta_s
        x = _project_psd(r)  # projection onto PSD matrices
        delta_s = x - r
        y = x.copy()
        np.fill_diagonal(y, 1.0)  # projection onto unit-diagonal matrices
        if np.linalg.norm(y - x, ord="fro") <= tol * np.linalg.norm(y, ord="fro"):
            break
    return y
