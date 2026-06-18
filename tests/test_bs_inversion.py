"""Black-76 pricing identities + implied-vol round-trip including the deep wings."""

import pytest

from spdt.data.curate.bs_inversion import bs_price, bs_vega, implied_vol

F, TAU, DF = 22000.0, 0.25, 0.985


def test_put_call_parity():
    k = 21000.0
    call = bs_price(F, k, TAU, 0.2, DF, is_call=True)
    put = bs_price(F, k, TAU, 0.2, DF, is_call=False)
    assert call - put == pytest.approx(DF * (F - k), abs=1e-9)


def test_price_is_monotonic_in_vol():
    lo = bs_price(F, F, TAU, 0.10, DF, is_call=True)
    hi = bs_price(F, F, TAU, 0.40, DF, is_call=True)
    assert hi > lo


def test_zero_vol_returns_discounted_intrinsic():
    assert bs_price(F, 20000.0, TAU, 0.0, DF, is_call=True) == pytest.approx(DF * 2000.0)
    assert bs_price(F, 25000.0, TAU, 0.0, DF, is_call=True) == pytest.approx(0.0)


def test_vega_matches_finite_difference():
    sigma, h = 0.22, 1e-5
    analytic = bs_vega(F, F, TAU, sigma, DF)
    bumped = (
        bs_price(F, F, TAU, sigma + h, DF, True) - bs_price(F, F, TAU, sigma - h, DF, True)
    ) / (2 * h)
    assert analytic == pytest.approx(bumped, rel=1e-5)


@pytest.mark.parametrize("strike", [16000.0, 19000.0, 22000.0, 25000.0, 30000.0])
@pytest.mark.parametrize("is_call", [True, False])
def test_implied_vol_round_trips(strike, is_call):
    """Pricing at a known vol then inverting recovers it — wings included (Brent path)."""
    true_vol = 0.27
    price = bs_price(F, strike, TAU, true_vol, DF, is_call)
    assert implied_vol(price, F, strike, TAU, DF, is_call) == pytest.approx(true_vol, abs=1e-6)


def test_price_below_intrinsic_is_rejected():
    intrinsic = DF * (F - 20000.0)
    with pytest.raises(ValueError, match="no-arbitrage"):
        implied_vol(intrinsic - 5.0, F, 20000.0, TAU, DF, is_call=True)
