"""Tests for OIS Curve Construction."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from src.data_ingestion.market_data import get_ois_market_data, get_gsec_market_data
from src.curves.ois_curve import OISCurve, GSecCurve


@pytest.fixture
def ois_curve():
    data = get_ois_market_data()
    return OISCurve(data['tenor_years'].values, data['ois_rate'].values)


@pytest.fixture
def gsec_curve():
    data = get_gsec_market_data()
    return GSecCurve(data['tenor_years'].values, data['yield_rate'].values)


class TestOISCurve:
    """Test OIS curve bootstrapping and interpolation."""

    def test_df_at_zero_is_one(self, ois_curve):
        """DF(0) must equal 1.0."""
        assert ois_curve.df(0.0) == 1.0

    def test_df_monotonically_decreasing(self, ois_curve):
        """Discount factors must decrease with tenor."""
        tenors = np.linspace(0.01, 10.0, 50)
        dfs = ois_curve.df_array(tenors)
        assert np.all(np.diff(dfs) < 0), "DFs must be strictly decreasing"

    def test_df_positive(self, ois_curve):
        """All discount factors must be positive."""
        tenors = np.linspace(0.01, 10.0, 50)
        dfs = ois_curve.df_array(tenors)
        assert np.all(dfs > 0), "DFs must be positive"

    def test_zero_rates_positive(self, ois_curve):
        """Zero rates must be positive."""
        tenors = np.linspace(0.1, 10.0, 50)
        zeros = ois_curve.zero_rate_array(tenors)
        assert np.all(zeros > 0), "Zero rates must be positive"

    def test_forward_rate_positive(self, ois_curve):
        """Forward rates must be positive."""
        for t in np.arange(0.1, 9.0, 0.5):
            fwd = ois_curve.forward_rate(t, t + 0.5)
            assert fwd > 0, f"Forward rate at {t} must be positive"

    def test_forward_consistency(self, ois_curve):
        """Forward rates must be consistent with zero rates."""
        t1, t2 = 2.0, 5.0
        z1 = ois_curve.zero_rate(t1)
        z2 = ois_curve.zero_rate(t2)
        fwd = ois_curve.forward_rate(t1, t2)

        # Check: DF(t1) × DF(t1,t2) ≈ DF(t2)
        df1 = ois_curve.df(t1)
        df2 = ois_curve.df(t2)
        df_fwd = 1 / (1 + fwd * (t2 - t1))
        assert abs(df1 * df_fwd - df2) < 1e-6

    def test_shift_moves_rates(self, ois_curve):
        """Shifting the curve should change zero rates."""
        shifted = ois_curve.shift(100)  # +100bps
        z_base = ois_curve.zero_rate(5.0)
        z_shifted = shifted.zero_rate(5.0)
        assert z_shifted > z_base

    def test_bump_tenor(self, ois_curve):
        """Bumping a single tenor should only affect nearby rates."""
        bumped = ois_curve.bump_tenor(8, 10)  # Bump 1Y node by 10bps
        # The 1Y zero rate should change
        z_base_1y = ois_curve.zero_rate(1.0)
        z_bumped_1y = bumped.zero_rate(1.0)
        assert abs(z_bumped_1y - z_base_1y) > 1e-5

    def test_to_dataframe(self, ois_curve):
        """Curve should export to DataFrame correctly."""
        df = ois_curve.to_dataframe()
        assert 'tenor_years' in df.columns
        assert 'discount_factor' in df.columns
        assert len(df) == len(ois_curve.tenors)


class TestGSecCurve:
    """Test G-Sec yield curve."""

    def test_df_at_zero_is_one(self, gsec_curve):
        assert gsec_curve.df(0.0) == 1.0

    def test_gsec_above_ois(self, ois_curve, gsec_curve):
        """G-Sec yields should generally be above OIS rates (positive basis)."""
        for t in [2.0, 5.0, 10.0]:
            spread = gsec_curve.zero_rate(t) - ois_curve.zero_rate(t)
            assert spread >= 0, f"G-Sec should trade above OIS at {t}Y"

    def test_spread_computation(self, ois_curve, gsec_curve):
        """Spread computation should return positive values."""
        tenors = np.array([2.0, 5.0, 10.0])
        spreads = gsec_curve.spread_over_ois(ois_curve, tenors)
        assert np.all(spreads >= 0)

def test_survival_prob_100bps_5y():
    from src.xva.cva import CreditCurve
    # h = 0.01 / 0.60 = 0.016667; SP(5) = exp(-0.016667*5) = 0.9200 approx
    cc = CreditCurve(cds_spread_bps=100, recovery_rate=0.40)
    expected = np.exp(-cc.hazard_rate * 5.0)
    assert abs(cc.survival_probability(5.0) - expected) < 1e-10
    # Also verify the numeric value is in plausible range
    assert 0.90 < cc.survival_probability(5.0) < 0.95
