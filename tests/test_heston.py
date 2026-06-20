"""Heston: CF vanilla reduces to BS, and QE Monte Carlo converges to the CF price (L4)."""

import numpy as np
import pytest

from spdt.pricing import bs_vanilla, price_mc
from spdt.pricing.models import HestonModel
from spdt.products import EuropeanOption

# A typical equity-index parameter set (down-skew, mean reversion).
HESTON = HestonModel(
    spot=100.0, r=0.03, q=0.0, v0=0.04, kappa=1.5, theta=0.04, xi=0.5, rho=-0.6
)


def test_cf_vanilla_reduces_to_black_scholes_in_the_low_vol_of_vol_limit():
    # ξ → 0 with v0 = θ ⇒ deterministic variance ⇒ Black-Scholes at vol √v0.
    flat = HestonModel(100.0, 0.03, 0.0, v0=0.04, kappa=2.0, theta=0.04, xi=1e-4, rho=0.0)
    for strike in (80.0, 100.0, 120.0):
        bs = bs_vanilla(100.0, strike, 1.0, 0.03, 0.0, 0.2, is_call=True)
        assert flat.vanilla(strike, 1.0, is_call=True) == pytest.approx(bs, abs=1e-3)


def test_carr_madan_fft_matches_the_quadrature_vanilla():
    """The FFT pricer (used for whole-smile calibration) agrees with the direct quadrature."""
    strikes = np.array([80.0, 90.0, 100.0, 110.0, 120.0])
    _, fft_calls = HESTON.carr_madan_call(strikes, 1.0)
    for k, fft_price in zip(strikes, fft_calls):
        assert fft_price == pytest.approx(HESTON.vanilla(float(k), 1.0, is_call=True), abs=2e-3)


def test_cf_vanilla_satisfies_put_call_parity():
    import math

    call = HESTON.vanilla(105.0, 1.0, is_call=True)
    put = HESTON.vanilla(105.0, 1.0, is_call=False)
    forward_minus = 100.0 * math.exp(-0.0 * 1.0) - 105.0 * math.exp(-0.03 * 1.0)
    assert call - put == pytest.approx(forward_minus, abs=1e-6)


def test_qe_monte_carlo_converges_to_the_cf_price():
    option = EuropeanOption(strike=100.0, expiry=1.0, is_call=True)
    cf_price = HESTON.vanilla(100.0, 1.0, is_call=True)
    mc = price_mc(option, HESTON, n_paths=200_000, seed=1, steps_per_year=64)
    assert abs(mc.price - cf_price) < 0.1  # QE matches the semi-analytic price


def test_qe_keeps_variance_nonnegative_and_prices_sanely():
    # Strong vol-of-vol that violates Feller — Euler would go negative; QE must not blow up.
    rough = HestonModel(100.0, 0.03, 0.0, v0=0.04, kappa=1.0, theta=0.04, xi=1.0, rho=-0.7)
    option = EuropeanOption(strike=100.0, expiry=1.0, is_call=True)
    mc = price_mc(option, rough, n_paths=100_000, seed=2, steps_per_year=64)
    assert 0.0 < mc.price < 100.0
