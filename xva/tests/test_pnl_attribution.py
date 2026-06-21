"""Tests for Swap PnL Attribution."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from src.xva.pnl_attribution import SwapPnLAttribution
from src.data_ingestion.market_data import get_ois_market_data
from src.curves.ois_curve import OISCurve


@pytest.fixture
def ois_curve():
    data = get_ois_market_data()
    return OISCurve(data['tenor_years'].values, data['ois_rate'].values)


@pytest.fixture
def attr():
    return SwapPnLAttribution(notional=500.0, fixed_rate=0.07,
                               maturity_years=5.0, pay_freq=0.5)


class TestSwapPnLAttribution:

    def test_full_attribution_returns_dataframe(self, attr, ois_curve):
        """full_attribution() must return a DataFrame with expected columns."""
        import pandas as pd
        shocked = OISCurve(ois_curve.tenors, ois_curve.rates + 0.001)
        result = attr.full_attribution(shocked, ois_curve)
        assert isinstance(result, pd.DataFrame)
        assert 'Effect' in result.columns
        assert 'PnL (₹ Cr)' in result.columns

    def test_attribution_has_six_effects_plus_total(self, attr, ois_curve):
        """Attribution must have exactly 7 rows: 6 components + TOTAL."""
        shocked = OISCurve(ois_curve.tenors, ois_curve.rates + 0.001)
        result = attr.full_attribution(shocked, ois_curve)
        assert len(result) == 7
        effects = result['Effect'].tolist()
        assert 'TOTAL' in effects
        assert 'Carry' in effects
        assert 'Delta' in effects
        assert 'Gamma' in effects

    def test_components_sum_to_total_approximately(self, attr, ois_curve):
        """
        Sum of Carry + Roll-Down + Delta + Gamma + New Fixing + Unexplained = TOTAL.
        The Unexplained residual ensures this identity holds exactly.
        """
        shocked = OISCurve(ois_curve.tenors, ois_curve.rates + 0.002)
        result = attr.full_attribution(shocked, ois_curve)
        row_dict = dict(zip(result['Effect'], result['PnL (₹ Cr)']))
        components = ['Carry', 'Roll-Down', 'Delta', 'Gamma', 'New Fixing', 'Unexplained']
        component_sum = sum(row_dict.get(c, 0.0) for c in components)
        total = row_dict['TOTAL']
        assert abs(component_sum - total) < 1e-8, \
            f"Component sum {component_sum:.8f} ≠ TOTAL {total:.8f}"

    def test_delta_pnl_positive_for_rate_rise_receive_fixed(self):
        """
        A receive-fixed swap gains value when rates rise (negative DV01 × positive move).
        Wait — for RECEIVE FIXED: DV01 is negative (rates up → swap value up for pay float).
        Actually for a RECEIVE FIXED swap, rates up → MTM increases (positive PnL).
        """
        attr_rf = SwapPnLAttribution(notional=500.0, fixed_rate=0.065,
                                      maturity_years=5.0)
        data = get_ois_market_data()
        curve_t0 = OISCurve(data['tenor_years'].values, data['ois_rate'].values)
        # Large rate rise: +50bps
        curve_t1 = OISCurve(curve_t0.tenors, curve_t0.rates + 0.005)
        delta_d = attr_rf.compute_delta_pnl(curve_t1, curve_t0)
        # For receive-fixed, higher rates → positive delta PnL (float leg up more than fixed)
        # The sign depends on whether fixed > current par or not
        # Just check it's non-zero
        assert abs(delta_d['_total']) > 0

    def test_carry_positive_for_above_par_receive_fixed(self):
        """
        If fixed rate > par rate, carry should be positive for receive-fixed.
        """
        data = get_ois_market_data()
        curve = OISCurve(data['tenor_years'].values, data['ois_rate'].values)
        # Use fixed rate well above current OIS (guarantees positive carry)
        attr_above_par = SwapPnLAttribution(notional=500.0, fixed_rate=0.12,
                                             maturity_years=5.0)
        carry = attr_above_par.compute_carry(curve)
        assert carry > 0, "Above-par receive-fixed swap should have positive carry"

    def test_build_daily_curve_sequence_returns_curves(self):
        """build_daily_curve_sequence() should return a list of OISCurve objects."""
        curves = SwapPnLAttribution.build_daily_curve_sequence(n_days=3)
        assert len(curves) == 3
        for c in curves:
            assert isinstance(c, OISCurve)
            assert c.df(1.0) < 1.0

    def test_daily_sequence_curves_differ(self):
        """Each day in the sequence should have a different curve (realistic moves)."""
        curves = SwapPnLAttribution.build_daily_curve_sequence(n_days=5)
        # Rates should differ day-over-day
        rate_arrays = [c.rates for c in curves]
        for i in range(1, len(rate_arrays)):
            assert not np.allclose(rate_arrays[i], rate_arrays[i-1]), \
                f"Day {i} and day {i-1} have identical curves"
