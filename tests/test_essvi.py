"""eSSVI: per-tenor skew whose no-crossing guarantee is enforced, not assumed.

The formative failure is reproduced as a test: slices satisfying the folklore adjacency
conditions (θ↑, ψ↑, |Δ(ρψ)| ≤ Δψ) can still cross near the money. The surface's guarantee is
therefore numerical, and these tests exercise it on exactly the configurations that broke the
parametric version.
"""

from datetime import date, timedelta

import numpy as np

from spdt.data.curate.bs_inversion import IVPoint
from spdt.vol.essvi import ESSVISlice, ESSVISurface, _ensure_no_cross
from spdt.vol.surface import VolSurface


def _points(tau: float, atm: float, skew: float, expiry_days: int) -> list[IVPoint]:
    expiry = date(2026, 1, 1) + timedelta(days=expiry_days)
    ks = np.linspace(-0.35, 0.35, 15)
    return [
        IVPoint(expiry, 100.0 * float(np.exp(k)), k >= 0, float(k), tau,
                float(atm + skew * k + 0.4 * k * k))
        for k in ks
    ]


def _chain() -> list[IVPoint]:
    # Skew varying strongly by tenor — the shape SSVI's single global rho cannot follow.
    return (
        _points(0.10, 0.24, -0.30, 37)
        + _points(0.25, 0.22, -0.18, 91)
        + _points(0.50, 0.21, -0.10, 183)
        + _points(1.00, 0.205, -0.06, 365)
    )


def test_the_folklore_adjacency_conditions_are_not_sufficient():
    """The pair that broke the parametric version: equal θ, growing ψ and |ρ| passes all
    three conditions and still crosses near the money. This is why the guarantee is numerical."""
    lo = ESSVISlice(theta=0.00095, psi=0.0421, rho=-0.360)
    hi = ESSVISlice(theta=0.00095, psi=0.0466, rho=-0.418)
    assert hi.theta >= lo.theta and hi.psi >= lo.psi
    assert abs(hi.rho * hi.psi - lo.rho * lo.psi) <= (hi.psi - lo.psi) + 1e-12
    grid = np.linspace(-1.5, 1.5, 301)
    gap = np.asarray(hi.total_variance(grid)) - np.asarray(lo.total_variance(grid))
    assert gap.min() < -1e-9  # all three hold, and the slices cross anyway


def test_enforcement_repairs_exactly_that_pair():
    lo = ESSVISlice(theta=0.00095, psi=0.0421, rho=-0.360)
    hi = ESSVISlice(theta=0.00095, psi=0.0466, rho=-0.418)
    grid = np.linspace(-1.5, 1.5, 301)
    fixed = _ensure_no_cross(hi, lo, grid)
    gap = np.asarray(fixed.total_variance(grid)) - np.asarray(lo.total_variance(grid))
    assert gap.min() >= -1e-9


def test_calibrated_surface_is_clean_and_beats_ssvi_on_tenor_varying_skew():
    pts = _chain()
    essvi = VolSurface.calibrate(pts, "X", param_model="eSSVI")
    ssvi = VolSurface.calibrate(pts, "X", param_model="SSVI")
    assert essvi.arb_status.butterfly_ok and essvi.arb_status.calendar_ok
    # On skew that genuinely varies by tenor, per-tenor rho must fit better than one global rho.
    assert essvi.fit_status.rmse_bps < ssvi.fit_status.rmse_bps


def test_theta_monotonicity_makes_the_domination_anchor_valid():
    """The bisection terminates because w is non-decreasing in θ at fixed (ψ, ρ) — checked
    numerically here since the proof is in a docstring, not a test."""
    grid = np.linspace(-2.0, 2.0, 401)
    for psi, rho in ((0.05, -0.4), (0.3, 0.6), (1.2, -0.9)):
        w_small = np.asarray(ESSVISlice(0.02, psi, rho).total_variance(grid))
        w_large = np.asarray(ESSVISlice(0.05, psi, rho).total_variance(grid))
        assert np.all(w_large >= w_small - 1e-12)


def test_surface_reports_calendar_freeness_directly():
    surf = ESSVISurface.calibrate(_chain())
    assert surf.is_calendar_free()
    # And the emitted SVI slices carry per-tenor rho — the point of the exercise.
    rhos = [s.rho for s in surf.slices.values()]
    assert max(rhos) - min(rhos) > 0.05
