"""Model-risk reserves: model gap, parameter uncertainty, bid-offer (L11)."""

import pytest

from spdt.modelrisk import (
    model_gap_reserve,
    parameter_uncertainty_reserve,
    reserve_from_scenarios,
    total_reserve,
    vol_bid_offer_reserve,
)
from spdt.pricing import BlackScholes
from spdt.products import Autocallable

NOTE = Autocallable(
    notional=100.0,
    observation_times=(0.25, 0.5, 0.75, 1.0),
    coupon_rate=0.03,
    coupon_barrier=0.7,
    knock_in=0.6,
    initial_fixing=100.0,
)
MODEL = BlackScholes(spot=100.0, r=0.03, q=0.0, sigma=0.25)


def test_model_gap_reserve_is_the_absolute_difference():
    assert model_gap_reserve(101.5, 100.2) == pytest.approx(1.3)
    assert model_gap_reserve(100.0, 100.0) == 0.0


def test_parameter_uncertainty_reserve_is_half_the_spread():
    assert parameter_uncertainty_reserve([99.0, 100.0, 101.5]) == pytest.approx(1.25)


def test_vol_bid_offer_reserve_is_positive_and_scales_with_spread():
    narrow = vol_bid_offer_reserve(NOTE, MODEL, 0.005, n_paths=60_000, seed=1)
    wide = vol_bid_offer_reserve(NOTE, MODEL, 0.02, n_paths=60_000, seed=1)
    assert narrow > 0.0
    assert wide > narrow  # a wider vol bid-offer reserves more


def test_reserve_from_scenarios_uses_the_repricer():
    reserve = reserve_from_scenarios(lambda x: 100.0 + x, [-0.5, 0.0, 0.75])
    assert reserve == pytest.approx(0.625)  # half of (100.75 − 99.5)


def test_total_reserve_sums_components():
    assert total_reserve(1.2, 0.5, 0.3) == pytest.approx(2.0)
