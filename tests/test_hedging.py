"""Dynamic delta hedging: replication in the limit, √Δt error, and slippage drag (L9)."""

from math import sqrt

import pytest

from spdt.hedging import simulate_delta_hedge
from spdt.pricing import BlackScholes
from spdt.products import EuropeanOption

MODEL = BlackScholes(spot=100.0, r=0.03, q=0.0, sigma=0.2)
CALL = EuropeanOption(strike=100.0, expiry=1.0, is_call=True)


def test_hedging_pnl_is_mean_zero():
    res = simulate_delta_hedge(MODEL, CALL, n_steps=50, n_paths=80_000, seed=1)
    # Delta hedging replicates the payoff: mean P&L is zero up to sampling noise.
    assert abs(res.mean_pnl) < 4 * res.std_error


def test_error_shrinks_with_more_rebalancing():
    coarse = simulate_delta_hedge(MODEL, CALL, n_steps=10, n_paths=80_000, seed=1)
    fine = simulate_delta_hedge(MODEL, CALL, n_steps=80, n_paths=80_000, seed=1)
    assert fine.std_pnl < coarse.std_pnl
    # Replication error scales ~√Δt, i.e. ~1/√n_steps: 8× steps ≈ √8 ≈ 2.8× tighter.
    assert coarse.std_pnl / fine.std_pnl == pytest.approx(sqrt(8), rel=0.4)


def test_slippage_is_a_drag_on_the_mean():
    clean = simulate_delta_hedge(MODEL, CALL, n_steps=50, n_paths=80_000, seed=1)
    costly = simulate_delta_hedge(
        MODEL, CALL, n_steps=50, n_paths=80_000, seed=1, slippage_bps=10.0
    )
    assert costly.mean_slippage_cost > 0.0
    assert costly.mean_pnl < clean.mean_pnl  # transaction costs bleed the hedger
