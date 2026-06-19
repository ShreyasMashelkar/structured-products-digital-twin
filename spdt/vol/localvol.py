"""Dupire local volatility from the calibrated total-variance surface (L2).

Gatheral's form of the Dupire equation in log-moneyness ``k`` and total variance
``w(k, T) = σ_BS²·T``::

                              ∂w/∂T
    σ_LV²(k,T) = ─────────────────────────────────────────────────────────────
                 1 − (k/w)·∂w/∂k + ¼·(−¼ − 1/w + k²/w²)·(∂w/∂k)² + ½·∂²w/∂k²

The derivatives are taken on the **smooth calibrated parametrisation** (SVI/SSVI), never by
finite-differencing raw quotes — doing the latter is what makes naive Dupire explode. A local
volatility built this way reprices the vanilla surface exactly *by construction*; what it does
not capture is forward-smile dynamics, which is the gap the LSV model and the model reserve
(L11) exist to quantify.
"""

from __future__ import annotations

from math import sqrt
from typing import Callable

WFunc = Callable[[float, float], float]


def dupire_local_variance(
    w: WFunc, k: float, t: float, *, dk: float = 1e-3, dt: float = 1e-4
) -> float:
    """Dupire local *variance* ``σ_LV²(k, T)`` from a total-variance surface ``w(k, T)``."""
    if t - dt <= 0.0:
        raise ValueError("need t > dt for the central time derivative")
    w0 = w(k, t)
    if w0 <= 0.0:
        raise ValueError("total variance must be positive")

    w_t = (w(k, t + dt) - w(k, t - dt)) / (2.0 * dt)
    w_k = (w(k + dk, t) - w(k - dk, t)) / (2.0 * dk)
    w_kk = (w(k + dk, t) - 2.0 * w0 + w(k - dk, t)) / (dk * dk)

    denom = (
        1.0
        - (k / w0) * w_k
        + 0.25 * (-0.25 - 1.0 / w0 + (k * k) / (w0 * w0)) * w_k * w_k
        + 0.5 * w_kk
    )
    if denom <= 0.0:
        raise ValueError("non-positive Dupire denominator — surface has a butterfly arbitrage")
    return w_t / denom


def dupire_local_vol(w: WFunc, k: float, t: float, *, dk: float = 1e-3, dt: float = 1e-4) -> float:
    """Dupire local volatility ``σ_LV(k, T)``."""
    return sqrt(dupire_local_variance(w, k, t, dk=dk, dt=dt))
