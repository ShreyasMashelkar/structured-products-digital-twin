"""Tests for Stress Testing Module."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from src.data_ingestion.market_data import get_ois_market_data
from src.curves.ois_curve import OISCurve
from src.pricing.swap_pricer import SwapPricer
from src.stress.stress_testing import shock_curve, stress_test_swap


@pytest.fixture
def ois_curve():
    data = get_ois_market_data()
    return OISCurve(data['tenor_years'].values, data['ois_rate'].values)


class TestStressTesting:
    """Test stress testing module."""

    def test_shock_curve_identity(self, ois_curve):
        """Zero shock should return same rates."""
        shocked = shock_curve(ois_curve, 0.0)
        np.testing.assert_array_almost_equal(
            ois_curve.rates, shocked.rates
        )

    def test_shock_curve_direction(self, ois_curve):
        """Positive shock should raise rates."""
        shocked = shock_curve(ois_curve, 100)
        assert np.all(shocked.rates > ois_curve.rates)

    def test_receive_fixed_rate_up(self, ois_curve):
        """Receive fixed swap MTM should decrease when rates rise."""
        swap = SwapPricer(500.0, 0.07, 5.0, 'Receive Fixed')
        base_mtm = swap.mtm(ois_curve)
        shocked_mtm = swap.mtm(shock_curve(ois_curve, 100))

        # Receive fixed: rates up → float leg PV up → MTM down
        assert shocked_mtm < base_mtm

    def test_pay_fixed_rate_up(self, ois_curve):
        """Pay fixed swap MTM should increase when rates rise."""
        swap = SwapPricer(500.0, 0.07, 5.0, 'Pay Fixed')
        base_mtm = swap.mtm(ois_curve)
        shocked_mtm = swap.mtm(shock_curve(ois_curve, 100))

        assert shocked_mtm > base_mtm

    def test_stress_test_swap_returns_dataframe(self, ois_curve):
        """Stress test should return correct DataFrame."""
        swap = SwapPricer(500.0, 0.07, 5.0, 'Receive Fixed')
        shocks = [-100, 0, 100, 200]
        result = stress_test_swap(swap, ois_curve, shocks)

        assert len(result) == len(shocks)
        assert 'MTM_cr' in result.columns
        assert 'MTM_change_cr' in result.columns

    def test_base_scenario_zero_change(self, ois_curve):
        """Base scenario (0 shock) should have zero MTM change."""
        swap = SwapPricer(500.0, 0.07, 5.0, 'Receive Fixed')
        result = stress_test_swap(swap, ois_curve, [0])
        assert abs(result.iloc[0]['MTM_change_cr']) < 1e-10
