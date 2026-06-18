"""Stress testing: coherent shocks, book reval, and per-trade decomposition (L12)."""

import pytest

from spdt.book import generate_autocallable_book
from spdt.pricing import BlackScholes
from spdt.stress import EQUITY_CRASH, RATE_SHOCK_UP, VOL_SPIKE, Scenario, stress_book

MODEL = BlackScholes(spot=100.0, r=0.03, q=0.0, sigma=0.25)


def test_scenario_applies_shocks_coherently():
    shocked = EQUITY_CRASH.apply(MODEL)
    assert shocked.spot == pytest.approx(70.0)  # −30%
    assert shocked.sigma == pytest.approx(0.35)  # +10 vol pts
    assert shocked.r == pytest.approx(0.025)  # −50 bp
    # The crash is multi-factor, not a lone spot bump.
    assert EQUITY_CRASH.spot_shock < 0 and EQUITY_CRASH.vol_shock > 0


def test_equity_crash_hurts_a_long_autocallable_book():
    trades = generate_autocallable_book(6, initial_fixing=100.0, seed=1)
    result = stress_book(trades, MODEL, EQUITY_CRASH, n_paths=40_000, seed=2)
    assert result.pnl < 0.0  # held notes lose in a crash through the barriers


def test_vol_spike_hurts_short_vol_book():
    trades = generate_autocallable_book(6, initial_fixing=100.0, seed=1)
    result = stress_book(trades, MODEL, VOL_SPIKE, n_paths=40_000, seed=2)
    assert result.pnl < 0.0  # short vega ⇒ a vol spike is a loss


def test_per_trade_pnl_sums_to_total():
    trades = generate_autocallable_book(5, initial_fixing=100.0, seed=1)
    result = stress_book(trades, MODEL, RATE_SHOCK_UP, n_paths=40_000, seed=2)
    assert sum(result.per_trade_pnl.values()) == pytest.approx(result.pnl, abs=1e-9)


def test_zero_scenario_is_a_noop():
    trades = generate_autocallable_book(3, initial_fixing=100.0, seed=1)
    result = stress_book(trades, MODEL, Scenario("flat"), n_paths=40_000, seed=2)
    assert result.pnl == pytest.approx(0.0, abs=1e-9)
