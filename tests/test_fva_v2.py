"""Tests for Pathwise FVA Engine V2."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from src.xva.fva_v2 import FVAEngineV2
from src.data_ingestion.market_data import get_ois_market_data
from src.curves.ois_curve import OISCurve


@pytest.fixture
def ois_curve():
    data = get_ois_market_data()
    return OISCurve(data['tenor_years'].values, data['ois_rate'].values)


@pytest.fixture
def time_grid():
    return np.linspace(0, 5, 61)


@pytest.fixture
def positive_npv_paths(time_grid):
    """All-positive NPV paths — should give positive FCA, zero FBA."""
    n_paths = 200
    rng = np.random.default_rng(42)
    return np.abs(rng.normal(5.0, 1.0, (n_paths, len(time_grid))))


@pytest.fixture
def negative_npv_paths(time_grid):
    """All-negative NPV paths — should give zero FCA, positive FBA."""
    n_paths = 200
    rng = np.random.default_rng(42)
    return -np.abs(rng.normal(5.0, 1.0, (n_paths, len(time_grid))))


class TestFVAEngineV2:

    def test_fca_positive_for_positive_npv(self, time_grid, positive_npv_paths, ois_curve):
        """FCA must be positive when all NPVs are positive (we fund receivables)."""
        dfs = np.array([ois_curve.df(t) for t in time_grid])
        engine = FVAEngineV2(funding_spread_borrow=0.015, funding_spread_lend=0.005)
        result = engine.compute_fva_pathwise(time_grid, positive_npv_paths, dfs)
        assert result['FCA'] > 0
        assert result['FBA'] == pytest.approx(0.0, abs=1e-6)

    def test_fba_positive_for_negative_npv(self, time_grid, negative_npv_paths, ois_curve):
        """FBA must be positive when all NPVs are negative (we have funding benefit)."""
        dfs = np.array([ois_curve.df(t) for t in time_grid])
        engine = FVAEngineV2(funding_spread_borrow=0.015, funding_spread_lend=0.005)
        result = engine.compute_fva_pathwise(time_grid, negative_npv_paths, dfs)
        assert result['FBA'] > 0
        assert result['FCA'] == pytest.approx(0.0, abs=1e-6)

    def test_fva_equals_fca_minus_fba(self, time_grid, ois_curve):
        """FVA = FCA - FBA must hold algebraically."""
        rng = np.random.default_rng(99)
        npv_paths = rng.normal(2.0, 3.0, (100, len(time_grid)))
        dfs = np.array([ois_curve.df(t) for t in time_grid])
        engine = FVAEngineV2()
        result = engine.compute_fva_pathwise(time_grid, npv_paths, dfs)
        assert abs(result['FVA'] - (result['FCA'] - result['FBA'])) < 1e-10

    def test_higher_borrow_spread_higher_fca(self, time_grid, positive_npv_paths, ois_curve):
        """Higher borrow spread → higher FCA."""
        dfs = np.array([ois_curve.df(t) for t in time_grid])
        engine_low  = FVAEngineV2(funding_spread_borrow=0.005, funding_spread_lend=0.002)
        engine_high = FVAEngineV2(funding_spread_borrow=0.020, funding_spread_lend=0.002)
        fca_low  = engine_low.compute_fva_pathwise(time_grid, positive_npv_paths, dfs)['FCA']
        fca_high = engine_high.compute_fva_pathwise(time_grid, positive_npv_paths, dfs)['FCA']
        assert fca_high > fca_low

    def test_zero_npv_zero_fva(self, time_grid, ois_curve):
        """Zero NPV paths → zero FVA."""
        dfs = np.array([ois_curve.df(t) for t in time_grid])
        engine = FVAEngineV2()
        npv_paths = np.zeros((50, len(time_grid)))
        result = engine.compute_fva_pathwise(time_grid, npv_paths, dfs)
        assert result['FVA'] == pytest.approx(0.0, abs=1e-10)
        assert result['FCA'] == pytest.approx(0.0, abs=1e-10)
        assert result['FBA'] == pytest.approx(0.0, abs=1e-10)
