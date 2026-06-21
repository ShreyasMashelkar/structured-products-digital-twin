"""
Tests for all gap-closing modules (Gaps 1–10).

Covers:
    - FRTB-CVA SA-CVA engine         (Gap 1)
    - Hull-White 2-Factor model      (Gap 2)
    - SIMM FX + Equity + Multi-class (Gap 3)
    - CTD optionality engine         (Gap 4)
    - Gaussian copula WWR            (Gap 5)
    - CVA Greeks: cs01, ir01, grid   (Gap 6)
    - Vectorised ops                 (Gap 8)
    - Credit-contingent CVA          (Gap 9)
    - CCIL tenor-specific DIM        (Gap 10)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
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
def ee_profile(time_grid):
    t = time_grid
    return 5.0 * np.sin(np.pi * t / 5.0) * np.exp(-0.1 * t)

@pytest.fixture
def ene_profile(time_grid):
    t = time_grid
    return -3.0 * np.sin(np.pi * t / 5.0) * np.exp(-0.1 * t)


# ── FRTB-CVA (Gap 1) ─────────────────────────────────────────────────────────

class TestFRTBCVA:

    def test_sa_cva_capital_positive(self):
        from src.sa_ccr.frtb_cva import FRTBCVAEngine
        engine = FRTBCVAEngine()
        result = engine.compute_sa_cva_capital(
            {'HDFC': 0.002, 'SBI': 0.001},
            {'HDFC': 'AA',  'SBI': 'AAA'},
        )
        assert result['K_CS_delta']          >= 0
        assert result['FRTB_CVA_Capital_CR'] >= 0

    def test_higher_cs01_higher_capital(self):
        from src.sa_ccr.frtb_cva import FRTBCVAEngine
        engine = FRTBCVAEngine()
        low  = engine.compute_sa_cva_capital({'X': 0.001}, {'X': 'AA'})
        high = engine.compute_sa_cva_capital({'X': 0.010}, {'X': 'AA'})
        assert high['K_CS_delta'] > low['K_CS_delta']

    def test_lower_rating_higher_rw(self):
        from src.sa_ccr.frtb_cva import _get_cs_rw
        assert _get_cs_rw('BBB') > _get_cs_rw('AA')

    def test_ir_delta_non_negative(self):
        from src.sa_ccr.frtb_cva import FRTBCVAEngine
        engine = FRTBCVAEngine()
        result = engine.compute_ir_delta_capital(
            {'HDFC': {'short': 0.001, 'medium': 0.005, 'long': 0.002}}
        )
        assert result['K_IR_delta'] >= 0

    def test_from_eod_report(self):
        import pandas as pd
        from src.sa_ccr.frtb_cva import FRTBCVAEngine
        engine = FRTBCVAEngine()
        df     = pd.DataFrame({
            'Counterparty': ['HDFC', 'SBI'],
            'Rating':       ['AA',   'AAA'],
            'CVA_CR':       [0.002,  0.0008],
            'CDS_BPS':      [60.0,   50.0],
            'EE_5Y_CR':     [5.0,    30.0],
            'EPE_CR':       [4.0,    28.0],
        })
        result = engine.compute_from_eod_report(df)
        assert len(result) == 2
        assert 'FRTB_CVA_Capital_CR' in result.columns
        assert (result['FRTB_CVA_Capital_CR'] >= 0).all()


# ── HW2F (Gap 2) ─────────────────────────────────────────────────────────────

class TestHullWhite2F:

    def test_simulation_shape(self, ois_curve):
        from src.montecarlo.hull_white_2f import HullWhite2F
        model  = HullWhite2F(ois_curve)
        result = model.simulate(n_paths=100, n_steps=12, horizon=2.0, seed=42)
        assert result['rate_paths'].shape == (100, 13)
        assert result['x_paths'].shape    == (100, 13)
        assert result['y_paths'].shape    == (100, 13)

    def test_initial_rate_near_forward(self, ois_curve):
        from src.montecarlo.hull_white_2f import HullWhite2F
        model  = HullWhite2F(ois_curve)
        result = model.simulate(n_paths=500, n_steps=24, horizon=5.0, seed=1)
        mean_r0 = float(np.mean(result['rate_paths'][:, 0]))
        f0      = ois_curve.instantaneous_forward(1/365)
        assert abs(mean_r0 - f0) < 0.005

    def test_rates_mostly_positive(self, ois_curve):
        from src.montecarlo.hull_white_2f import HullWhite2F
        model  = HullWhite2F(ois_curve)
        result = model.simulate(n_paths=500, n_steps=60, horizon=10.0, seed=99)
        assert float(np.mean(result['rate_paths'] < 0)) < 0.05

    def test_a_b_must_differ(self, ois_curve):
        from src.montecarlo.hull_white_2f import HullWhite2F
        with pytest.raises(ValueError):
            HullWhite2F(ois_curve, a=0.10, b=0.10)

    def test_calibrate_from_rbi(self, ois_curve):
        from src.montecarlo.hull_white_2f import calibrate_hw2f_from_rbi_dbie
        model = calibrate_hw2f_from_rbi_dbie(ois_curve)
        assert model.a > model.b
        assert 0.001 <= model.sigma1 <= 0.05
        assert 0.001 <= model.sigma2 <= 0.05
        assert 0.0   <  model.rho    <  1.0

    def test_swap_mtm_shape(self, ois_curve):
        from src.montecarlo.hull_white_2f import HullWhite2F
        model  = HullWhite2F(ois_curve)
        result = model.simulate(n_paths=50, n_steps=20, horizon=5.0, seed=7)
        mtm    = model.compute_swap_mtm_paths(
            result['time_grid'], result['x_paths'], result['y_paths'],
            notional=500.0, fixed_rate=0.07, swap_maturity=5.0,
        )
        assert mtm.shape == (50, 21)

    def test_zcb_price_in_unit_interval(self, ois_curve):
        from src.montecarlo.hull_white_2f import HullWhite2F
        model = HullWhite2F(ois_curve)
        x = np.zeros(10)
        y = np.zeros(10)
        p = model.zero_coupon_bond_price(0.0, 5.0, x, y)
        assert np.all(p > 0) and np.all(p < 1)


# ── SIMM Extensions (Gap 3) ───────────────────────────────────────────────────

class TestSIMMExtensions:

    def test_fx_im_positive(self):
        from src.xva.simm import SIMMFXDeltaCalculator
        calc = SIMMFXDeltaCalculator()
        assert calc.compute_fx_delta_im({'USD/INR': 50_000_000}) > 0

    def test_cat1_cat2_higher_than_cat1_cat1(self):
        from src.xva.simm import SIMMFXDeltaCalculator
        calc  = SIMMFXDeltaCalculator()
        im_12 = calc.compute_fx_delta_im({'USD/INR': 1_000_000})
        im_11 = calc.compute_fx_delta_im({'EUR/USD': 1_000_000})
        assert im_12 > im_11

    def test_equity_im_positive(self):
        from src.xva.simm import SIMMEquityDeltaCalculator
        calc = SIMMEquityDeltaCalculator()
        assert calc.compute_equity_delta_im({4: 10_000_000, 8: 5_000_000}) > 0

    def test_multi_class_exceeds_single_class(self):
        from src.xva.simm import SIMMMultiClassCalculator
        calc   = SIMMMultiClassCalculator()
        result = calc.compute_total_im(
            ir_sensitivities={'5Y': 2_000_000},
            fx_sensitivities={'USD/INR': 5_000_000},
            equity_sensitivities={4: 1_000_000},
        )
        assert result['IM_Total'] > 0
        assert result['IM_Total'] >= max(
            result['IM_IR'], result['IM_FX'], result['IM_EQ']
        )

    def test_zero_inputs_zero_im(self):
        from src.xva.simm import SIMMMultiClassCalculator
        result = SIMMMultiClassCalculator().compute_total_im()
        assert result['IM_Total'] == 0.0


# ── CTD Optionality (Gap 4) ───────────────────────────────────────────────────

class TestCTDOptionality:

    def test_ctd_is_minimum_carry(self):
        from src.csa.ctd_optionality import CTDEngine, get_standard_rbi_collateral_set
        engine = CTDEngine(ois_rate=0.068)
        assets = get_standard_rbi_collateral_set()
        result = engine.find_ctd(assets, repo_rate=0.065)
        min_cost = min(a['net_carry_cost'] for a in result['all_assets'])
        assert abs(result['ctd_asset']['net_carry_cost'] - min_cost) < 1e-10

    def test_optionality_spread_non_negative(self):
        from src.csa.ctd_optionality import CTDEngine, get_standard_rbi_collateral_set
        engine = CTDEngine(0.068)
        result = engine.find_ctd(get_standard_rbi_collateral_set(), 0.065)
        assert result['ctd_optionality_spread_bps'] >= 0

    def test_ctd_fva_non_negative(self, ois_curve, time_grid, ee_profile):
        from src.csa.ctd_optionality import CTDEngine, get_standard_rbi_collateral_set
        engine = CTDEngine(0.068)
        result = engine.ctd_adjusted_fva(
            ee_profile, time_grid, get_standard_rbi_collateral_set(), 0.065, ois_curve
        )
        assert result['CTD_FVA'] >= 0


# ── Gaussian Copula WWR (Gap 5) ───────────────────────────────────────────────

class TestGaussianCopulaWWR:

    def test_default_times_shape(self, ois_curve):
        from src.wwr.gaussian_copula_wwr import GaussianCopulaWWR
        from src.xva.cva import CreditCurve
        model  = GaussianCopulaWWR(ois_curve, n_paths=500, seed=42)
        result = model.simulate_correlated_defaults(
            ['HDFC','SBI'], [CreditCurve(60), CreditCurve(50)],
            ['Private_Bank','PSU_Bank'], horizon=5.0, n_time_steps=20,
        )
        assert result['default_times'].shape == (500, 2)

    def test_corr_matrix_valid(self):
        from src.wwr.gaussian_copula_wwr import build_empirical_correlation_matrix
        C = build_empirical_correlation_matrix(
            ['Private_Bank','PSU_Bank','NBFC','Corporate_IG']
        )
        assert C.shape == (4, 4)
        assert np.allclose(np.diag(C), 1.0)
        assert (C >= 0).all() and (C <= 1.0 + 1e-10).all()

    def test_portfolio_cva_non_negative(self, ois_curve, time_grid, ee_profile):
        from src.wwr.gaussian_copula_wwr import GaussianCopulaWWR
        from src.xva.cva import CreditCurve
        model  = GaussianCopulaWWR(ois_curve, n_paths=200, seed=7)
        result = model.compute_portfolio_cva_copula(
            ['HDFC','SBI'], [CreditCurve(60), CreditCurve(50)],
            ['Private_Bank','PSU_Bank'],
            [ee_profile, ee_profile * 5], time_grid,
        )
        assert result['portfolio_cva_copula'] >= 0
        assert result['sum_standalone_cva']   >= 0


# ── CVA Greeks (Gap 6) ───────────────────────────────────────────────────────

class TestCVAGreeks:

    def test_cs01_positive(self, ois_curve, time_grid, ee_profile):
        from src.xva.cva import CVAEngine, CreditCurve
        engine = CVAEngine(ois_curve)
        assert engine.cs01(ee_profile, time_grid, CreditCurve(80.0)) > 0

    def test_ir01_negative(self, ois_curve, time_grid, ee_profile):
        from src.xva.cva import CVAEngine, CreditCurve
        engine = CVAEngine(ois_curve)
        assert engine.ir01(ee_profile, time_grid, CreditCurve(80.0)) < 0

    def test_sensitivity_grid_keys(self, ois_curve, time_grid, ee_profile, ene_profile):
        from src.xva.cva import CVAEngine, CreditCurve
        engine = CVAEngine(ois_curve)
        grid   = engine.cva_sensitivity_grid(
            ee_profile, ene_profile, time_grid,
            CreditCurve(80.0), CreditCurve(40.0)
        )
        for key in ['CVA','DVA','CS01_CVA','CS01_DVA',
                    'IR01_CVA','IR01_DVA','CDS_Gamma']:
            assert key in grid

    def test_cds_gamma_small(self, ois_curve, time_grid, ee_profile, ene_profile):
        from src.xva.cva import CVAEngine, CreditCurve
        engine = CVAEngine(ois_curve)
        grid   = engine.cva_sensitivity_grid(
            ee_profile, ene_profile, time_grid,
            CreditCurve(80.0), CreditCurve(40.0)
        )
        # Gamma should be much smaller in magnitude than CVA
        assert abs(grid['CDS_Gamma']) < abs(grid['CVA']) * 0.1


# ── Vectorised Ops (Gap 8) ────────────────────────────────────────────────────

class TestVectorisedOps:

    def test_cva_matches_loop_engine(self, ois_curve, time_grid, ee_profile):
        from src.utils.vectorised_ops import vectorised_cva
        from src.xva.cva import CVAEngine, CreditCurve
        curve    = CreditCurve(80.0, 0.40)
        cva_loop = CVAEngine(ois_curve).compute_cva(ee_profile, time_grid, curve)
        dfs      = np.array([ois_curve.df(t) for t in time_grid])
        cva_vec  = vectorised_cva(ee_profile, time_grid,
                                   curve.hazard_rate, 1-curve.recovery_rate, dfs)
        assert abs(cva_vec - cva_loop) / (abs(cva_loop) + 1e-10) < 0.02

    def test_exposure_metrics_match_numpy(self, time_grid):
        from src.utils.vectorised_ops import vectorised_exposure_metrics
        paths  = np.random.default_rng(42).normal(2.0, 3.0, (200, len(time_grid)))
        result = vectorised_exposure_metrics(paths, time_grid)
        assert np.allclose(result['EE'], np.mean(np.maximum(paths, 0.0), axis=0))
        assert result['EPE'] > 0

    def test_antithetic_pairs_are_negatives(self):
        from src.utils.vectorised_ops import antithetic_variates
        Z = antithetic_variates(np.random.default_rng(1), (100, 20))
        assert Z.shape == (100, 20)
        assert np.allclose(Z[:50], -Z[50:])

    def test_bilateral_symmetry(self, time_grid):
        from src.utils.vectorised_ops import vectorised_bilateral_cva
        dfs    = np.ones(len(time_grid))
        ee     =  5.0 * np.sin(np.pi * time_grid / 5.0) * np.exp(-0.1 * time_grid)
        ene    = -3.0 * np.sin(np.pi * time_grid / 5.0) * np.exp(-0.1 * time_grid)
        result = vectorised_bilateral_cva(ee, ene, time_grid, 0.02, 0.01, 0.6, 0.6, dfs)
        assert result['CVA'] > 0
        assert result['DVA'] > 0
        assert abs(result['Bilateral_CVA'] - (result['CVA'] - result['DVA'])) < 1e-10


# ── CCIL DIM (Gap 10) ────────────────────────────────────────────────────────

class TestCCILDIM:

    def test_dim_shape(self, time_grid):
        from src.data_ingestion.ccil_data import compute_tenor_specific_dim
        dim = compute_tenor_specific_dim(5.0, time_grid, {'1Y': 0.01, '5Y': 0.05})
        assert dim.shape == time_grid.shape

    def test_dim_zero_at_maturity(self, time_grid):
        from src.data_ingestion.ccil_data import compute_tenor_specific_dim
        dim = compute_tenor_specific_dim(5.0, time_grid, {'5Y': 0.05})
        assert dim[-1] == 0.0

    def test_dim_non_negative(self, time_grid):
        from src.data_ingestion.ccil_data import compute_tenor_specific_dim
        dim = compute_tenor_specific_dim(5.0, time_grid, {'1Y': 0.02, '5Y': 0.06})
        assert np.all(dim >= 0)

    def test_vol_structure_monotone(self):
        from src.data_ingestion.ccil_data import CCILDataFetcher
        vols = CCILDataFetcher().get_tenor_specific_vol()
        assert vols['1Y'] > vols['10Y']

    def test_credit_contingent_hedge_notional(self, ois_curve, time_grid, ee_profile):
        from src.xva.credit_contingent import CDSHedgeEngine
        from src.xva.cva import CreditCurve
        engine = CDSHedgeEngine(ois_curve)
        result = engine.compute_cds_hedge_notional(ee_profile, time_grid,
                                                    CreditCurve(80.0), 5.0)
        assert result['hedge_notional_cr']  >= 0
        assert result['cs01_cva_cr_per_bp'] >  0

    def test_hedge_effectiveness_in_range(self, ois_curve):
        from src.xva.credit_contingent import CDSHedgeEngine
        engine = CDSHedgeEngine(ois_curve)
        result = engine.hedge_effectiveness('NBFC', cva_vol=0.5)
        assert 0.0 <= result['effectiveness'] <= 1.0
