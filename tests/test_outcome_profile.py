"""Tests for the client-facing outcome profile — forward MC over any DSL product.

Generic over the payoff DSL: per-path cashflow totals give the return distribution, last
payment time gives the life/autocall split. Checked against products whose outcomes are
known by construction.
"""

import pytest

from spdt.outcomes import outcome_profile
from spdt.pricing.models import BlackScholes
from spdt.products import Autocallable, BarrierReverseConvertible, CapitalProtectedNote

_MODEL = BlackScholes(spot=100.0, sigma=0.20, r=0.06, q=0.01)
_OBS = (0.5, 1.0)


def test_fully_protected_note_never_loses_capital():
    note = CapitalProtectedNote(100.0, 1.0, 1.0, 1.0, 1.0, None, initial_fixing=100.0)
    profile = outcome_profile(note, _MODEL, n_paths=4_000, seed=1)
    assert profile["prob_loss_pct"] == 0.0
    assert profile["prob_autocall_pct"] == 0.0  # nothing to autocall
    assert profile["median_life_years"] == 1.0


def test_certain_autocall_redeems_at_first_observation():
    # Autocall level far below spot → every path autocalls at the first observation.
    note = Autocallable(100.0, _OBS, 0.02, 0.01, 0.0, 0.0, False, initial_fixing=100.0)
    profile = outcome_profile(note, _MODEL, n_paths=2_000, seed=2)
    assert profile["prob_autocall_pct"] == 100.0
    assert profile["median_life_years"] == 0.5
    assert profile["autocall_by_period"][0]["prob_pct"] == 100.0


def test_deep_barrier_brc_rarely_loses_and_shallow_often_does():
    deep = BarrierReverseConvertible(100.0, _OBS, 0.06, 1.0, 0.05, initial_fixing=100.0)
    shallow = BarrierReverseConvertible(100.0, _OBS, 0.06, 1.0, 0.95, initial_fixing=100.0)
    p_deep = outcome_profile(deep, _MODEL, n_paths=4_000, seed=3)
    p_shallow = outcome_profile(shallow, _MODEL, n_paths=4_000, seed=3)
    assert p_deep["prob_loss_pct"] < 1.0
    assert p_shallow["prob_loss_pct"] > 20.0
    assert p_shallow["p5_return_pct"] < p_deep["p5_return_pct"]


def test_profile_shape_and_consistency():
    note = Autocallable(100.0, _OBS, 0.02, 1.0, 0.7, 0.6, True, initial_fixing=100.0)
    profile = outcome_profile(note, _MODEL, n_paths=4_000, seed=4)
    for key in ("prob_autocall_pct", "prob_loss_pct", "mean_return_pa_pct",
                "median_return_pct", "p5_return_pct", "p95_return_pct",
                "median_life_years", "autocall_by_period", "n_paths"):
        assert key in profile
    assert 0.0 <= profile["prob_autocall_pct"] <= 100.0
    assert 0.0 <= profile["prob_loss_pct"] <= 100.0
    assert profile["p5_return_pct"] <= profile["median_return_pct"] <= profile["p95_return_pct"]
    by_period = profile["autocall_by_period"]
    assert [row["time"] for row in by_period] == [0.5, 1.0]
    total_autocall = sum(row["prob_pct"] for row in by_period)
    assert total_autocall == pytest.approx(profile["prob_autocall_pct"], abs=0.01)
