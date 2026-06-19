"""SSVI calibration (calendar-arb-free) and Dupire local vol from the surface."""

from datetime import date

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
