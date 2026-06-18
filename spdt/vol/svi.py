"""Raw SVI: per-slice total-variance parametrisation and least-squares calibration (L2).

For one maturity slice, Gatheral's raw SVI models **total variance** ``w = σ²·T`` as a
function of log-moneyness ``k = log(K/F)``::

    w(k) = a + b·( ρ·(k − m) + √((k − m)² + σ²) )

with five parameters ``(a, b, ρ, m, σ)``. We fit total variance (not implied vol) by least
squares because total variance is what the arbitrage conditions are stated in and what SSVI
and Dupire consume downstream — fitting in vol and squaring reintroduces the same numerical
noise the surface layer exists to remove.

Calendar arbitrage *between* slices is not addressed here (independent SVI slices can cross);
that is exactly what SSVI fixes by construction and is the next slice. Static (butterfly)
arbitrage *within* a slice is checked in :mod:`spdt.vol.arbitrage`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import least_squares


@dataclass(frozen=True)
class SVIParams:
    """The five raw-SVI parameters for a single maturity slice."""

    a: float  # vertical level of total variance
    b: float  # angle between the asymptotes (≥ 0)
    rho: float  # skew / rotation, |ρ| < 1
    m: float  # horizontal shift of the smile
    sigma: float  # ATM curvature / smoothing (> 0)

    def total_variance(self, k: NDArray[np.float64] | float) -> NDArray[np.float64] | float:
        """Total variance ``w(k)`` at log-moneyness ``k`` (scalar or array)."""
        x = np.asarray(k, dtype=float) - self.m
        w = self.a + self.b * (self.rho * x + np.sqrt(x * x + self.sigma * self.sigma))
        return w if np.ndim(k) else float(w)

    def derivatives(self, k: NDArray[np.float64]) -> tuple[NDArray, NDArray, NDArray]:
        """Return ``(w, w', w'')`` w.r.t. ``k`` — closed-form, used by the Durrleman check."""
        x = np.asarray(k, dtype=float) - self.m
        r = np.sqrt(x * x + self.sigma * self.sigma)
        w = self.a + self.b * (self.rho * x + r)
        w1 = self.b * (self.rho + x / r)
        w2 = self.b * (self.sigma * self.sigma) / (r * r * r)
        return w, w1, w2


def total_variance_from_iv(implied_vol: NDArray | float, tau: float) -> NDArray | float:
    """Convert implied vol(s) at year-fraction ``tau`` to total variance ``σ²·T``."""
    iv = np.asarray(implied_vol, dtype=float)
    w = iv * iv * tau
    return w if np.ndim(implied_vol) else float(w)


def calibrate_svi(
    k: NDArray[np.float64], w: NDArray[np.float64], *, max_nfev: int = 2000
) -> SVIParams:
    """Calibrate raw SVI to observed ``(k, w)`` total-variance points by least squares.

    Bounds enforce the basic shape constraints (``b ≥ 0``, ``|ρ| < 1``, ``σ > 0``); they do
    not by themselves guarantee a butterfly-arbitrage-free fit, which is why the result is
    passed through :mod:`spdt.vol.arbitrage` afterwards.
    """
    k = np.asarray(k, dtype=float)
    w = np.asarray(w, dtype=float)
    if k.size < 5:
        raise ValueError(f"SVI needs at least 5 points to fit 5 params, got {k.size}")

    w_atm = float(np.interp(0.0, k, w)) if k.size else float(np.mean(w))
    # Seed: a at the ATM level, modest convexity, no skew, centred.
    p0 = [max(w_atm * 0.5, 1e-6), 0.1, 0.0, 0.0, 0.1]
    lower = [-np.inf, 0.0, -0.999, k.min() - 1.0, 1e-6]
    upper = [np.inf, np.inf, 0.999, k.max() + 1.0, 10.0]

    def residual(p: NDArray[np.float64]) -> NDArray[np.float64]:
        a, b, rho, m, sigma = p
        return SVIParams(a, b, rho, m, sigma).total_variance(k) - w

    sol = least_squares(residual, p0, bounds=(lower, upper), max_nfev=max_nfev)
    a, b, rho, m, sigma = sol.x
    return SVIParams(a=a, b=b, rho=rho, m=m, sigma=sigma)
