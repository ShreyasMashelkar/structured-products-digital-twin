"""Crank–Nicolson PDE: cross-check vs Black-Scholes, MC, and barrier in/out parity (L4).

An independent numerical method (finite differences) agreeing with the closed form and with the
Monte-Carlo engine on the same model is exactly the validation a desk wants before a pricer goes
live: two unrelated implementations, one number.
"""

import pytest

from spdt.pricing import BlackScholes, bs_vanilla, price_mc
from spdt.pricing.pde import crank_nicolson_price
from spdt.products import DownBarrierPut, EuropeanOption

R, Q, SIG, T = 0.04, 0.01, 0.22, 1.0


@pytest.mark.parametrize("strike,is_call", [(90.0, True), (100.0, True), (110.0, False)])
def test_cn_matches_black_scholes(strike, is_call):
    pde = crank_nicolson_price(100.0, strike, T, R, Q, SIG, is_call=is_call, n_s=500, n_t=500)
    bs = bs_vanilla(100.0, strike, T, R, Q, SIG, is_call=is_call)
    assert pde == pytest.approx(bs, abs=2e-2)


def test_cn_matches_monte_carlo():
    pde = crank_nicolson_price(100.0, 100.0, T, R, Q, SIG, is_call=True, n_s=400, n_t=400)
    mc = price_mc(EuropeanOption(100.0, T, is_call=True),
                  BlackScholes(100.0, R, Q, SIG), n_paths=200_000, seed=1).price
    assert pde == pytest.approx(mc, abs=0.1)


def test_cn_converges_to_bs_with_grid_refinement():
    bs = bs_vanilla(100.0, 100.0, T, R, Q, SIG, is_call=True)
    coarse = abs(crank_nicolson_price(100.0, 100.0, T, R, Q, SIG, n_s=60, n_t=60) - bs)
    fine = abs(crank_nicolson_price(100.0, 100.0, T, R, Q, SIG, n_s=600, n_t=600) - bs)
    assert fine < coarse  # the FD error shrinks as the grid is refined


def test_down_and_out_put_plus_in_equals_vanilla():
    """A continuously-monitored down-and-out + down-and-in put = the vanilla put (parity)."""
    barrier, strike = 80.0, 100.0
    do = crank_nicolson_price(100.0, strike, T, R, Q, SIG, is_call=False,
                              barrier=barrier, n_s=500, n_t=500)
    vanilla = bs_vanilla(100.0, strike, T, R, Q, SIG, is_call=False)
    di = vanilla - do  # in = vanilla − out, by parity
    assert do > 0.0 and di > 0.0
    # The discretely-monitored MC down-and-in (fine monitoring) ≈ the PDE continuous one.
    mc_di = price_mc(
        DownBarrierPut(strike=strike, barrier=barrier, expiry=T,
                       monitoring=tuple(round(i / 100, 4) for i in range(1, 101)), knock_in=True),
        BlackScholes(100.0, R, Q, SIG), n_paths=120_000, seed=2,
    ).price
    assert mc_di == pytest.approx(di, abs=0.6)


def test_cn_accepts_a_local_vol_function():
    # A flat local-vol callable must reproduce the constant-vol price.
    flat = crank_nicolson_price(100.0, 100.0, T, R, Q, lambda s, t: 0 * s + SIG, n_s=300, n_t=300)
    const = crank_nicolson_price(100.0, 100.0, T, R, Q, SIG, n_s=300, n_t=300)
    assert flat == pytest.approx(const, abs=1e-6)
