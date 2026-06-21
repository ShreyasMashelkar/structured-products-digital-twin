"""Tests for XVA Engines (CVA, FVA, KVA)."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from src.data_ingestion.market_data import get_ois_market_data
from src.curves.ois_curve import OISCurve
from src.xva.cva import CreditCurve, CVAEngine
from src.xva.fva import FVAEngine
from src.xva.kva import KVAEngine


@pytest.fixture
def ois_curve():
    data = get_ois_market_data()
    return OISCurve(data['tenor_years'].values, data['ois_rate'].values)


@pytest.fixture
def time_grid():
    return np.linspace(0, 5, 61)


@pytest.fixture
def ee_profile(time_grid):
    """Synthetic bell-shaped EE profile."""
    t = time_grid
    return 5.0 * np.sin(np.pi * t / 5.0) * np.exp(-0.1 * t)


@pytest.fixture
def ene_profile(time_grid):
    """Synthetic ENE profile (negative values)."""
    t = time_grid
    return -3.0 * np.sin(np.pi * t / 5.0) * np.exp(-0.1 * t)


class TestCreditCurve:
    """Test credit curve construction."""

    def test_hazard_rate_formula(self):
        """h = s / (1 - R)."""
        cc = CreditCurve(cds_spread_bps=50, recovery_rate=0.40)
        expected = 0.005 / 0.60
        assert abs(cc.hazard_rate - expected) < 1e-10

    def test_survival_at_zero_is_one(self):
        cc = CreditCurve(100)
        assert cc.survival_probability(0.0) == 1.0

    def test_survival_decreasing(self):
        cc = CreditCurve(100)
        sp1 = cc.survival_probability(1.0)
        sp5 = cc.survival_probability(5.0)
        assert sp5 < sp1

    def test_default_prob_consistent(self):
        """PD(0,T) = 1 - SP(T)."""
        cc = CreditCurve(200, 0.40)
        sp5 = cc.survival_probability(5.0)
        pd5 = cc.cumulative_default_probability(5.0)
        assert abs(sp5 + pd5 - 1.0) < 1e-10

    def test_marginal_pd_sums(self):
        """Sum of marginal PDs should equal cumulative PD."""
        cc = CreditCurve(150)
        total_pd = 0.0
        for i in range(5):
            total_pd += cc.default_probability(float(i), float(i + 1))
        cum_pd = cc.cumulative_default_probability(5.0)
        assert abs(total_pd - cum_pd) < 1e-10

    def test_higher_spread_higher_hazard(self):
        cc1 = CreditCurve(50)
        cc2 = CreditCurve(300)
        assert cc2.hazard_rate > cc1.hazard_rate

    def test_shift_increases_spread(self):
        cc = CreditCurve(100)
        shifted = cc.shift(50)
        assert shifted.hazard_rate > cc.hazard_rate


class TestTermStructureCreditCurve:
    """Test TermStructureCreditCurve construction and methods."""

    def test_term_structure_survival_higher_than_flat(self, ois_curve):
        """For a steep upward curve, survival prob at 5Y should be lower than flat 1Y curve."""
        from src.xva.cva import build_credit_curve_from_cds, CreditCurve
        
        tsc = build_credit_curve_from_cds(
            tenors=[1.0, 5.0],
            spreads_bps=[50.0, 150.0],
            recovery_rate=0.40,
            ois_curve=ois_curve
        )
        flat = CreditCurve(cds_spread_bps=50.0, recovery_rate=0.40)
        
        # Steep curve has much higher default risk later, so survival should be LOWER
        assert tsc.survival_probability(5.0) < flat.survival_probability(5.0)

    def test_shift_rebuilds_bootstrapper(self, ois_curve):
        from src.xva.cva import build_credit_curve_from_cds
        tsc = build_credit_curve_from_cds(
            tenors=[1.0, 5.0],
            spreads_bps=[50.0, 150.0],
            recovery_rate=0.40,
            ois_curve=ois_curve
        )
        shifted = tsc.shift(50.0)
        # Higher spread -> lower survival
        assert shifted.survival_probability(5.0) < tsc.survival_probability(5.0)


class TestCVAEngine:
    """Test CVA computation."""

    def test_cva_positive(self, ois_curve, ee_profile, time_grid):
        """CVA should be positive (it's a cost)."""
        engine = CVAEngine(ois_curve)
        cc = CreditCurve(100)
        cva = engine.compute_cva(ee_profile, time_grid, cc)
        assert cva > 0

    def test_higher_spread_higher_cva(self, ois_curve, ee_profile, time_grid):
        """Higher CDS spread → higher CVA."""
        engine = CVAEngine(ois_curve)
        cva_50 = engine.compute_cva(ee_profile, time_grid, CreditCurve(50))
        cva_300 = engine.compute_cva(ee_profile, time_grid, CreditCurve(300))
        assert cva_300 > cva_50

    def test_zero_ee_zero_cva(self, ois_curve, time_grid):
        """Zero exposure should give zero CVA."""
        engine = CVAEngine(ois_curve)
        zero_ee = np.zeros_like(time_grid)
        cva = engine.compute_cva(zero_ee, time_grid, CreditCurve(100))
        assert abs(cva) < 1e-12

    def test_dva_positive(self, ois_curve, ene_profile, time_grid):
        """DVA should be positive (it's a benefit)."""
        engine = CVAEngine(ois_curve)
        own_curve = CreditCurve(40)
        dva = engine.compute_dva(ene_profile, time_grid, own_curve)
        assert dva > 0

    def test_bilateral_cva(self, ois_curve, ee_profile, ene_profile, time_grid):
        """Bilateral CVA should be CVA - DVA."""
        engine = CVAEngine(ois_curve)
        result = engine.compute_bilateral_cva(
            ee_profile, ene_profile, time_grid,
            CreditCurve(100), CreditCurve(40)
        )
        assert abs(result['Bilateral_CVA'] -
                   (result['CVA'] - result['DVA'])) < 1e-10

    def test_cva_sensitivity_positive(self, ois_curve, ee_profile, time_grid):
        """CVA spread sensitivity should be positive."""
        engine = CVAEngine(ois_curve)
        sens = engine.cva_sensitivity(ee_profile, time_grid, CreditCurve(100))
        assert sens > 0

    def test_cva_numerical_value(self, ois_curve):
        # Flat 5Y exposure of 10 Cr, 100bps CDS, 40% recovery
        # Expected CVA ≈ LGD * integral(EE * h * DF dt) — verify order of magnitude
        time_grid = np.linspace(0, 5, 61)
        flat_ee = np.full_like(time_grid, 10.0)
        engine = CVAEngine(ois_curve)
        cva = engine.compute_cva(flat_ee, time_grid, CreditCurve(100, 0.40))
        # Rough check: CVA should be between 0.4 and 5 Cr for these inputs
        assert 0.4 < cva < 5.0

    def test_bootstrapped_vs_flat_cva(self, ois_curve):
        """
        Bootstrapped CreditCurve should differ from flat approximation
        when the CDS term structure is steep, and CVA values should differ.
        This test verifies that build_credit_curve_from_cds is actually
        doing something different from CreditCurve(flat_spread).
        """
        from src.xva.cva import build_credit_curve_from_cds
        
        # Steep upward CDS term structure (short end cheap, long end expensive)
        tenors = [1.0, 2.0, 3.0, 5.0, 7.0]
        spreads_steep = [50.0, 80.0, 120.0, 180.0, 250.0]
        
        bootstrapped = build_credit_curve_from_cds(
            tenors=tenors,
            spreads_bps=spreads_steep,
            recovery_rate=0.40,
            ois_curve=ois_curve
        )
        
        # Flat curve using only the 5Y spread (what the old code did)
        flat = CreditCurve(cds_spread_bps=180.0, recovery_rate=0.40)
        
        # The bootstrapped 5Y-equivalent hazard rate should differ from h=s/LGD
        flat_h = 180.0 / 10000.0 / 0.60
        assert abs(bootstrapped.hazard_rate - flat_h) > 1e-5, \
            "Bootstrapped hazard rate should differ from flat approximation"
        
        # CVA on a long-dated EE profile should differ between the two curves
        time_grid = np.linspace(0, 7, 85)
        ee = 10.0 * np.sin(np.pi * time_grid / 7.0) * np.exp(-0.05 * time_grid)
        engine = CVAEngine(ois_curve)
        
        cva_boot = engine.compute_cva(ee, time_grid, bootstrapped)
        cva_flat = engine.compute_cva(ee, time_grid, flat)
        
        # They should be in the same ballpark but not identical
        assert abs(cva_boot - cva_flat) / cva_flat > 0.01, \
            f"CVA difference should be > 1% for steep curve: boot={cva_boot:.4f} flat={cva_flat:.4f}"


class TestFVAEngine:
    """Test FVA computation."""

    def test_fca_negative(self, ois_curve, ee_profile, time_grid):
        """FCA should be negative (funding cost)."""
        engine = FVAEngine(ois_curve, funding_spread_bps=50)
        fca = engine.compute_fca(ee_profile, time_grid)
        assert fca < 0

    def test_fba_positive(self, ois_curve, ene_profile, time_grid):
        """FBA should be positive (funding benefit)."""
        engine = FVAEngine(ois_curve, funding_spread_bps=50)
        fba = engine.compute_fba(ene_profile, time_grid)
        assert fba > 0

    def test_fva_components(self, ois_curve, ee_profile, ene_profile, time_grid):
        """FVA should equal FCA + FBA."""
        engine = FVAEngine(ois_curve, funding_spread_bps=50)
        result = engine.compute_fva(ee_profile, ene_profile, time_grid)
        assert abs(result['FVA'] - (result['FCA'] + result['FBA'])) < 1e-10

    def test_wider_spread_larger_fca(self, ois_curve, ee_profile, time_grid):
        """Wider funding spread → larger FCA magnitude."""
        e1 = FVAEngine(ois_curve, funding_spread_bps=25)
        e2 = FVAEngine(ois_curve, funding_spread_bps=100)
        assert abs(e2.compute_fca(ee_profile, time_grid)) > \
               abs(e1.compute_fca(ee_profile, time_grid))


class TestKVAEngine:
    """Test KVA computation."""

    def test_kva_positive(self, ois_curve, ee_profile, time_grid):
        """KVA should be positive."""
        engine = KVAEngine(ois_curve)
        result = engine.compute_kva_from_exposure(
            ee_profile, time_grid, risk_weight=0.20
        )
        assert result['KVA'] > 0

    def test_higher_rw_higher_kva(self, ois_curve, ee_profile, time_grid):
        """Higher risk weight → higher KVA."""
        engine = KVAEngine(ois_curve)
        kva_20 = engine.compute_kva_from_exposure(
            ee_profile, time_grid, 0.20
        )['KVA']
        kva_100 = engine.compute_kva_from_exposure(
            ee_profile, time_grid, 1.00
        )['KVA']
        assert kva_100 > kva_20

    def test_zero_ee_zero_kva(self, ois_curve, time_grid):
        """Zero exposure should give zero KVA."""
        engine = KVAEngine(ois_curve)
        result = engine.compute_kva_from_exposure(
            np.zeros_like(time_grid), time_grid, 0.50
        )
        assert abs(result['KVA']) < 1e-12

    def test_kva_saccr_lower_than_alpha_proxy(self, ois_curve, time_grid):
        """KVA from SA-CCR should be lower than alpha proxy for heavily un-margined high EE trades."""
        engine = KVAEngine(ois_curve)
        
        # Artificial high EE profile vs low MTM
        high_ee = np.full_like(time_grid, 100.0)
        low_mtm = np.zeros_like(time_grid)
        
        res_proxy = engine.compute_kva_from_exposure(
            high_ee, time_grid, risk_weight=0.50
        )
        
        res_saccr = engine.compute_kva_from_saccr(
            time_grid=time_grid,
            notional=100.0,
            initial_maturity=5.0,
            direction='Receive Fixed',
            risk_weight=0.50,
            mtm_profile=low_mtm,
        )
        
        assert res_saccr['KVA'] <= res_proxy['KVA']


class TestMVAEngine:
    """Test MVA computation."""
    
    def test_simm_im_greater_than_zero(self, ois_curve):
        from src.xva.mva import MVAEngine
        engine = MVAEngine(ois_curve)
        im = engine.compute_simm_im({5.0: 1000.0})
        assert im > 0.0

    def test_simm_diversification(self, ois_curve):
        from src.xva.mva import MVAEngine
        engine = MVAEngine(ois_curve)
        
        dv01_same = {1.0: 1000.0, 5.0: 1000.0}
        dv01_opp = {1.0: 1000.0, 5.0: -1000.0}
        
        im_same = engine.compute_simm_im(dv01_same)
        im_opp = engine.compute_simm_im(dv01_opp)
        
        # Positive correlation means opposite signs hedge each other
        assert im_same > im_opp
