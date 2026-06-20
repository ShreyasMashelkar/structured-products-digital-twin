"""Static (butterfly) and calendar arbitrage diagnostics for the vol surface (L2).

Two distinct no-arbitrage conditions, which manifest differently:

* **Butterfly (static)** — the risk-neutral density implied by a slice must be non-negative.
  Gatheral's **Durrleman condition** ``g(k) ≥ 0`` for all ``k`` is exactly this. A violation
  means a negative density: a butterfly spread with negative cost.
* **Calendar** — at fixed log-moneyness, total variance must be non-decreasing in maturity
  (``w(k, T₂) ≥ w(k, T₁)`` for ``T₂ > T₁``). Independent SVI slices can cross and violate
  this; SSVI removes it by construction (next slice).

These are checks/diagnostics. Repair (re-fitting under constraints, or moving to SSVI) is a
separate concern; here we report so callers can decide.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from spdt.vol.svi import SVIParams


def durrleman_g(params: SVIParams, k: NDArray[np.float64]) -> NDArray[np.float64]:
    """Durrleman's ``g(k)`` for a slice; butterfly-arbitrage-free iff ``g(k) ≥ 0`` (and w>0)."""
    w, w1, w2 = params.derivatives(k)
    term1 = (1.0 - k * w1 / (2.0 * w)) ** 2
    term2 = (w1 * w1 / 4.0) * (1.0 / w + 0.25)
    return term1 - term2 + w2 / 2.0


@dataclass(frozen=True)
class ArbReport:
    """Surface-level arbitrage diagnostics carried on the snapshot (design doc §7)."""

    butterfly_ok: bool
    min_g: float  # smallest Durrleman g over all slices/grid (negative ⇒ butterfly arb)
    calendar_ok: bool
    n_slices: int

    @property
    def is_clean(self) -> bool:
        return self.butterfly_ok and self.calendar_ok


def check_butterfly(
    params: SVIParams, *, k_grid: NDArray[np.float64] | None = None, tol: float = -1e-8
) -> tuple[bool, float]:
    """Return ``(ok, min_g)`` for one slice. ``tol`` allows a tiny numerical slack below 0."""
    grid: NDArray[np.float64] = (
        np.linspace(-1.5, 1.5, 301) if k_grid is None else np.asarray(k_grid, dtype=np.float64)
    )
    g = durrleman_g(params, grid)
    min_g = float(np.min(g))
    return (min_g >= tol and bool(np.all(params.total_variance(grid) > 0.0)), min_g)


def check_calendar(
    slices: list[SVIParams], *, k_grid: NDArray[np.float64] | None = None, tol: float = -1e-8
) -> bool:
    """Total variance non-decreasing in maturity at fixed ``k``; ``slices`` ordered by tenor."""
    grid: NDArray[np.float64] = (
        np.linspace(-1.5, 1.5, 301) if k_grid is None else np.asarray(k_grid, dtype=np.float64)
    )
    prev = None
    for params in slices:
        w = params.total_variance(grid)
        if prev is not None and bool(np.any(w - prev < tol)):
            return False
        prev = w
    return True


def check_slices(
    slices: list[SVIParams], *, k_grid: NDArray[np.float64] | None = None
) -> ArbReport:
    """Run butterfly + calendar checks over tenor-ordered ``slices`` and summarise."""
    if not slices:
        return ArbReport(butterfly_ok=True, min_g=float("inf"), calendar_ok=True, n_slices=0)
    results = [check_butterfly(p, k_grid=k_grid) for p in slices]
    butterfly_ok = all(ok for ok, _ in results)
    min_g = min(g for _, g in results)
    calendar_ok = check_calendar(slices, k_grid=k_grid)
    return ArbReport(
        butterfly_ok=butterfly_ok, min_g=min_g, calendar_ok=calendar_ok, n_slices=len(slices)
    )
