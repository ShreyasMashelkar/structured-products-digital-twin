"""
Tests for the equity asset class and hybrid cross-asset XVA.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from src.data_ingestion.market_data import get_ois_market_data
from src.curves.ois_curve import OISCurve
from src.xva.cva import CreditCurve


@pytest.fixture
def ois_curve():
    d = get_ois_market_data()
    return OISCurve(d['tenor_years'].values, d['ois_rate'].values)

@pytest.fixture
def equity_md():
    from src.data_ingestion.equity_data import get_equity_market_data
    return get_equity_market_data('NIFTY')


# ── Equity data ──────────────────────────────────────────────────────────────

class TestEquityData:
    def test_market_data_structure(self, equity_md):
        for k in ('spot', 'div_yield', 'atm_vol', 'india_vix', 'lot_size', 'source'):
            assert k in equity_md
        assert equity_md['spot'] > 0
        assert 0 < equity_md['atm_vol'] < 1

    def test_option_chain_smile(self):
        from src.data_ingestion.equity_data import get_nifty_option_chain
        ch = get_nifty_option_chain('NIFTY')
        assert len(ch) >= 5
        assert {'strike', 'log_moneyness', 'implied_vol'} <= set(ch.columns)


# ── Equity option pricing ────────────────────────────────────────────────────

class TestEquityOptions:
    def test_put_call_parity(self):
        from src.pricing.equity_options import bsm_price
        S, K, T, r, q, v = 24500, 24500, 0.25, 0.067, 0.013, 0.135
        c = bsm_price(S, K, T, r, q, v, True)
        p = bsm_price(S, K, T, r, q, v, False)
        parity = S * np.exp(-q * T) - K * np.exp(-r * T)
        assert abs((c - p) - parity) < 1e-6

    def test_implied_vol_inversion(self):
        from src.pricing.equity_options import bsm_price, implied_vol
        S, K, T, r, q, v = 24500, 25000, 0.5, 0.067, 0.013, 0.16
        price = bsm_price(S, K, T, r, q, v, True)
        iv = implied_vol(price, S, K, T, r, q, True)
        assert abs(iv - v) < 1e-4

    def test_negative_skew(self):
        from src.pricing.equity_options import EquityVolSmile
        sm = EquityVolSmile(atm_vol=0.135)
        assert sm.vol(22000, 24500) > sm.vol(24500, 24500)   # OTM put richer

    def test_greeks_signs(self):
        from src.pricing.equity_options import bsm_greeks
        g = bsm_greeks(24500, 24500, 0.25, 0.067, 0.013, 0.135, True)
        assert 0 < g['delta'] < 1
        assert g['gamma'] > 0 and g['vega'] > 0 and g['theta'] < 0


# ── Equity exposure MC ───────────────────────────────────────────────────────

class TestEquityMC:
    def test_discounted_spot_martingale(self, ois_curve, equity_md):
        from src.montecarlo.equity_mc import EquityGBM
        gbm = EquityGBM(equity_md['spot'], equity_md['atm_vol'], equity_md['div_yield'])
        tg = np.linspace(0, 1, 53)
        S = gbm.simulate(tg, 8000, ois_curve, seed=42)
        r1 = ois_curve.zero_rate(1.0)
        disc_S = S[:, -1].mean() * np.exp(-r1 * 1.0)
        target = equity_md['spot'] * np.exp(-equity_md['div_yield'] * 1.0)
        assert abs(disc_S - target) / target < 0.02

    def test_option_exposure_non_negative(self, ois_curve, equity_md):
        from src.montecarlo.equity_mc import EquityGBM
        gbm = EquityGBM(equity_md['spot'], equity_md['atm_vol'], equity_md['div_yield'])
        tg = np.linspace(0, 1, 27)
        S = gbm.simulate(tg, 3000, ois_curve, seed=1)
        mtm = gbm.option_mtm_paths(S, tg, ois_curve, equity_md['spot'], 1.0,
                                   units=500, call=True)
        em = gbm.exposure_metrics(mtm, tg)
        assert np.all(em['EE'] >= -1e-9)
        assert em['EPE'] > 0


# ── Hybrid cross-asset XVA ───────────────────────────────────────────────────

class TestHybridXVA:
    def _engine(self, ois_curve, equity_md, rho):
        from src.xva.hybrid_xva import HybridXVAEngine
        return HybridXVAEngine(ois_curve, equity_md['spot'], equity_md['atm_vol'],
                               equity_md['div_yield'], a=0.10, sigma_r=0.010,
                               equity_rate_corr=rho)

    def test_subadditive_netting(self, ois_curve, equity_md):
        eng = self._engine(ois_curve, equity_md, -0.15)
        tg = np.linspace(0, 3, 37)
        sim = eng.simulate_joint(tg, 5000, seed=42)
        swap = eng.swap_mtm(sim, 500.0, 0.07, 3.0, payer=False)
        units = int(300e7 / equity_md['spot'])
        fwd = eng.eq.forward_mtm_paths(sim['spot'], tg, ois_curve, equity_md['spot'],
                                       3.0, units, long=False) / 1e7
        res = eng.compute_hybrid_xva(sim, [swap, fwd], CreditCurve(85.0))
        # netting benefit: hybrid CVA <= sum of standalone CVAs (subadditivity)
        assert res['CVA_hybrid'] <= res['sum_standalone_cva'] + 1e-9
        assert 0.0 <= res['netting_benefit_pct'] <= 100.0

    def test_correlation_affects_netting(self, ois_curve, equity_md):
        tg = np.linspace(0, 3, 37)
        units = int(300e7 / equity_md['spot'])

        def benefit(rho):
            eng = self._engine(ois_curve, equity_md, rho)
            sim = eng.simulate_joint(tg, 6000, seed=42)
            swap = eng.swap_mtm(sim, 500.0, 0.07, 3.0, payer=False)
            fwd = eng.eq.forward_mtm_paths(sim['spot'], tg, ois_curve, equity_md['spot'],
                                           3.0, units, long=False) / 1e7
            return eng.compute_hybrid_xva(sim, [swap, fwd], CreditCurve(85.0))['netting_benefit_pct']

        # more negative equity-rate corr → better offset → larger netting benefit
        assert benefit(-0.6) > benefit(0.6)

    def test_hybrid_xva_components(self, ois_curve, equity_md):
        eng = self._engine(ois_curve, equity_md, -0.15)
        tg = np.linspace(0, 2, 25)
        sim = eng.simulate_joint(tg, 4000, seed=3)
        swap = eng.swap_mtm(sim, 500.0, 0.07, 2.0, payer=False)
        opt = eng.equity_option_mtm(sim, equity_md['spot'], 2.0, units=500, call=True) / 1e7
        res = eng.compute_hybrid_xva(sim, [swap, opt], CreditCurve(85.0))
        for k in ('CVA_hybrid', 'DVA_hybrid', 'FVA_hybrid', 'BCVA_hybrid'):
            assert k in res
        assert res['CVA_hybrid'] >= 0
        assert res['FVA_hybrid'] >= 0
