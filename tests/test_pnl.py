"""P&L attribution: the explained-plus-residual identity and a small residual (L10)."""

import pytest

from spdt.pnl import age, attribute
from spdt.pricing import BlackScholes
from spdt.products import Autocallable, EuropeanOption

VANILLA = EuropeanOption(strike=100.0, expiry=1.0, is_call=True)
NOTE = Autocallable(
    notional=100.0,
    observation_times=(0.25, 0.5, 0.75, 1.0),
    coupon_rate=0.03,
    autocall_level=1.0,
    coupon_barrier=0.7,
    knock_in=0.6,
    initial_fixing=100.0,
)
DT = 1.0 / 52.0


def test_explained_plus_residual_equals_total():
    m0 = BlackScholes(100.0, 0.03, 0.0, 0.2)
    m1 = BlackScholes(102.0, 0.03, 0.0, 0.21)
    ex = attribute(VANILLA, m0, m1, DT, n_paths=200_000, seed=1)
    assert ex.explained + ex.residual == pytest.approx(ex.total, abs=1e-12)


def test_vanilla_residual_is_small_for_small_moves():
    m0 = BlackScholes(100.0, 0.03, 0.0, 0.2)
    m1 = BlackScholes(101.0, 0.031, 0.0, 0.205)  # 1% spot, +0.5 vol pt, +10bp rate
    ex = attribute(VANILLA, m0, m1, DT, n_paths=400_000, seed=1)
    # A smooth payoff under BS is explained almost entirely by the second-order Taylor terms.
    assert abs(ex.residual) < 0.02 * abs(ex.total)


def test_delta_dominates_a_pure_spot_move():
    m0 = BlackScholes(100.0, 0.03, 0.0, 0.2)
    m1 = BlackScholes(101.0, 0.03, 0.0, 0.2)  # spot only, no time/vol/rate change... except dt
    ex = attribute(VANILLA, m0, m1, dt=1e-6, n_paths=400_000, seed=1)
    assert ex.delta_pnl > 0  # call gains as spot rises
    assert abs(ex.vega_pnl) < 1e-9 and abs(ex.rho_pnl) < 1e-9


def test_autocallable_attribution_reconciles():
    m0 = BlackScholes(100.0, 0.03, 0.0, 0.25)
    m1 = BlackScholes(101.0, 0.03, 0.0, 0.255)
    ex = attribute(NOTE, m0, m1, DT, n_paths=400_000, seed=2)
    assert ex.explained + ex.residual == pytest.approx(ex.total, abs=1e-12)
    # Even with barriers, the residual should be a modest slice of the total move.
    assert abs(ex.residual) < 0.5 * abs(ex.total) + 0.05


def test_age_shifts_schedule_and_guards_crossings():
    aged = age(NOTE, 0.1)
    assert aged.observation_times == pytest.approx((0.15, 0.4, 0.65, 0.9))
    with pytest.raises(ValueError, match="crosses"):
        age(NOTE, 0.30)  # would push the first observation (0.25) past today
