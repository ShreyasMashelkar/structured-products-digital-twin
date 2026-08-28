"""Black-Scholes with a volatility **term structure** — one vol per maturity, not one vol.

The desk calibrates a surface with a real term structure (measured on NIFTY, 2026-08-28:
9.6% at 11 days rising to 12.8% at 305) and then priced every note off a single scalar
``atm_vol`` read at one tenor. A 1.5-year note and a 3-month note got the same volatility,
and on an upward-sloping curve that understates the long-dated one — which is exactly the
population a structured note desk sells.

This model keeps the GBM but lets ``σ`` depend on time, which is the smallest change that
respects the data. Simulation is driven by **forward variance** over each step rather than a
constant ``σ²Δt``, so the integrated variance to every observation date matches the surface's
own ATM total variance:

    w(t) = ∫₀ᵗ σ(u)² du        matched at each calibrated pillar
    Var[log S_{t+Δ} − log S_t] = w(t+Δ) − w(t)

Interpolation is linear in ``w`` at fixed moneyness — the representation calendar no-arbitrage
is stated in, so a calendar-clean surface produces non-negative forward variance by
construction.

**Past the last pillar it holds σ flat, not w flat.** That is a deliberate departure from
:meth:`spdt.vol.surface.VolSurface.total_variance`, whose flat-``w`` extrapolation implies
σ ∝ 1/√τ — vol *decaying* with maturity, which from a 60-day pillar prices a 1.5-year note at
3.2% against a 9.7% front. Flat σ is not a forecast either; it is the least-wrong default
until the surface reaches the tenors being quoted, and it is the single place to change when
a genuine long-end extrapolation policy is chosen.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from math import exp

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class BlackScholesTermVol:
    """Risk-neutral GBM with constant rate/dividend and a piecewise ATM vol term structure.

    ``pillars`` is ``((tau, atm_vol), ...)`` ascending in ``tau``, each ``tau > 0``. A single
    pillar reproduces :class:`~spdt.pricing.models.bs.BlackScholes` at that vol exactly.
    """

    spot: float
    r: float
    q: float
    pillars: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if not self.pillars:
            raise ValueError("a vol term structure needs at least one pillar")
        taus = [t for t, _ in self.pillars]
        if any(t <= 0.0 for t in taus):
            raise ValueError("term-structure pillars must have positive maturity")
        if taus != sorted(taus) or len(set(taus)) != len(taus):
            raise ValueError("term-structure pillars must be strictly ascending in maturity")
        if any(v <= 0.0 for _, v in self.pillars):
            raise ValueError("term-structure pillars must have positive volatility")

    # --- the term structure ------------------------------------------------------------

    def total_variance(self, t: float) -> float:
        """``w(t) = ∫₀ᵗ σ(u)²du``, linear in ``w`` between pillars, flat ``σ`` past the last."""
        if t <= 0.0:
            return 0.0
        taus = [tau for tau, _ in self.pillars]
        ws = [v * v * tau for tau, v in self.pillars]
        if t <= taus[0]:
            return ws[0] * t / taus[0]  # flat vol from the origin to the first pillar
        if t >= taus[-1]:
            sigma_last = self.pillars[-1][1]
            return sigma_last * sigma_last * t  # flat *vol*, not flat variance — see module doc
        j = bisect_left(taus, t)
        lo, hi = taus[j - 1], taus[j]
        weight = (t - lo) / (hi - lo)
        return (1.0 - weight) * ws[j - 1] + weight * ws[j]

    def atm_vol(self, t: float) -> float:
        """The ATM vol this model would quote for maturity ``t``."""
        if t <= 0.0:
            raise ValueError("volatility undefined at t <= 0")
        return float(np.sqrt(self.total_variance(t) / t))

    # --- PathModel -----------------------------------------------------------------------

    def simulate(
        self, times: NDArray[np.float64], normals: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        """Exact GBM spots on ``times`` (times[0]==0) given ``(n_paths, len(times)-1)`` draws."""
        dt = np.diff(times)
        w = np.array([self.total_variance(float(t)) for t in times], dtype=float)
        # Forward variance per step. Clipped at zero so a non-monotone (calendar-arbitrageable)
        # term structure degrades to a zero-vol step instead of producing NaNs from a negative
        # square root — the calibration guards against that, but this is the last line.
        var = np.maximum(np.diff(w), 0.0)
        drift = (self.r - self.q) * dt - 0.5 * var
        log_increments = drift + np.sqrt(var) * normals
        log_paths = np.cumsum(log_increments, axis=1)
        spots = self.spot * np.exp(log_paths)
        return np.column_stack([np.full(normals.shape[0], self.spot), spots])

    def discount(self, t: float) -> float:
        return exp(-self.r * t)
