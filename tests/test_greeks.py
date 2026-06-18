"""Greeks cross-check: bump ≈ pathwise ≈ AAD ≈ closed form; LR rescues the digital."""

from math import erf, exp, log, pi, sqrt

import pytest

from spdt.greeks import bs_vanilla_aad, bump_greeks, lr_digital_delta, pathwise_vanilla
from spdt.pricing import BlackScholes, bs_vanilla
from spdt.products import CashOrNothingDigital, EuropeanOption

S, K, T, R, Q, SIG = 100.0, 100.0, 1.0, 0.05, 0.02, 0.2
MODEL = BlackScholes(spot=S, r=R, q=Q, sigma=SIG)


def _n_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2 * pi)


def _n_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _d1() -> float:
    return (log(S / K) + (R - Q + 0.5 * SIG * SIG) * T) / (SIG * sqrt(T))


def _analytic_delta_call() -> float:
    return exp(-Q * T) * _n_cdf(_d1())


def _analytic_vega() -> float:
    return S * exp(-Q * T) * _n_pdf(_d1()) * sqrt(T)


# --- the headline: four methods agree on a vanilla --------------------------------------

def test_aad_price_matches_closed_form():
    price, _ = bs_vanilla_aad(S, K, T, R, Q, SIG, is_call=True)
    assert price == pytest.approx(bs_vanilla(S, K, T, R, Q, SIG, is_call=True), abs=1e-12)


def test_aad_delta_vega_equal_closed_form_exactly():
    # AAD differentiates the exact BS formula, so it equals the analytic Greeks to machine eps.
    _, g = bs_vanilla_aad(S, K, T, R, Q, SIG, is_call=True)
    assert g["delta"] == pytest.approx(_analytic_delta_call(), abs=1e-10)
    assert g["vega"] == pytest.approx(_analytic_vega(), abs=1e-9)


def test_aad_matches_finite_difference_on_rho():
    _, g = bs_vanilla_aad(S, K, T, R, Q, SIG, is_call=True)
    h = 1e-6
    fd = (
        bs_vanilla(S, K, T, R + h, Q, SIG, True) - bs_vanilla(S, K, T, R - h, Q, SIG, True)
    ) / (2 * h)
    assert g["rho"] == pytest.approx(fd, rel=1e-5)


def test_pathwise_vanilla_matches_analytic():
    pw = pathwise_vanilla(MODEL, K, T, is_call=True, n_paths=400_000, seed=1)
    assert pw["delta"] == pytest.approx(_analytic_delta_call(), abs=5e-3)
    assert pw["vega"] == pytest.approx(_analytic_vega(), rel=1e-2)


def test_bump_vanilla_matches_analytic():
    g = bump_greeks(EuropeanOption(K, T, is_call=True), MODEL, n_paths=400_000, seed=1)
    assert g.delta == pytest.approx(_analytic_delta_call(), abs=1e-2)
    assert g.vega == pytest.approx(_analytic_vega(), rel=2e-2)


# --- the digital: pathwise fails, likelihood-ratio works --------------------------------

def test_lr_digital_delta_matches_closed_form():
    analytic = exp(-R * T) * _n_pdf(_d1() - SIG * sqrt(T)) / (S * SIG * sqrt(T))
    lr = lr_digital_delta(MODEL, K, T, is_call=True, n_paths=2_000_000, seed=4)
    assert lr == pytest.approx(analytic, rel=3e-2)
    assert analytic > 0.0  # a zero pathwise estimate (step has no derivative) would be wrong


def test_digital_mc_price_is_consistent():
    from spdt.pricing import bs_cash_or_nothing, price_mc

    mc = price_mc(CashOrNothingDigital(K, T, is_call=True), MODEL, n_paths=200_000, seed=4)
    analytic = bs_cash_or_nothing(S, K, T, R, Q, SIG, is_call=True)
    assert abs(mc.price - analytic) < 4 * mc.std_error


# --- the autocallable carries the right risk signs --------------------------------------

def test_autocallable_is_short_vol_short_gamma():
    from spdt.products import Autocallable

    note = Autocallable(
        notional=100.0,
        observation_times=(0.25, 0.5, 0.75, 1.0),
        coupon_rate=0.03,
        autocall_level=1.0,
        coupon_barrier=0.7,
        knock_in=0.6,
        initial_fixing=100.0,  # struck at inception ⇒ a genuine (non-zero) delta
    )
    g = bump_greeks(note, BlackScholes(100.0, 0.03, 0.0, 0.25), n_paths=400_000, seed=5)
    # The investor sold optionality (the knock-in put + the autocall cap), so the position is
    # short vol and short gamma. Delta near ATM is small and sign-ambiguous, so we don't assert
    # its sign — only that it is finite and modest.
    assert g.vega < 0.0
    assert g.gamma < 0.0
    assert abs(g.delta) < 1.0
