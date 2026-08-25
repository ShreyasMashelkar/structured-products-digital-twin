"""Black-Scholes under Hull-White stochastic rates: the note's own rate risk.

The model's authority rests on three anchors, each a known answer:
sigma_r = 0 must reproduce plain Black-Scholes exactly (same seed, common random numbers);
the pathwise deflators must reprice the initial curve's bonds; and deflated equity must be a
martingale. A hybrid model that fails any of these is not a model with stochastic rates — it
is a bug with extra state.
"""

import numpy as np
import pytest

from spdt.pricing.engine import price_mc
from spdt.pricing.models.bs import BlackScholes
from spdt.pricing.models.bshw import BlackScholesHW, price_mc_hw
from spdt.products.catalog import Autocallable
from spdt.products.primitives import EuropeanOption

OBS = tuple(round(0.25 * i, 4) for i in range(1, 13))  # 3y quarterly


def _note() -> Autocallable:
    return Autocallable(
        notional=100.0, observation_times=OBS, coupon_rate=0.02,
        autocall_level=1.0, coupon_barrier=0.8, knock_in=0.6, memory=True,
        initial_fixing=100.0,
    )


def test_zero_rate_vol_reproduces_black_scholes_exactly():
    """The regression anchor: with sigma_r = 0 the deflator is deterministic and the drift is
    r0, so the price must match plain BS to MC identity, not merely to tolerance."""
    flat = price_mc(_note(), BlackScholes(spot=100.0, r=0.042, q=0.013, sigma=0.2),
                    n_paths=50_000).price
    hw = price_mc_hw(_note(), BlackScholesHW(spot=100.0, r0=0.042, q=0.013, sigma=0.2,
                                             sigma_r=0.0), n_paths=50_000).price
    assert hw == pytest.approx(flat, abs=1e-6)


def test_deflators_reprice_the_initial_curve():
    """E[D(t)] = e^(−r0·t): the phi convexity term exists precisely to make this hold; without
    it the funding leg is mispriced by the rate-vol convexity."""
    m = BlackScholesHW(spot=100.0, r0=0.042, q=0.013, sigma=0.2, sigma_r=0.015)
    grid = np.linspace(0.0, 3.0, 13)
    z = np.random.default_rng(1).standard_normal((100_000, 12))
    _, deflators = m.simulate_joint(grid, z, seed=1)
    for i, t in enumerate(grid):
        assert deflators[:, i].mean() == pytest.approx(np.exp(-0.042 * t), rel=2e-3)


def test_deflated_equity_is_a_martingale():
    m = BlackScholesHW(spot=100.0, r0=0.042, q=0.013, sigma=0.2, sigma_r=0.015, rho=-0.3)
    grid = np.linspace(0.0, 3.0, 13)
    z = np.random.default_rng(2).standard_normal((200_000, 12))
    spots, deflators = m.simulate_joint(grid, z, seed=2)
    deflated = (spots[:, -1] * deflators[:, -1]).mean() * np.exp(0.013 * 3.0)
    assert deflated == pytest.approx(100.0, rel=5e-3)


def test_rate_equity_correlation_moves_a_vanilla_the_right_way():
    """Positive equity-rate correlation must RAISE a call, not cheapen it.

    The naive intuition says the opposite — the call pays when equity is high, rates are then
    high too, so the payoff is discounted harder — and an earlier version of this test asserted
    exactly that. It is wrong because it ignores the drift: under the T-forward measure the
    call prices off the forward's volatility,

        sigma_F^2 = sigma_S^2 + sigma_P^2 + 2*rho*sigma_S*sigma_P,

    where sigma_P is the bond vol (whose shocks are anti-correlated with rates, flipping the
    sign of the cross term). rho > 0 widens the forward distribution, and the vol effect beats
    the discounting covariance. The model got this right when the test did not — which is
    precisely why direction checks belong to closed-form theory, not to intuition."""
    call = EuropeanOption(strike=100.0, expiry=3.0, is_call=True)
    up = price_mc_hw(call, BlackScholesHW(spot=100.0, r0=0.042, q=0.013, sigma=0.2,
                                          sigma_r=0.02, rho=+0.5), n_paths=100_000).price
    dn = price_mc_hw(call, BlackScholesHW(spot=100.0, r0=0.042, q=0.013, sigma=0.2,
                                          sigma_r=0.02, rho=-0.5), n_paths=100_000).price
    assert up > dn


def test_stochastic_rates_price_the_note_close_to_flat_for_short_tenors():
    """The honest magnitude check: at 100bp rate vol the 3y autocallable moves by basis
    points, not points. A large move here would mean a drift or deflator bug, since the note's
    rate exposure is genuinely modest — it is mostly a funding-leg instrument."""
    flat = price_mc(_note(), BlackScholes(spot=100.0, r=0.042, q=0.013, sigma=0.2),
                    n_paths=100_000).price
    hw = price_mc_hw(_note(), BlackScholesHW(spot=100.0, r0=0.042, q=0.013, sigma=0.2,
                                             sigma_r=0.010, rho=-0.15), n_paths=100_000).price
    assert abs(hw - flat) < 0.10


def test_a_sloped_initial_curve_is_reprice_by_the_deflators():
    """With a real curve the deflators must reprice *that curve's* bonds, tenor by tenor —
    the whole point of taking a curve instead of a level."""
    curve = ((0.25, 0.038), (1.0, 0.040), (2.0, 0.042), (3.0, 0.0435), (5.0, 0.044))
    m = BlackScholesHW(spot=100.0, r0=0.042, q=0.013, sigma=0.2, sigma_r=0.012,
                       zero_curve=curve)
    grid = np.linspace(0.0, 3.0, 25)
    z = np.random.default_rng(4).standard_normal((100_000, 24))
    _, deflators = m.simulate_joint(grid, z, seed=4)
    for t_check in (1.0, 2.0, 3.0):
        i = int(np.argmin(np.abs(grid - t_check)))
        zero = float(np.interp(t_check, [p[0] for p in curve], [p[1] for p in curve]))
        assert deflators[:, i].mean() == pytest.approx(np.exp(-zero * t_check), rel=2e-3)


def test_curve_slope_actually_reaches_the_note_price():
    """An upward-sloping curve discounts the far coupons harder than its short rate suggests;
    if the price under the curve equals the price under flat-at-2y, the curve is decorative."""
    flat = price_mc_hw(_note(), BlackScholesHW(spot=100.0, r0=0.042, q=0.013, sigma=0.2,
                                               sigma_r=0.010), n_paths=60_000).price
    steep = ((0.25, 0.030), (1.0, 0.036), (2.0, 0.042), (3.0, 0.050), (5.0, 0.055))
    curved = price_mc_hw(_note(), BlackScholesHW(spot=100.0, r0=0.042, q=0.013, sigma=0.2,
                                                 sigma_r=0.010, zero_curve=steep),
                         n_paths=60_000).price
    assert curved != pytest.approx(flat, abs=0.02)
