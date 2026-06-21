"""Tests for SA-CCR Regulatory Capital Module."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from src.sa_ccr.regulatory import (
    SACCRCalculator, compute_rwa, compute_capital_requirement, ALPHA
)


@pytest.fixture
def calculator():
    return SACCRCalculator()


class TestSACCR:
    """Test SA-CCR computations."""

    def test_maturity_bucket_short(self, calculator):
        assert calculator.maturity_bucket(0.5) == 'short'

    def test_maturity_bucket_medium(self, calculator):
        assert calculator.maturity_bucket(3.0) == 'medium'

    def test_maturity_bucket_long(self, calculator):
        assert calculator.maturity_bucket(7.0) == 'long'

    def test_supervisory_duration_positive(self, calculator):
        sd = calculator.supervisory_duration(0.0, 5.0)
        assert sd > 0

    def test_supervisory_duration_formula(self, calculator):
        """Verify the supervisory duration formula."""
        sd = calculator.supervisory_duration(0.0, 5.0)
        expected = (np.exp(-0.05 * 0) - np.exp(-0.05 * 5)) / 0.05
        assert abs(sd - expected) < 1e-10

    def test_maturity_factor_unmargined(self, calculator):
        """MF = sqrt(min(M, 1))."""
        mf = calculator.maturity_factor(0.5, margined=False)
        assert abs(mf - np.sqrt(0.5)) < 1e-10

        mf_1y = calculator.maturity_factor(1.0, margined=False)
        assert abs(mf_1y - 1.0) < 1e-10

        mf_5y = calculator.maturity_factor(5.0, margined=False)
        assert abs(mf_5y - 1.0) < 1e-10  # Capped at 1Y

    def test_trade_addon_positive(self, calculator):
        result = calculator.compute_trade_addon(
            notional=500, maturity=5.0, direction='Receive Fixed'
        )
        assert result['trade_addon'] > 0

    def test_delta_sign(self, calculator):
        recv = calculator.compute_trade_addon(
            500, 5.0, 'Receive Fixed'
        )
        pay = calculator.compute_trade_addon(
            500, 5.0, 'Pay Fixed'
        )
        assert recv['delta'] == 1.0
        assert pay['delta'] == -1.0

    def test_replacement_cost_unmargined(self, calculator):
        rc = calculator.compute_replacement_cost(
            mtm=10.0, collateral=0.0, margined=False
        )
        assert rc == 10.0

        rc_neg = calculator.compute_replacement_cost(
            mtm=-5.0, collateral=0.0, margined=False
        )
        assert rc_neg == 0.0

    def test_replacement_cost_margined(self, calculator):
        rc = calculator.compute_replacement_cost(
            mtm=10.0, collateral=8.0,
            threshold=1.0, mta=0.5, nica=0.0,
            margined=True
        )
        # max(10-8, 1+0.5-0, 0) = max(2, 1.5, 0) = 2.0
        assert abs(rc - 2.0) < 1e-10

    def test_ead_alpha_multiplier(self, calculator):
        """EAD should include alpha = 1.4 multiplier."""
        import pandas as pd
        trades = pd.DataFrame({
            'notional_cr': [500],
            'maturity_years': [5.0],
            'direction': ['Receive Fixed'],
        })
        result = calculator.compute_netting_set_ead(
            trades, mtm_total=5.0
        )
        expected_ead = ALPHA * (result['RC'] + result['PFE'])
        assert abs(result['EAD'] - expected_ead) < 1e-10

    def test_rwa_formula(self):
        """RWA = EAD × Risk Weight."""
        rwa = compute_rwa(100.0, 0.20)
        assert abs(rwa - 20.0) < 1e-10

    def test_capital_requirement(self):
        """Capital = RWA × 10.5%."""
        cap = compute_capital_requirement(100.0)
        assert abs(cap - 10.5) < 1e-10
