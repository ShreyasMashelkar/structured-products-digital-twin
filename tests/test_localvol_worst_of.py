"""Correlated local-vol paths and worst-of pricing under skew.

A worst-of's knock-in sits 30–50% below spot, in the put wing, which is exactly where a single
ATM number is furthest from the market. These tests pin the machinery that lets the barrier see
the fitted skew instead of a flat level.
"""

import numpy as np
import pytest

from spdt.pricing.engine import price_worst_of, price_worst_of_lv
from spdt.pricing.mc.paths import correlated_gbm_paths, correlated_local_vol_paths
from spdt.products.catalog import WorstOfAutocallable

SPOTS = np.array([100.0, 100.0])
CORR = np.array([[1.0, 0.5], [0.5, 1.0]])
R, Q = 0.03, 0.0


def _flat_lv(sigma: float):
    return lambda spots, t: np.full(np.shape(spots), sigma)


def _note() -> WorstOfAutocallable:
    return WorstOfAutocallable(
        notional=100.0, observation_times=(0.25, 0.5, 0.75, 1.0), coupon_rate=0.02,
        autocall_level=1.0, coupon_barrier=0.8, knock_in=0.6, memory=True,
        underlyings=("A", "B"), initial_fixings=(100.0, 100.0),
    )


def test_flat_local_vol_reproduces_gbm_paths():
    """A constant σ_LV must give back geometric Brownian motion, or the scheme is wrong."""
    times = np.linspace(0.0, 1.0, 251)  # fine grid: log-Euler has no exact transition
    sigma = 0.25
    gbm = correlated_gbm_paths(
        SPOTS, np.array([sigma, sigma]), CORR, times, r=R, q=Q,
        n_paths=20_000, rng=np.random.default_rng(3),
    )
    lv = correlated_local_vol_paths(
        SPOTS, [_flat_lv(sigma), _flat_lv(sigma)], CORR, times, r=R, q=Q,
        n_paths=20_000, rng=np.random.default_rng(3),
    )
    assert lv.shape == gbm.shape
    # Same terminal distribution to within Euler discretisation error.
    assert lv[:, -1, 0].mean() == pytest.approx(gbm[:, -1, 0].mean(), rel=2e-2)
    assert lv[:, -1, 0].std() == pytest.approx(gbm[:, -1, 0].std(), rel=3e-2)


def test_terminal_spot_is_a_martingale_under_flat_local_vol():
    times = np.linspace(0.0, 1.0, 251)
    paths = correlated_local_vol_paths(
        SPOTS, [_flat_lv(0.2), _flat_lv(0.2)], CORR, times, r=R, q=Q,
        n_paths=40_000, rng=np.random.default_rng(11),
    )
    assert paths[:, -1, 0].mean() == pytest.approx(100.0 * np.exp((R - Q) * 1.0), rel=1e-2)


def test_correlation_is_preserved_across_assets():
    times = np.linspace(0.0, 1.0, 101)
    paths = correlated_local_vol_paths(
        SPOTS, [_flat_lv(0.3), _flat_lv(0.3)], np.array([[1.0, 0.8], [0.8, 1.0]]),
        times, r=R, q=Q, n_paths=20_000, rng=np.random.default_rng(5),
    )
    returns = np.diff(np.log(paths[:, :, :]), axis=1)
    realised = np.corrcoef(returns[:, :, 0].ravel(), returns[:, :, 1].ravel())[0, 1]
    assert realised == pytest.approx(0.8, abs=0.03)


def test_a_missing_local_vol_function_is_refused():
    with pytest.raises(ValueError, match="one local-vol function per asset"):
        correlated_local_vol_paths(
            SPOTS, [_flat_lv(0.2)], CORR, np.linspace(0, 1, 5), r=R, q=Q,
            n_paths=100, rng=np.random.default_rng(0),
        )


def test_worst_of_under_flat_local_vol_matches_the_constant_vol_pricer():
    """The two engines must agree when the surface is flat; otherwise a price difference under
    a real surface cannot be attributed to skew."""
    sigma = 0.25
    const = price_worst_of(
        _note(), SPOTS, np.array([sigma, sigma]), CORR, r=R, q=Q, n_paths=40_000, seed=4
    ).price
    lv = price_worst_of_lv(
        _note(), SPOTS, [_flat_lv(sigma), _flat_lv(sigma)], CORR,
        r=R, q=Q, n_paths=40_000, seed=4, steps_per_year=104,
    ).price
    assert lv == pytest.approx(const, abs=1.5)


def test_a_steeper_put_wing_lowers_the_worst_of_value():
    """Higher vol below spot breaks the knock-in more often, so the note is worth less.

    This is the economic reason the flat-ATM price was suspect: it prices the barrier at a vol
    the market does not quote there.
    """
    def skewed(spots, t):
        s = np.asarray(spots, dtype=float)
        return np.where(s < 100.0, 0.45, 0.25)  # steep put wing, calm upside

    flat = price_worst_of_lv(
        _note(), SPOTS, [_flat_lv(0.25), _flat_lv(0.25)], CORR,
        r=R, q=Q, n_paths=40_000, seed=6, steps_per_year=52,
    ).price
    wing = price_worst_of_lv(
        _note(), SPOTS, [skewed, skewed], CORR,
        r=R, q=Q, n_paths=40_000, seed=6, steps_per_year=52,
    ).price
    assert wing < flat


def test_surface_total_variance_accepts_arrays():
    """Dupire evaluates the surface on a vector of spots at every step; scalar-only silently
    forces local-vol pricing back onto a flat vol."""
    from datetime import date, timedelta

    from spdt.data.curate.bs_inversion import IVPoint
    from spdt.vol.surface import VolSurface

    expiry = date(2026, 1, 1)
    tau = 1.0
    ks = np.linspace(-0.4, 0.4, 15)
    pts = [
        IVPoint(expiry, 100.0 * float(np.exp(k)), k >= 0, float(k), tau, 0.30 - 0.1 * float(k))
        for k in ks
    ]
    surface = VolSurface.calibrate(pts, "X")

    vector = surface.total_variance(ks, tau)
    assert isinstance(vector, np.ndarray) and vector.shape == ks.shape
    assert surface.total_variance(0.0, tau) == pytest.approx(float(np.interp(0.0, ks, vector)), rel=0.05)
    assert isinstance(surface.total_variance(0.0, tau), float)  # scalars still return scalars
