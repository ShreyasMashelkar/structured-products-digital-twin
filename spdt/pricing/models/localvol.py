"""Local-volatility model: log-Euler simulation under a Dupire local-vol surface (L4).

The local vol ``σ_LV(S, t)`` is read off the calibrated total-variance surface via Dupire
(L2). By construction this reprices the vanilla surface, so a vanilla priced here matches
Black-Scholes at that strike's implied vol — the consistency check used in the tests, and the
"LV" half of the eventual LSV − LV model reserve (L11).

Simulation is log-Euler on the engine's fine grid (``steps_per_year``); unlike GBM the SDE has
no exact transition, so the time step is a real source of (controllable) discretisation error.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp
from typing import Callable

import numpy as np
from numpy.typing import NDArray

# σ_LV evaluated on a vector of spots at a single time: (spots, t) -> vols.
LocalVolFn = Callable[[NDArray[np.float64], float], NDArray[np.float64]]


@dataclass(frozen=True)
class LocalVolModel:
    """Risk-neutral local-volatility dynamics ``dS = (r−q)S dt + σ_LV(S,t) S dW``."""

    spot: float
    r: float
    q: float
    local_vol: LocalVolFn

    def simulate(
        self, times: NDArray[np.float64], normals: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        """Log-Euler spots on ``times`` (times[0]==0) with one normal per fine step."""
        s = np.full(normals.shape[0], self.spot)
        columns = [s.copy()]
        for i in range(times.size - 1):
            dt = times[i + 1] - times[i]
            sig = np.asarray(self.local_vol(s, float(times[i])), dtype=float)
            drift = (self.r - self.q - 0.5 * sig * sig) * dt
            s = s * np.exp(drift + sig * np.sqrt(dt) * normals[:, i])
            columns.append(s.copy())
        return np.column_stack(columns)

    def discount(self, t: float) -> float:
        return exp(-self.r * t)


def local_vol_from_surface(
    total_variance: Callable[[NDArray | float, float], NDArray | float],
    *,
    r: float,
    q: float,
    spot0: float,
    floor: float = 0.01,
    cap: float = 2.0,
    dk: float = 1e-3,
    dt: float = 1e-4,
) -> LocalVolFn:
    """Build a vectorised ``σ_LV(S, t)`` from a total-variance surface via Dupire.

    Moneyness is taken against the forward ``F(t) = S₀·exp((r−q)t)``. The result is floored and
    capped for simulation stability; a non-positive Dupire denominator (local arbitrage) falls
    back to the floor rather than producing an imaginary vol.
    """

    def sigma(spots: NDArray[np.float64], t: float) -> NDArray[np.float64]:
        tt = max(t, 2.0 * dt)
        forward = spot0 * exp((r - q) * tt)
        k = np.log(np.asarray(spots, dtype=float) / forward)

        w0 = np.asarray(total_variance(k, tt), dtype=float)
        w_t = (np.asarray(total_variance(k, tt + dt)) - np.asarray(total_variance(k, tt - dt))) / (
            2.0 * dt
        )
        w_k = (np.asarray(total_variance(k + dk, tt)) - np.asarray(total_variance(k - dk, tt))) / (
            2.0 * dk
        )
        w_kk = (
            np.asarray(total_variance(k + dk, tt))
            - 2.0 * w0
            + np.asarray(total_variance(k - dk, tt))
        ) / (dk * dk)

        denom = (
            1.0
            - (k / w0) * w_k
            + 0.25 * (-0.25 - 1.0 / w0 + (k * k) / (w0 * w0)) * w_k * w_k
            + 0.5 * w_kk
        )
        var = np.where(denom > 0.0, w_t / np.where(denom > 0.0, denom, 1.0), floor * floor)
        return np.clip(np.sqrt(np.maximum(var, floor * floor)), floor, cap)

    return sigma
