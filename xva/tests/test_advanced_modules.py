"""
Tests for the advanced quant modules (AAD, QMC, LSM, FX-XVA, stochastic WWR,
BA-CVA / SA-CVA vega, exposure backtesting, IFRS 13).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from src.data_ingestion.market_data import get_ois_market_data
from src.curves.ois_curve import OISCurve
from src.xva.cva import CVAEngine, CreditCurve


@pytest.fixture
def ois_curve():
    d = get_ois_market_data()
    return OISCurve(d['tenor_years'].values, d['ois_rate'].values)

@pytest.fixture
def time_grid():
    return np.linspace(0, 5, 61)

@pytest.fixture
def ee_profile(time_grid):
    t = time_grid
    return 5.0 * np.sin(np.pi * t / 5.0) * np.exp(-0.1 * t)


# ── AAD ──────────────────────────────────────────────────────────────────────

class TestAAD:
    def test_autodiff_basic(self):
        from src.utils.autodiff import Var
        x = Var(3.0); y = Var(4.0)
        z = (x * y + x.exp()) * 2.0
        z.backward()
        # dz/dx = 2*(y + e^x) = 2*(4 + e^3); dz/dy = 2*x = 6
        assert abs(float(x.grad) - 2 * (4 + np.exp(3))) < 1e-6
        assert abs(float(y.grad) - 6.0) < 1e-9

    def test_cva_matches_reference(self, ois_curve, time_grid, ee_profile):
        from src.xva.aad_greeks import AADCVAEngine
        cc = CreditCurve(80.0, 0.40)
        ref = CVAEngine(ois_curve).compute_cva(ee_profile, time_grid, cc)
        out = AADCVAEngine(ois_curve).cva_and_greeks(ee_profile, time_grid, cc)
        assert abs(out['CVA'] - ref) < 1e-9

    def test_greeks_match_bump(self, ois_curve, time_grid, ee_profile):
        from src.xva.aad_greeks import AADCVAEngine
        cc = CreditCurve(80.0, 0.40)
        bm = AADCVAEngine(ois_curve).benchmark_vs_bump(ee_profile, time_grid, cc, n_reps=10)
        assert bm['CS01_abs_err'] < 1e-5
        assert bm['IR01_abs_err'] < 1e-6
        assert bm['EE_delta_max_abs_err'] < 1e-6
        # one reverse sweep yields all sensitivities
        assert bm['aad_revaluations'] == 1
        assert bm['bump_revaluations'] == bm['n_sensitivities']

    def test_full_gradient_one_sweep(self, ois_curve, time_grid, ee_profile):
        from src.xva.aad_greeks import AADCVAEngine
        out = AADCVAEngine(ois_curve).cva_and_greeks(ee_profile, time_grid, CreditCurve(80.0))
        assert out['EE_deltas'].shape == time_grid.shape
        assert out['CS01'] > 0      # CVA rises with spread
        assert out['IR01'] < 0      # CVA falls as rates rise (discount)


# ── Quasi-Monte Carlo ────────────────────────────────────────────────────────

class TestQMC:
    def test_qmc_beats_mc(self):
        from src.montecarlo.quasi_mc import convergence_demo
        d = convergence_demo(path_counts=(512, 1024, 2048))
        # at the largest N, Sobol error should be well below pseudo-random
        last = d['rows'][-1]
        assert last['qmc_abs_err'] < last['mc_abs_err']

    def test_brownian_bridge(self):
        from src.montecarlo.quasi_mc import sobol_normals, brownian_bridge
        tg = np.linspace(0, 1, 9)
        W = brownian_bridge(sobol_normals(2048, 8, seed=1), tg)
        assert np.allclose(W[:, 0], 0.0)
        assert abs(W[:, -1].var() - 1.0) < 0.1     # Var(W_T)=T=1

    def test_sobol_shape(self):
        from src.montecarlo.quasi_mc import sobol_normals
        z = sobol_normals(1000, 5, seed=3)
        assert z.shape == (1000, 5)


# ── Longstaff-Schwartz ───────────────────────────────────────────────────────

class TestLSM:
    def test_bermudan_ge_european(self, ois_curve):
        from src.montecarlo.longstaff_schwartz import BermudanSwaptionLSM
        b = BermudanSwaptionLSM(ois_curve, 500.0, 0.07, [2.0, 3.0, 4.0], 5.0,
                                payer=True, a=0.10, sigma=0.012)
        r = b.price_and_exposure(n_paths=4000, n_steps_per_year=4, seed=42)
        assert r['price'] >= r['european_ref'] - 1e-3   # early-exercise premium
        assert r['price'] > 0

    def test_exposure_non_negative(self, ois_curve):
        from src.montecarlo.longstaff_schwartz import BermudanSwaptionLSM
        b = BermudanSwaptionLSM(ois_curve, 500.0, 0.07, [2.0, 3.0], 4.0,
                                payer=True, sigma=0.012)
        r = b.price_and_exposure(n_paths=3000, seed=1)
        assert np.all(r['EE'] >= -1e-9)

    def test_bond_level_correct(self, ois_curve):
        from src.montecarlo.longstaff_schwartz import HullWhite1FBonds
        hw = HullWhite1FBonds(ois_curve, 0.10, 0.012)
        p = hw.bond_price(2.0, 5.0, np.array([0.0]))[0]
        fwd = ois_curve.df(5.0) / ois_curve.df(2.0)
        assert abs(p - fwd) / fwd < 0.02     # within convexity tolerance


# ── Cross-currency / FX-XVA ──────────────────────────────────────────────────

class TestCrossCurrency:
    def test_fx_drift_and_exposure(self, ois_curve):
        from src.montecarlo.cross_currency import CrossCurrencySwapModel
        m = CrossCurrencySwapModel(ois_curve, for_rate=0.053, fx_spot=84.0, fx_vol=0.05)
        tg = np.linspace(0, 5, 61)
        sim = m.simulate(3000, tg, seed=42)
        # INR depreciates vs USD when r_d > r_f
        assert sim['FX'][:, -1].mean() > 84.0
        mtm = m.swap_mtm_paths(sim, 500.0, 0.067, 0.045, 5.0)
        em = m.exposure_metrics(mtm, tg)
        assert em['EPE'] > 0
        # PFE near maturity exceeds PFE early (notional-exchange FX risk)
        assert em['PFE'][-5] > em['PFE'][10]


# ── Stochastic-intensity WWR ─────────────────────────────────────────────────

class TestStochasticWWR:
    def test_wwr_monotonic(self, ois_curve):
        from src.wwr.stochastic_intensity_wwr import StochasticIntensityWWR
        w = StochasticIntensityWWR(ois_curve, kappa=0.5, theta=0.03, xi=0.08)
        up = w.wwr_multiplier(500.0, 0.07, 5.0, rho=0.5, payer=True, n_paths=6000, seed=7)
        dn = w.wwr_multiplier(500.0, 0.07, 5.0, rho=-0.5, payer=True, n_paths=6000, seed=7)
        assert up['wwr_multiplier'] > 1.0     # wrong-way
        assert dn['wwr_multiplier'] < 1.0     # right-way

    def test_zero_corr_unit(self, ois_curve):
        from src.wwr.stochastic_intensity_wwr import StochasticIntensityWWR
        w = StochasticIntensityWWR(ois_curve)
        r = w.wwr_multiplier(500.0, 0.07, 5.0, rho=0.0, n_paths=4000, seed=7)
        assert abs(r['wwr_multiplier'] - 1.0) < 1e-6


# ── BA-CVA & SA-CVA vega/curvature ───────────────────────────────────────────

class TestBACVA:
    def test_reduced_positive(self):
        from src.sa_ccr.ba_cva import BACVAEngine
        cptys = [{'name': 'A', 'sector': 'Financial', 'rating': 'AA', 'ead': 40.0, 'maturity': 5.0},
                 {'name': 'B', 'sector': 'Financial', 'rating': 'BB', 'ead': 30.0, 'maturity': 3.0}]
        r = BACVAEngine().compute_reduced(cptys)
        assert r['K_reduced'] > 0
        assert r['BA_CVA_capital_CR'] > 0

    def test_hedging_reduces_capital(self):
        from src.sa_ccr.ba_cva import BACVAEngine
        cptys = [{'name': 'A', 'sector': 'Financial', 'rating': 'AA', 'ead': 40.0, 'maturity': 5.0}]
        eng = BACVAEngine()
        red = eng.compute_reduced(cptys)
        full = eng.compute_full(cptys, beta=0.5)
        assert full['K_full'] <= red['K_reduced']

    def test_sa_cva_vega_curvature(self):
        from src.sa_ccr.frtb_cva import FRTBCVAEngine
        f = FRTBCVAEngine()
        veg = f.compute_vega_capital({'X': 0.002, 'Y': 0.001})
        assert veg['K_vega'] > 0
        cur = f.compute_curvature_capital(1.0, 1.05, 0.98)
        assert cur['K_curvature'] >= 0
        tot = f.compute_total_with_vega_curvature(
            {'X': 0.002}, {'X': 'AA'},
            counterparty_vega={'X': 0.002}, curvature=cur)
        assert tot['K_SA_CVA_total'] >= tot['K_total_FRTB_CVA']


# ── Exposure backtesting & IFRS 13 ───────────────────────────────────────────

class TestBacktestIFRS:
    def test_calibrated_green(self):
        from src.validation.exposure_backtest import ExposureBacktester
        rng = np.random.default_rng(1); n = 250
        bt = ExposureBacktester(quantile=0.95)
        res = bt.backtest(np.full(n, 1.645), rng.standard_normal(n))
        assert res['traffic_light']['zone'] == 'GREEN'
        assert not res['kupiec']['reject_H0']

    def test_understated_red(self):
        from src.validation.exposure_backtest import ExposureBacktester
        rng = np.random.default_rng(2); n = 250
        bt = ExposureBacktester(quantile=0.95)
        res = bt.backtest(np.full(n, 0.4), rng.standard_normal(n))
        assert res['traffic_light']['zone'] == 'RED'
        assert res['kupiec']['reject_H0']

    def test_ifrs13_signs(self):
        from src.xva.ifrs13 import XVAReserve, IFRS13XVAReporter
        r = XVAReserve(cva=4.0, dva=0.7, fva=1.0, mva=0.3, kva=2.0)
        stmt = IFRS13XVAReporter().fair_value_statement(r, include_kva=True)
        # net = -CVA + DVA - FVA - MVA - KVA
        assert abs(stmt['net_fv_adjustment_CR'] - (-4.0 + 0.7 - 1.0 - 0.3 - 2.0)) < 1e-9

    def test_ifrs13_pnl(self):
        from src.xva.ifrs13 import XVAReserve, IFRS13XVAReporter
        prev = XVAReserve(cva=4.0, dva=0.8)
        curr = XVAReserve(cva=4.5, dva=0.7)
        pnl = IFRS13XVAReporter().pnl_attribution(prev, curr)
        # CVA up 0.5 -> loss -0.5 ; DVA down 0.1 -> loss -0.1
        assert abs(pnl['lines']['CVA_pnl'] + 0.5) < 1e-9
        assert abs(pnl['lines']['DVA_pnl'] + 0.1) < 1e-9
