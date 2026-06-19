"""Local-vol MC: log-Euler simulation and the reprices-vanillas property (L4)."""

import numpy as np
import pytest

from spdt.pricing import BlackScholes, bs_vanilla, price_mc
from spdt.pricing.models import LocalVolModel, local_vol_from_surface
from spdt.products import EuropeanOption


def _flat_surface(sigma: float):
    def w(k, t):
        return sigma * sigma * np.asarray(t, dtype=float) * np.ones_like(np.asarray(k, dtype=float))

    return w


def test_constant_local_vol_matches_black_scholes():
    sigma = 0.2
    lv = local_vol_from_surface(_flat_surface(sigma), r=0.03, q=0.0, spot0=100.0)
    model = LocalVolModel(spot=100.0, r=0.03, q=0.0, local_vol=lv)
    option = EuropeanOption(strike=100.0, expiry=1.0, is_call=True)
    mc = price_mc(option, model, n_paths=100_000, seed=1, steps_per_year=100)
    analytic = bs_vanilla(100.0, 100.0, 1.0, 0.03, 0.0, sigma, is_call=True)
    assert mc.price == pytest.approx(analytic, abs=0.06)


def test_local_vol_function_is_constant_on_a_flat_surface():
    lv = local_vol_from_surface(_flat_surface(0.25), r=0.03, q=0.0, spot0=100.0)
    vols = lv(np.array([80.0, 100.0, 125.0]), 0.5)
    assert np.allclose(vols, 0.25, atol=1e-3)


def test_skewed_surface_gives_a_downward_local_skew():
    # A put-skewed total-variance surface ⇒ higher local vol for low spots.
    def w(k, t):
        k = np.asarray(k, dtype=float)
        return (0.04 - 0.04 * k + 0.05 * k * k) * np.asarray(t, dtype=float)

    lv = local_vol_from_surface(w, r=0.0, q=0.0, spot0=100.0)
    low, high = lv(np.array([80.0]), 0.5)[0], lv(np.array([120.0]), 0.5)[0]
    assert low > high > 0.0


def test_fine_grid_adds_no_bias_to_black_scholes():
    # GBM steps exactly, so neither the coarse nor the fine grid is biased: both agree with
    # the closed form within sampling error (they differ from each other only because a finer
    # grid draws more normals, i.e. a different sample — not because of any Euler bias).
    model = BlackScholes(100.0, 0.03, 0.0, 0.2)
    option = EuropeanOption(strike=100.0, expiry=1.0, is_call=True)
    analytic = bs_vanilla(100.0, 100.0, 1.0, 0.03, 0.0, 0.2, is_call=True)
    coarse = price_mc(option, model, n_paths=50_000, seed=1)
    fine = price_mc(option, model, n_paths=50_000, seed=1, steps_per_year=50)
    assert abs(coarse.price - analytic) < 4 * coarse.std_error
    assert abs(fine.price - analytic) < 4 * fine.std_error
