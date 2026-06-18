"""Black-Scholes model: exact geometric-Brownian-motion path simulation (L4).

Constant ``r, q, σ``. Because GBM has an exact transition law, paths are simulated by exact
lognormal stepping between observation dates — there is **no discretisation bias**, so any
gap between the MC price and the closed form is pure sampling error. That is what makes the
convergence test a clean check of the engine rather than of a stepping scheme.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class BlackScholes:
    """Risk-neutral GBM with constant rate, dividend yield and volatility."""

    spot: float
    r: float
    q: float
    sigma: float

    def simulate(
        self, times: NDArray[np.float64], normals: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        """Exact GBM spots on ``times`` (times[0]==0) given ``(n_paths, len(times)-1)`` draws."""
        dt = np.diff(times)
        drift = (self.r - self.q - 0.5 * self.sigma * self.sigma) * dt
        diffusion = self.sigma * np.sqrt(dt)
        log_increments = drift + diffusion * normals  # (n_paths, n_steps)
        log_paths = np.cumsum(log_increments, axis=1)
        spots = self.spot * np.exp(log_paths)
        return np.column_stack([np.full(normals.shape[0], self.spot), spots])

    def discount(self, t: float) -> float:
        return exp(-self.r * t)
