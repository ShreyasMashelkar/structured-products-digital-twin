"""eSSVI: per-tenor skew with an enforced no-crossing guarantee (L2).

SSVI buys its no-arbitrage guarantees with one global shape — a single ρ and one φ(θ) law for
every tenor — and on real chains that rigidity costs about 55bps of fit against per-slice SVI,
because the market's skew genuinely varies by tenor. eSSVI (Hendriks–Martini) relaxes exactly
that: each tenor carries its own ``(θ, ψ, ρ)`` in the SSVI slice form

    w(k) = (θ/2)·(1 + ρ·φ·k + √((φ·k + ρ)² + 1 − ρ²)),   φ = ψ/θ

and the surface stays calendar-free through an **enforced, numerical** no-crossing guarantee
between consecutive tenors.

Numerical rather than parametric, deliberately. A first cut used the parametric adjacency
conditions θ↑, ψ↑, |Δ(ρψ)| ≤ Δψ — and real SPX chains produced slices that satisfied all
three and still crossed near the money (equal-θ neighbours whose |ρ| grows do exactly this).
The conditions are necessary-flavoured folklore, not sufficient, and trusting them would have
shipped a surface whose guarantee was a comment. What IS provable — the derivative reduces to
``(1 + ρφk)/√(...) + 1`` whose worst case is bounded by ``φ²k²(1−ρ²) ≥ 0`` — is that ``w`` is
non-decreasing in θ at fixed ``(ψ, ρ)``. So a slice that copies its predecessor's ``(ψ, ρ)``
with θ_{i+1} ≥ θ_i can never cross it, and bisecting a crossing slice's ``(ψ, ρψ)`` toward
that anchor terminates, by that monotonicity, at a non-crossing slice. The fit carries a
grid-crossing penalty so the bisection rarely has to move anything.

Butterfly no-arb stays per-slice via the Gatheral–Jacquier conditions, which in ``(θ, ψ, ρ)``
read ``ψ(1+|ρ|) < 4`` and ``ψ²(1+|ρ|) ≤ 4θ``. Downstream the emitted SVI slices still run
through the ordinary Durrleman/calendar checkers, so the guarantee is verified twice.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import least_squares

from spdt.data.curate.bs_inversion import IVPoint
from spdt.vol.svi import SVIParams

_BUTTERFLY_MARGIN = 0.98  # sit just inside the open GJ conditions
_PENALTY_GRID = np.linspace(-1.2, 1.2, 61)  # coarse: inside every fit residual, so keep it cheap


@dataclass(frozen=True)
class ESSVISlice:
    theta: float  # ATM total variance
    psi: float  # θ·φ — the ATM skew capacity
    rho: float

    def total_variance(self, k: NDArray | float) -> NDArray | float:
        phi = self.psi / self.theta
        x = phi * np.asarray(k, dtype=float)
        w = 0.5 * self.theta * (
            1.0 + self.rho * x + np.sqrt((x + self.rho) ** 2 + 1.0 - self.rho**2)
        )
        return w if np.ndim(k) else float(w)

    def to_svi(self) -> SVIParams:
        """Exact raw-SVI form of one eSSVI slice (same algebra as the SSVI conversion)."""
        phi = self.psi / self.theta
        root = float(np.sqrt(max(1.0 - self.rho**2, 0.0)))
        return SVIParams(
            a=0.5 * self.theta * (1.0 - self.rho**2),
            b=0.5 * self.psi,
            rho=self.rho,
            m=-self.rho / phi,
            sigma=root / phi,
        )


@dataclass(frozen=True)
class ESSVISurface:
    """Tenor-keyed eSSVI slices satisfying the adjacency and butterfly conditions."""

    slices: dict[float, ESSVISlice]  # tau -> slice

    def to_svi_slices(self) -> dict[float, SVIParams]:
        return {tau: s.to_svi() for tau, s in self.slices.items()}

    def is_calendar_free(self, *, k_grid: NDArray | None = None, tol: float = -1e-9) -> bool:
        """Grid check that consecutive slices never cross — the guarantee, checked directly."""
        grid = np.linspace(-1.5, 1.5, 301) if k_grid is None else k_grid
        taus = sorted(self.slices)
        for a, b in zip(taus, taus[1:]):
            gap = np.asarray(self.slices[b].total_variance(grid)) - np.asarray(
                self.slices[a].total_variance(grid)
            )
            if bool(np.any(gap < tol)):
                return False
        return True

    @classmethod
    def calibrate(cls, iv_points: list[IVPoint]) -> "ESSVISurface":
        by_tau: dict[float, list[IVPoint]] = {}
        for p in iv_points:
            by_tau.setdefault(p.tau, []).append(p)

        out: dict[float, ESSVISlice] = {}
        prev: ESSVISlice | None = None
        grid = np.linspace(-1.5, 1.5, 301)
        for tau in sorted(by_tau):
            pts = by_tau[tau]
            ks = np.array([p.log_moneyness for p in pts])
            ivs = np.array([p.implied_vol for p in pts])
            fitted = _fit_slice(ks, ivs, tau, prev)
            projected = _project(fitted, prev)
            prev = _ensure_no_cross(projected, prev, grid)
            out[tau] = prev
        return cls(out)


def _fit_slice(
    ks: NDArray, ivs: NDArray, tau: float, prev: ESSVISlice | None
) -> ESSVISlice:
    """Bounded vol-space fit of one tenor: monotonicity floors as hard bounds, crossing as a
    grid penalty (it couples all three parameters, so it cannot be a box bound)."""
    order = np.argsort(ks)
    atm_seed = float(np.interp(0.0, ks[order], ivs[order])) ** 2 * tau
    theta_floor = prev.theta if prev else 1e-8
    psi_floor = prev.psi if prev else 1e-8

    def residual(params: NDArray) -> NDArray:
        theta, psi, rho = params
        w = ESSVISlice(theta, psi, rho).total_variance(ks)
        resid = np.sqrt(np.maximum(w, 1e-12) / tau) - ivs
        if prev is not None:
            # Penalise actual grid crossings against the previous slice — the condition the
            # surface is accountable to — so the exact enforcement afterwards rarely binds.
            gap = np.asarray(ESSVISlice(theta, psi, rho).total_variance(_PENALTY_GRID))
            gap = gap - np.asarray(prev.total_variance(_PENALTY_GRID))
            resid = np.append(resid, 25.0 * np.sqrt(np.maximum(-gap, 0.0)))
        return resid

    sol = least_squares(
        residual,
        x0=[max(atm_seed, theta_floor * 1.001), max(0.5 * np.sqrt(max(atm_seed, 1e-8)), psi_floor * 1.001), -0.3],
        bounds=([theta_floor, psi_floor, -0.999], [10.0, 1.99, 0.999]),
        max_nfev=2000,
    )
    return ESSVISlice(float(sol.x[0]), float(sol.x[1]), float(sol.x[2]))


def _project(s: ESSVISlice, prev: ESSVISlice | None) -> ESSVISlice:
    """Monotonicity floors and the per-slice butterfly caps.

    Calendar no-crossing is NOT established here — the parametric adjacency conditions turned
    out insufficient on real chains — so this only enforces what is provable slice-locally:
    θ and ψ floors (needed by the domination argument in ``_ensure_no_cross``) and the
    Gatheral–Jacquier butterfly caps. The crossing guarantee lives in ``_ensure_no_cross``.
    """
    theta = max(s.theta, prev.theta if prev else 0.0, 1e-10)
    psi = max(s.psi, prev.psi if prev else 0.0, 1e-10)
    rho = float(np.clip(s.rho, -0.999, 0.999))

    # Butterfly (GJ in (θ, ψ, ρ)): ψ(1+|ρ|) < 4 and ψ²(1+|ρ|) ≤ 4θ.
    cap = _BUTTERFLY_MARGIN * 4.0 / (1.0 + abs(rho))
    psi = min(psi, cap, float(np.sqrt(_BUTTERFLY_MARGIN * 4.0 * theta / (1.0 + abs(rho)))))
    if prev is not None:
        psi = max(psi, prev.psi)  # the caps must not undo monotonicity

    return ESSVISlice(theta, psi, rho)


def _ensure_no_cross(
    cand: ESSVISlice, prev: ESSVISlice | None, grid: NDArray, *, tol: float = -1e-9
) -> ESSVISlice:
    """Bisect ``cand``'s ``(ψ, ρψ)`` toward ``prev``'s until the pair no longer crosses.

    Terminates because the λ = 1 endpoint — the predecessor's ``(ψ, ρ)`` under ``cand``'s
    larger θ — provably dominates: ``w`` is non-decreasing in θ at fixed ``(ψ, ρ)``. λ = 0 is
    the fitted slice; the smallest non-crossing λ keeps as much of the fit as the guarantee
    allows. The final slice is re-checked, so a failure here is an exception, not a surface.
    """
    if prev is None:
        return cand

    def crosses(s: ESSVISlice) -> bool:
        gap = np.asarray(s.total_variance(grid)) - np.asarray(prev.total_variance(grid))
        return bool(np.any(gap < tol))

    if not crosses(cand):
        return cand

    def blend(lam: float) -> ESSVISlice:
        psi = (1.0 - lam) * cand.psi + lam * prev.psi
        rho_psi = (1.0 - lam) * cand.rho * cand.psi + lam * prev.rho * prev.psi
        rho = float(np.clip(rho_psi / max(psi, 1e-12), -0.999, 0.999))
        return ESSVISlice(cand.theta, psi, rho)

    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if crosses(blend(mid)):
            lo = mid
        else:
            hi = mid
    result = blend(hi)
    if crosses(result):
        raise ValueError("eSSVI no-crossing enforcement failed to converge")
    return result
