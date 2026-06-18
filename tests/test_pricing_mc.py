"""Monte-Carlo prices converge to the Black-Scholes closed forms (the L4 headline check)."""

import pytest

from spdt.pricing import BlackScholes, bs_cash_or_nothing, bs_vanilla, price_mc
from spdt.products import CashOrNothingDigital, EuropeanOption

MODEL = BlackScholes(spot=100.0, r=0.05, q=0.02, sigma=0.2)
T = 1.0


def test_put_call_parity_in_closed_form():
    call = bs_vanilla(100.0, 100.0, T, 0.05, 0.02, 0.2, is_call=True)
    put = bs_vanilla(100.0, 100.0, T, 0.05, 0.02, 0.2, is_call=False)
    import math

    assert call - put == pytest.approx(100.0 * math.exp(-0.02 * T) - 100.0 * math.exp(-0.05 * T))


@pytest.mark.parametrize("is_call", [True, False])
def test_mc_vanilla_converges_to_closed_form(is_call):
    option = EuropeanOption(strike=105.0, expiry=T, is_call=is_call)
    mc = price_mc(option, MODEL, n_paths=200_000, seed=1)
    analytic = bs_vanilla(100.0, 105.0, T, 0.05, 0.02, 0.2, is_call)
    assert abs(mc.price - analytic) < 4 * mc.std_error  # within sampling noise
    assert mc.std_error < 0.05


def test_mc_digital_converges_to_closed_form():
    digital = CashOrNothingDigital(strike=100.0, expiry=T, payout=1.0, is_call=True)
    mc = price_mc(digital, MODEL, n_paths=200_000, seed=2)
    analytic = bs_cash_or_nothing(100.0, 100.0, T, 0.05, 0.02, 0.2, is_call=True)
    assert abs(mc.price - analytic) < 4 * mc.std_error


def test_sobol_also_converges():
    option = EuropeanOption(strike=100.0, expiry=T, is_call=True)
    mc = price_mc(option, MODEL, n_paths=2**15, method="sobol", seed=3)
    analytic = bs_vanilla(100.0, 100.0, T, 0.05, 0.02, 0.2, is_call=True)
    assert mc.price == pytest.approx(analytic, abs=0.05)


def test_antithetic_requires_even_paths():
    option = EuropeanOption(strike=100.0, expiry=T)
    with pytest.raises(ValueError, match="even"):
        price_mc(option, MODEL, n_paths=99_999)
