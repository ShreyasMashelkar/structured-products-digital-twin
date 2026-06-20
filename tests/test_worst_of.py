"""Worst-of autocallable: a first-class basket product where correlation actually bites.

The economics a structurer relies on: a worst-of is worth *less* than the same note on any
single name (the worst performer drags it down), and as correlation → 1 the dispersion the
investor is short collapses, so the note's value rises toward the single-name case. That
correlation sensitivity is the whole reason the desk can pay a higher coupon on a worst-of.
"""

import numpy as np
import pytest

from spdt.pricing import BlackScholes, price_mc, price_worst_of, worst_of_greeks
from spdt.products import Autocallable, WorstOfAutocallable

OBS = (0.5, 1.0)
SPOTS = np.array([100.0, 100.0, 100.0])
VOLS = np.array([0.25, 0.25, 0.25])


def _worst_of(initial_fixings=None):
    return WorstOfAutocallable(
        notional=100.0, observation_times=OBS, coupon_rate=0.04, autocall_level=1.0,
        coupon_barrier=0.8, knock_in=0.6, memory=False,
        underlyings=("A", "B", "C"), initial_fixings=initial_fixings,
    )


def _corr(rho: float) -> np.ndarray:
    c = np.full((3, 3), rho)
    np.fill_diagonal(c, 1.0)
    return c


def test_worst_of_is_worth_less_than_the_single_name():
    wo = price_worst_of(_worst_of(), SPOTS, VOLS, _corr(0.5), r=0.03, n_paths=80_000, seed=1).price
    single = price_mc(
        Autocallable(100.0, OBS, 0.04, 1.0, 0.8, 0.6, initial_fixing=None),
        BlackScholes(100.0, 0.03, 0.0, 0.25), n_paths=80_000, seed=1,
    ).price
    assert wo < single  # the worst performer drags the basket below any one name


def test_higher_correlation_lifts_the_worst_of():
    low = price_worst_of(_worst_of(), SPOTS, VOLS, _corr(0.2), r=0.03, n_paths=80_000, seed=2).price
    high = price_worst_of(_worst_of(), SPOTS, VOLS, _corr(0.95), r=0.03, n_paths=80_000, seed=2).price
    assert high > low  # as names move together, dispersion shrinks and the note is worth more


def test_struck_worst_of_has_real_delta_and_positive_corr_delta():
    note = _worst_of(initial_fixings=(100.0, 100.0, 100.0))
    g = worst_of_greeks(note, SPOTS, VOLS, _corr(0.5), r=0.03, n_paths=60_000, seed=3)
    assert abs(g["delta"]) > 1e-6  # struck ⇒ genuine basket delta
    assert g["corr_delta"] > 0.0  # value rises with correlation (consistent with above)
    assert np.isfinite(g["vega"])


def test_floating_worst_of_is_scale_invariant():
    # No struck fixings ⇒ basket struck to the path start ⇒ scaling all spots leaves PV unchanged.
    note = _worst_of(initial_fixings=None)
    a = price_worst_of(note, SPOTS, VOLS, _corr(0.5), r=0.05, n_paths=40_000, seed=4).price
    b = price_worst_of(note, SPOTS * 1.5, VOLS, _corr(0.5), r=0.05, n_paths=40_000, seed=4).price
    assert a == pytest.approx(b, rel=1e-9)
