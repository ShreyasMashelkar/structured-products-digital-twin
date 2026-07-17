"""Realized-vol estimator recovers the generating vol of simulated GBM ticks."""

import numpy as np
import pytest

from spdt.analytics.realized_vol import TRADING_SECONDS_PER_YEAR, realized_vol


def _gbm_ticks(sigma, n=1800, dt_s=2.0, spot=24000.0, seed=11):
    rng = np.random.default_rng(seed)
    dt = dt_s / TRADING_SECONDS_PER_YEAR
    returns = sigma * np.sqrt(dt) * rng.standard_normal(n)
    spots = spot * np.exp(np.cumsum(returns))
    return [(i * dt_s, float(s)) for i, s in enumerate(spots)]


def test_recovers_generating_vol():
    for sigma in (0.10, 0.14, 0.25):
        rv = realized_vol(_gbm_ticks(sigma))
        assert rv == pytest.approx(sigma, rel=0.05)


def test_bad_prints_and_clock_skew_are_skipped():
    ticks = _gbm_ticks(0.14)
    ticks[100] = (ticks[100][0], 0.0)          # bad print
    ticks[200] = (ticks[199][0] - 1.0, ticks[200][1])  # clock skew
    rv = realized_vol(ticks)
    assert rv == pytest.approx(0.14, rel=0.06)


def test_too_few_samples_returns_none():
    assert realized_vol([]) is None
    assert realized_vol([(0.0, 100.0), (2.0, 100.1)]) is None
    assert realized_vol([(float(i), 100.0) for i in range(20)]) is None  # flat tape → no vol
