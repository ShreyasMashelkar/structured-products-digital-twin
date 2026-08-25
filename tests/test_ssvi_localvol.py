"""SSVI calibration (calendar-arb-free) and Dupire local vol from the surface."""

from datetime import date

import numpy as np

import pytest

from spdt.data import build_snapshot
from spdt.data.curate import invert_chain
from spdt.data.ingest.synthetic import SyntheticSource
from spdt.vol import SSVISurface, dupire_local_variance, dupire_local_vol

AS_OF = date(2024, 6, 17)


@pytest.fixture
def iv_points():
    raw = SyntheticSource().fetch(AS_OF, "NIFTY")
    snap = build_snapshot(raw)
    return invert_chain(raw, snap.ois_curve)


# --- SSVI -------------------------------------------------------------------------------

def test_ssvi_atm_total_variance_is_theta(iv_points):
    surface = SSVISurface.calibrate(iv_points)
    for tau, theta in surface.theta_pillars.items():
        # w(0, T) = θ(T) by construction.
        assert surface.total_variance(0.0, tau) == pytest.approx(theta, rel=1e-9)


def test_ssvi_is_calendar_and_butterfly_free(iv_points):
    surface = SSVISurface.calibrate(iv_points)
    assert surface.is_calendar_free()  # θ(T) non-decreasing by construction
    assert surface.is_butterfly_free()


def test_ssvi_total_variance_increases_with_maturity(iv_points):
    surface = SSVISurface.calibrate(iv_points)
    taus = sorted(surface.theta_pillars)
    w_near = surface.total_variance(0.05, taus[0])
    w_far = surface.total_variance(0.05, taus[-1])
    assert w_far > w_near


def test_ssvi_fits_the_points_reasonably(iv_points):
    surface = SSVISurface.calibrate(iv_points)
    # SSVI is a 3-parameter global fit, so per-point error is larger than per-slice SVI but
    # should still track the synthetic smile to a few vol points.
    errs = [abs(surface.implied_vol(p.log_moneyness, p.tau) - p.implied_vol) for p in iv_points]
    assert max(errs) < 0.02


# --- Dupire local vol -------------------------------------------------------------------

def test_dupire_recovers_constant_vol_on_a_flat_surface():
    # Flat surface w(k,T) = σ²·T: no skew, no curvature ⇒ local vol == σ everywhere.
    sigma = 0.23

    def w(k: float, t: float) -> float:
        return sigma * sigma * t

    assert dupire_local_vol(w, 0.1, 0.5) == pytest.approx(sigma, abs=1e-6)
    assert dupire_local_vol(w, -0.2, 1.0) == pytest.approx(sigma, abs=1e-6)


def test_dupire_local_variance_positive_on_calibrated_ssvi(iv_points):
    surface = SSVISurface.calibrate(iv_points)
    t = sorted(surface.theta_pillars)[-2]  # avoid the very last tenor's time-derivative edge
    for k in (-0.1, 0.0, 0.1):
        assert dupire_local_variance(surface.total_variance, k, t) > 0.0


def test_dupire_rejects_butterfly_arbitrage():
    # A surface whose smile curves down sharply produces a non-positive denominator.
    def bad_w(k: float, t: float) -> float:
        return 0.04 * t - 0.5 * k * k * t

    with pytest.raises(ValueError):
        dupire_local_variance(bad_w, 0.3, 0.5)


def test_ssvi_calibration_is_arbitrage_free(iv_points):
    """The desk's live route: calibrating a VolSurface as SSVI yields a butterfly- and
    calendar-arbitrage-free surface (GJ conditions enforced + non-decreasing θ)."""
    from spdt.vol import VolSurface

    surf = VolSurface.calibrate(iv_points, "NIFTY", param_model="SSVI")
    assert surf.param_model == "SSVI"
    assert surf.arb_status.butterfly_ok and surf.arb_status.calendar_ok
    assert surf.arb_status.is_clean
    assert surf.arb_status.min_g >= 0.0


def test_ssvi_to_svi_slices_round_trip_atm(iv_points):
    """The SSVI→SVI per-slice conversion is exact: each slice's ATM total variance w(0) = θ(T)."""
    ssvi = SSVISurface.calibrate(iv_points)
    assert ssvi.is_butterfly_free()  # GJ enforcement held
    for tau, svi in ssvi.to_svi_slices().items():
        assert svi.total_variance(0.0) == pytest.approx(ssvi.theta_pillars[tau], rel=1e-9)


def test_joint_fit_survives_a_poisoned_atm_read():
    """θ used to be *read* off a linear interpolation of the two ATM-straddling quotes and
    frozen; one bad print there biased the whole expiry's level. The joint fit lets every
    strike on the slice vote, so the same poison must now be outvoted."""
    from spdt.data.curate.bs_inversion import IVPoint
    from spdt.vol.ssvi import SSVISurface

    tau = 0.5
    expiry = date(2026, 7, 1)
    ks = np.linspace(-0.4, 0.4, 21)
    pts = []
    for k in ks:
        iv = 0.22 - 0.08 * k + 0.15 * k * k
        if abs(k) < 0.025:  # poison exactly the quotes the old ATM interpolation used
            iv += 0.06
        pts.append(IVPoint(expiry, 100.0 * float(np.exp(k)), k >= 0, float(k), tau, float(iv)))

    surf = SSVISurface.calibrate(pts)
    fitted_atm = surf.implied_vol(0.0, tau)
    # The clean smile's ATM is 0.22; the poisoned prints say 0.28. A frozen pillar sits at the
    # poison; the joint fit must land much nearer the smile the other 19 quotes describe.
    assert abs(fitted_atm - 0.22) < 0.02


def test_theta_projection_restores_calendar_freeness():
    """The joint fit is unconstrained in θ ordering; the running-max projection is what makes
    the calendar guarantee unconditional rather than an accident of the data."""
    from spdt.data.curate.bs_inversion import IVPoint
    from spdt.vol.ssvi import SSVISurface

    pts = []
    # Second tenor engineered with LOWER total variance than the first (0.35²·0.6 < 0.5²·0.3).
    for tau, expiry, vol in ((0.3, date(2026, 5, 1), 0.50), (0.6, date(2026, 8, 1), 0.35)):
        for k in np.linspace(-0.3, 0.3, 15):
            pts.append(
                IVPoint(expiry, 100.0 * float(np.exp(k)), k >= 0, float(k), tau,
                        float(vol - 0.05 * k))
            )
    surf = SSVISurface.calibrate(pts)
    assert surf.is_calendar_free()
    assert surf.is_butterfly_free()
