"""Dynamic delta hedging: replication in the limit, √Δt error, and slippage drag (L9)."""

from math import sqrt

import pytest

from spdt.hedging import simulate_delta_hedge, simulate_delta_vega_hedge
from spdt.pricing import BlackScholes
from spdt.pricing.models import HestonModel
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


def test_gap_risk_widens_the_tail():
    """An overnight jump the continuous hedge can't catch gives a fat left tail."""
    no_jump = simulate_delta_hedge(MODEL, CALL, n_steps=50, n_paths=80_000, seed=2)
    gap = simulate_delta_hedge(MODEL, CALL, n_steps=50, n_paths=80_000, seed=2,
                               jump_intensity=2.0, jump_mean=-0.10, jump_std=0.03)
    assert gap.tail_5pct < no_jump.tail_5pct  # 5th-percentile P&L is worse with gaps


def test_gap_risk_cannot_be_rebalanced_away():
    """Rebalancing more tightens the diffusion error but NOT the gap-loss tail — the whole
    point: gap risk is not a discretisation error you can hedge out with frequency."""
    coarse = simulate_delta_hedge(MODEL, CALL, n_steps=20, n_paths=80_000, seed=3,
                                  jump_intensity=2.0, jump_mean=-0.12, jump_std=0.03)
    fine = simulate_delta_hedge(MODEL, CALL, n_steps=160, n_paths=80_000, seed=3,
                                jump_intensity=2.0, jump_mean=-0.12, jump_std=0.03)
    assert fine.std_pnl < coarse.std_pnl  # diffusion error still shrinks with frequency
    # ...but the gap tail does not: 8× the rebalancing leaves it at least ~70% as deep.
    assert fine.tail_5pct < 0.7 * coarse.tail_5pct  # both are losses (negative)


def test_vega_hedge_reduces_pnl_dispersion_under_stochastic_vol():
    """Under Heston, delta-only hedging leaves vega exposed; adding a static vega hedge with a
    second vanilla cuts the P&L std (it removes the first-order vol risk)."""
    heston = HestonModel(spot=100.0, r=0.03, q=0.0, v0=0.04, kappa=1.5, theta=0.04, xi=0.6, rho=-0.6)
    target = EuropeanOption(strike=110.0, expiry=1.0, is_call=True)
    hedge = EuropeanOption(strike=100.0, expiry=1.0, is_call=True)  # ATM, carries vega
    res = simulate_delta_vega_hedge(heston, target, hedge, n_steps=50, n_paths=40_000, seed=1)
    assert res.delta_vega_std < res.delta_only_std
    assert res.vega_hedge_ratio > 0.1  # removes a meaningful chunk of the vol risk
