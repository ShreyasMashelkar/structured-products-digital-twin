"""LSV: leverage calibration reprices the surface; the LSV − LV reserve is real (L4/L11)."""

import numpy as np

from spdt.modelrisk import model_gap_reserve
from spdt.pricing import bs_vanilla, price_mc
from spdt.pricing.models import LocalVolModel, LSVModel, local_vol_from_surface
from spdt.pricing.models.lsv import _conditional_mean_v
from spdt.products import Autocallable, EuropeanOption


def _flat_surface(sigma: float):
    def w(k, t):
        ones = np.ones_like(np.asarray(k, dtype=float))
        return sigma * sigma * np.asarray(t, dtype=float) * ones

    return w


def _models(sigma=0.2, xi=0.6):
    lv_fn = local_vol_from_surface(_flat_surface(sigma), r=0.03, q=0.0, spot0=100.0)
    lsv = LSVModel(100.0, 0.03, 0.0, v0=0.04, kappa=1.5, theta=0.04, xi=xi, rho=-0.5,
                   local_vol=lv_fn, seed=1)
    lv = LocalVolModel(100.0, 0.03, 0.0, lv_fn)
    return lsv, lv


def test_conditional_mean_v_recovers_a_constant():
    spots = np.linspace(80, 120, 1000)
    v = np.full(1000, 0.04)
    assert np.allclose(_conditional_mean_v(spots, v, n_bins=20), 0.04)


def test_lsv_leverage_reprices_the_vanilla_surface():
    # With a flat local-vol surface, the leverage corrects the stochastic vol so LSV reprices
    # to the same vanilla as Black-Scholes / the local-vol model (up to discretisation).
    lsv, lv = _models(sigma=0.2, xi=0.6)
    option = EuropeanOption(strike=100.0, expiry=1.0, is_call=True)
    bs = bs_vanilla(100.0, 100.0, 1.0, 0.03, 0.0, 0.2, is_call=True)
    lsv_price = price_mc(option, lsv, n_paths=100_000, seed=1, steps_per_year=48).price
    lv_price = price_mc(option, lv, n_paths=100_000, seed=1, steps_per_year=48).price
    assert abs(lsv_price - bs) < 0.3
    assert abs(lsv_price - lv_price) < 0.3


def test_lsv_minus_lv_reserve_on_an_autocallable():
    # LSV and LV agree on vanillas but differ on the forward-smile-sensitive autocallable;
    # that gap is the model reserve. Modest here (flat surface) but real and finite.
    lsv, lv = _models(sigma=0.2, xi=0.6)
    note = Autocallable(100.0, (0.25, 0.5, 0.75, 1.0), 0.03, 1.0, 0.7, 0.6, initial_fixing=100.0)
    lsv_price = price_mc(note, lsv, n_paths=100_000, seed=1, steps_per_year=48).price
    lv_price = price_mc(note, lv, n_paths=100_000, seed=1, steps_per_year=48).price
    reserve = model_gap_reserve(lsv_price, lv_price)
    assert 0.0 <= reserve < 2.0
    assert np.isfinite(reserve)
