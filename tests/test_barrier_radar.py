"""Closed-form barrier touch / terminal probabilities vs Monte Carlo on exact GBM paths."""

import numpy as np
import pytest

from spdt.analytics.barrier_radar import barrier_hit_probability, terminal_above_probability
from spdt.pricing.models.bs import BlackScholes

SPOT, R, Q, SIGMA, TAU = 24000.0, 0.065, 0.012, 0.14, 1.0


def _paths(n_paths=40_000, n_steps=800):
    model = BlackScholes(spot=SPOT, r=R, q=Q, sigma=SIGMA)
    times = np.linspace(0.0, TAU, n_steps + 1)
    rng = np.random.default_rng(7)
    return model.simulate(times, rng.standard_normal((n_paths, n_steps)))


def test_down_barrier_hit_probability_matches_mc():
    paths = _paths()
    for ki in (0.85, 0.70):
        barrier = ki * SPOT
        mc = float((paths.min(axis=1) <= barrier).mean())
        cf = barrier_hit_probability(SPOT, barrier, TAU, SIGMA, R, Q)
        # discrete monitoring under-counts touches, so MC sits slightly below closed form
        assert mc <= cf + 0.005
        assert cf == pytest.approx(mc, abs=0.02)


def test_up_barrier_hit_probability_matches_mc():
    paths = _paths()
    barrier = 1.10 * SPOT
    mc = float((paths.max(axis=1) >= barrier).mean())
    cf = barrier_hit_probability(SPOT, barrier, TAU, SIGMA, R, Q)
    assert cf == pytest.approx(mc, abs=0.02)


def test_terminal_above_probability_matches_mc():
    paths = _paths()
    level = 1.02 * SPOT
    mc = float((paths[:, -1] >= level).mean())
    cf = terminal_above_probability(SPOT, level, TAU, SIGMA, R, Q)
    assert cf == pytest.approx(mc, abs=0.01)


def test_degenerate_cases():
    assert barrier_hit_probability(SPOT, SPOT, TAU, SIGMA, R, Q) == 1.0
    assert barrier_hit_probability(SPOT, 0.7 * SPOT, 0.0, SIGMA, R, Q) == 0.0
    assert barrier_hit_probability(SPOT, 0.01 * SPOT, TAU, SIGMA, R, Q) < 1e-6
    assert terminal_above_probability(SPOT, 0.9 * SPOT, 0.0, SIGMA, R, Q) == 1.0
    assert terminal_above_probability(SPOT, 1.1 * SPOT, 0.0, SIGMA, R, Q) == 0.0
