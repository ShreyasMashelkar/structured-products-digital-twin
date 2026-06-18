"""Backtesting on realised paths: outcomes, aggregation, and the drift dependence (L7)."""

import pytest

from spdt.backtest import aggregate, generate_realized_series, roll_issuance
from spdt.products import Autocallable

NOTE = Autocallable(
    notional=100.0,
    observation_times=(0.25, 0.5, 0.75, 1.0),
    coupon_rate=0.03,
    autocall_level=1.0,
    coupon_barrier=0.7,
    knock_in=0.6,
)


def test_realized_series_is_deterministic_and_positive():
    s = generate_realized_series(500, s0=100.0, mu=0.08, sigma=0.2, seed=0)
    assert s.shape == (501,)  # n_days + 1
    assert s[0] == 100.0
    assert (s > 0).all()


def test_roll_issuance_produces_aggregatable_outcomes():
    series = generate_realized_series(2000, mu=0.08, sigma=0.2, seed=1)
    outcomes = roll_issuance(series, NOTE, issuance_step_days=21)
    stats = aggregate(outcomes)
    assert stats.n_issuances > 10
    assert 0.0 <= stats.autocall_rate <= 1.0
    assert 0.0 <= stats.loss_rate <= 1.0


def test_bull_market_autocalls_more_than_bear():
    bull_series = generate_realized_series(3000, mu=0.20, sigma=0.18, seed=2)
    bear_series = generate_realized_series(3000, mu=-0.15, sigma=0.18, seed=2)
    bull = aggregate(roll_issuance(bull_series, NOTE))
    bear = aggregate(roll_issuance(bear_series, NOTE))
    assert bull.autocall_rate > bear.autocall_rate
    assert bear.loss_rate > bull.loss_rate  # downtrends breach the knock-in


def test_tail_return_is_no_better_than_the_mean():
    series = generate_realized_series(3000, mu=0.05, sigma=0.25, seed=3)
    stats = aggregate(roll_issuance(series, NOTE))
    assert stats.worst_5pct_return <= stats.mean_total_return


def test_aggregate_rejects_empty():
    with pytest.raises(ValueError, match="no issuances"):
        aggregate([])
