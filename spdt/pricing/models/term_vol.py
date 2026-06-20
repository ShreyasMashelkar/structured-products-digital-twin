"""Black-Scholes with a term structure of (forward) volatility (L4).

Flat-vol Black-Scholes can price an exotic but cannot answer *which maturity* its vega lives
in. This model carries a piecewise-constant **forward vol** between knot tenors, so bumping one
knot isolates the sensitivity to that section of the vol term structure — the input a desk's
bucketed vega ladder and surface-aware P&L explain are built on. Paths are still simulated by
exact lognormal stepping (no discretisation bias), now with a per-step vol read off the term
structure.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from math import exp

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class TermVolBlackScholes:
    """GBM with constant ``r, q`` and a piecewise-constant forward-vol term structure.

    ``knot_times`` are increasing tenors (years); ``knot_vols[i]`` is the forward vol applying
    on ``(knot_times[i-1], knot_times[i]]`` (the first bucket starts at 0). A vol beyond the
    last knot is held flat at the last knot's vol.
    """

    spot: float
    r: float
    q: float
    knot_times: tuple[float, ...]
    knot_vols: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.knot_times) != len(self.knot_vols):
            raise ValueError("knot_times and knot_vols must have equal length")
        if list(self.knot_times) != sorted(self.knot_times):
            raise ValueError("knot_times must be increasing")

    def vol_on(self, t_mid: float) -> float:
        """Forward vol applying at time ``t_mid`` (the bucket whose right edge first exceeds it)."""
        for tk, vk in zip(self.knot_times, self.knot_vols):
            if t_mid <= tk:
                return vk
        return self.knot_vols[-1]

    def bumped(self, bucket: int, dvol: float) -> "TermVolBlackScholes":
        """Copy with ``knot_vols[bucket]`` shifted by ``dvol`` (for bucketed vega)."""
        vols = list(self.knot_vols)
        vols[bucket] += dvol
        return dataclasses.replace(self, knot_vols=tuple(vols))

    def simulate(
        self, times: NDArray[np.float64], normals: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        dt = np.diff(times)
        mids = 0.5 * (times[:-1] + times[1:])
        vols = np.array([self.vol_on(float(m)) for m in mids])
        drift = (self.r - self.q - 0.5 * vols * vols) * dt
        diffusion = vols * np.sqrt(dt)
        log_increments = drift + diffusion * normals
        log_paths = np.cumsum(log_increments, axis=1)
        spots = self.spot * np.exp(log_paths)
        return np.column_stack([np.full(normals.shape[0], self.spot), spots])

    def discount(self, t: float) -> float:
        return exp(-self.r * t)
