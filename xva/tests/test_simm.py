"""Tests for ISDA SIMM Calculator and MVA Engine V2."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from src.xva.simm import SIMMCalculator, MVAEngineV2
from src.data_ingestion.market_data import get_ois_market_data
from src.curves.ois_curve import OISCurve


@pytest.fixture
def ois_curve():
    data = get_ois_market_data()
    return OISCurve(data['tenor_years'].values, data['ois_rate'].values)


@pytest.fixture
def simm():
    return SIMMCalculator()


class TestSIMMCalculator:

    def test_single_bucket_equals_rw_times_sensitivity(self, simm):
        """
        For a single-bucket portfolio, IM = RW × |sensitivity|.
        This is the diagonal case of the correlation matrix.
        """
        sensitivity = 1_000_000  # ₹ 1M sensitivity at 5Y bucket
        result = simm.compute_im_rates_delta({'5Y': sensitivity})
        rw_5y = simm.RW_RATES['5Y']
        expected = rw_5y * sensitivity
        assert abs(result - expected) < 1.0  # Within ₹1 rounding

    def test_im_positive(self, simm):
        """IM must always be non-negative."""
        sensitivities = {'1Y': 500_000, '5Y': -800_000, '10Y': 200_000}
        result = simm.compute_im_rates_delta(sensitivities)
        assert result >= 0

    def test_empty_sensitivities_gives_zero(self, simm):
        """No sensitivities → zero IM."""
        assert simm.compute_im_rates_delta({}) == 0.0

    def test_opposite_signs_give_netting_benefit(self, simm):
        """
        Opposing sensitivities should give lower IM than summing absolute values.
        (Correlation between adjacent tenors < 1, so netting is partial.)
        """
        long_only  = simm.compute_im_rates_delta({'5Y': 1_000_000})
        short_only = simm.compute_im_rates_delta({'5Y': -1_000_000})
        net        = simm.compute_im_rates_delta({'5Y': 1_000_000, '10Y': -800_000})
        # Net should be less than sum of individual (partial netting via correlation)
        assert net < long_only + short_only

    def test_higher_sensitivity_higher_im(self, simm):
        """Doubling all sensitivities should double IM (linearity in RW)."""
        base = simm.compute_im_rates_delta({'5Y': 1_000_000})
        double = simm.compute_im_rates_delta({'5Y': 2_000_000})
        assert abs(double - 2 * base) < 1.0


class TestMVAEngineV2:

    def test_mva_positive(self, ois_curve):
        """MVA must be positive for positive IM profile."""
        engine = MVAEngineV2(funding_spread=0.015)
        time_grid = np.linspace(0, 5, 61)
        im_profile = np.linspace(1_000_000, 0, 61)  # Amortising IM
        dfs = np.array([ois_curve.df(t) for t in time_grid])
        mva = engine.compute_mva(time_grid, im_profile, dfs)
        assert mva > 0

    def test_mva_less_than_undiscounted(self, ois_curve):
        """MVA must be less than its undiscounted equivalent (discount factors < 1)."""
        engine = MVAEngineV2(funding_spread=0.015)
        time_grid = np.linspace(0, 5, 61)
        im_profile = np.linspace(1_000_000, 0, 61)
        dfs = np.array([ois_curve.df(t) for t in time_grid])
        mva = engine.compute_mva(time_grid, im_profile, dfs)
        # Undiscounted: funding_spread × integral(IM × dt)
        dt = np.diff(time_grid, prepend=0.0)
        undiscounted = engine.funding_spread * float(np.sum(im_profile * dt))
        assert mva < undiscounted

    def test_zero_im_zero_mva(self):
        """Zero IM profile → zero MVA."""
        engine = MVAEngineV2(funding_spread=0.015)
        time_grid = np.linspace(0, 5, 61)
        im_profile = np.zeros(61)
        dfs = np.ones(61)
        mva = engine.compute_mva(time_grid, im_profile, dfs)
        assert mva == 0.0

    def test_dim_profile_decreasing_to_zero(self):
        """DIM profile should reach zero at maturity."""
        engine = MVAEngineV2(funding_spread=0.015)
        time_grid = np.linspace(0, 5, 61)
        sensitivities = {'5Y': 2_000_000}
        im_profile = engine.estimate_dim_profile(5.0, time_grid, sensitivities)
        assert im_profile[-1] == 0.0 or im_profile[-1] < 1.0  # Zero at maturity

    def test_higher_funding_spread_higher_mva(self, ois_curve):
        """Higher funding spread → higher MVA."""
        time_grid = np.linspace(0, 5, 61)
        im_profile = np.linspace(1_000_000, 0, 61)
        dfs = np.array([ois_curve.df(t) for t in time_grid])
        mva_low  = MVAEngineV2(funding_spread=0.005).compute_mva(time_grid, im_profile, dfs)
        mva_high = MVAEngineV2(funding_spread=0.020).compute_mva(time_grid, im_profile, dfs)
        assert mva_high > mva_low
