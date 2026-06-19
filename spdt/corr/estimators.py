"""Correlation estimators from return histories (corr framework, feeds L4/L12).

Historical sample correlation for a stable long-run view, and EWMA for a recency-weighted one
(the RiskMetrics λ≈0.94 convention) that reacts to regime changes. Both consume log-returns
shaped ``(observations, assets)`` and return a correlation matrix; neither guarantees PSD once
shocked, which is what :mod:`spdt.corr.psd` repairs.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def historical_correlation(returns: NDArray) -> NDArray[np.float64]:
    """Sample correlation of ``returns`` (shape ``(T, n_assets)``)."""
    r = np.asarray(returns, dtype=float)
    return np.corrcoef(r, rowvar=False)


def ewma_correlation(returns: NDArray, *, lam: float = 0.94) -> NDArray[np.float64]:
    """Exponentially-weighted correlation; recent observations weigh more (RiskMetrics)."""
    r = np.asarray(returns, dtype=float)
    t = r.shape[0]
    # Weights grow toward the most recent row; normalised to sum to one.
    weights = lam ** np.arange(t - 1, -1, -1)
    weights /= weights.sum()
    mean = np.average(r, axis=0, weights=weights)
    centered = r - mean
    cov = (centered * weights[:, None]).T @ centered
    std = np.sqrt(np.diag(cov))
    corr = cov / np.outer(std, std)
    np.fill_diagonal(corr, 1.0)
    return corr
