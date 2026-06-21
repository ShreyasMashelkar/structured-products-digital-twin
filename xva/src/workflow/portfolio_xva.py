"""
Portfolio / netting-set XVA context (additive layer — reuses existing engines).

Provides a single reusable context that builds curves + Hull-White Monte Carlo
ONCE, then computes netting-set-level XVA for an arbitrary list of trades. This
is the foundation for incremental XVA (Phase 1): run the SAME context for
(netting set) and (netting set + proposed trade) using common random numbers
(identical MC paths), so the difference reflects the trade, not MC noise.

It does NOT re-derive any XVA — it calls CVAEngine / FVAEngine / MVAEngine /
KVAEngine / SACCRCalculator exactly as src/eod/risk_engine.py does.
"""
from typing import Dict, List, Optional, Any
import numpy as np
import pandas as pd

from src.curves.ois_curve import OISCurve
from src.curves.multi_curve import MultiCurveFramework
from src.montecarlo.hull_white import HullWhite1F, calibrate_hw1f
from src.portfolio.netting_engine import NettingEngine
from src.pricing.swap_pricer import SwapPricer
from src.xva.cva import CVAEngine, CreditCurve, build_credit_curve_from_cds
from src.xva.fva import FVAEngine
from src.xva.kva import KVAEngine
from src.xva.mva import MVAEngine
from src.sa_ccr.regulatory import SACCRCalculator, compute_rwa, compute_capital_requirement
from src.data_ingestion.market_data import get_ois_market_data, get_historical_mibor
from src.data_ingestion.portfolio_manager import PortfolioManager


class PortfolioXVAContext:
    """Builds market state once; computes netting-set XVA for any trade subset."""

    def __init__(self, n_paths: int = 2000, n_steps: int = 60,
                 horizon: float = 10.0, seed: int = 42,
                 own_cds_bps: float = 40.0):
        self.seed = seed
        self.own_cds_bps = own_cds_bps

        ois_data = get_ois_market_data()
        self.ois_curve = OISCurve(ois_data['tenor_years'].values,
                                  ois_data['ois_rate'].values)
        self.mcf = MultiCurveFramework.build_from_market_data()

        mibor_history = get_historical_mibor(n_days=504)
        hw_params = calibrate_hw1f(mibor_history['mibor_rate'])
        a = float(np.clip(hw_params['a'], 0.01, 0.50))
        sigma = float(np.clip(hw_params['sigma'], 0.001, 0.05))

        # Monte Carlo built ONCE — common random numbers for all subset runs.
        self.hw_model = HullWhite1F(self.ois_curve, a=a, sigma=sigma)
        self.time_grid, self.rate_paths = self.hw_model.simulate_rates(
            n_paths=n_paths, n_steps=n_steps, horizon=horizon, seed=seed
        )
        self.cptys_df = PortfolioManager.load_counterparties()

    def _cpty_row(self, counterparty: str) -> Dict[str, Any]:
        rows = self.cptys_df[self.cptys_df['Counterparty'] == counterparty]
        if rows.empty:
            return {'CDS_Spread_BPS': 100.0, 'RecoveryRate': 0.40,
                    'FundingSpread': 0.005, 'RiskWeight': 0.50}
        return rows.iloc[0].to_dict()

    def netting_set_xva(self, trades: List[Dict[str, Any]],
                        counterparty: str) -> Dict[str, float]:
        """Compute netting-set-level XVA for `trades` (all under one counterparty)."""
        if not trades:
            return {'EPE': 0.0, 'CVA': 0.0, 'DVA': 0.0, 'BCVA': 0.0,
                    'FVA': 0.0, 'MVA': 0.0, 'KVA': 0.0, 'EAD': 0.0, 'Capital': 0.0}

        row = self._cpty_row(counterparty)
        cds_bps = float(row.get('CDS_Spread_BPS', 100.0))
        recovery = float(row.get('RecoveryRate', 0.40))
        funding_spread_bps = float(row.get('FundingSpread', 0.005)) * 10000
        risk_weight = float(row.get('RiskWeight', 0.50))

        netting = NettingEngine(self.time_grid, self.rate_paths, self.hw_model)
        trade_paths = netting.calculate_trade_mtm_paths(trades, projection_curve=self.mcf.mibor)
        csa_mtm = netting.aggregate_by_csa(trades, trade_paths=trade_paths)
        csa_exposures = netting.apply_collateral(csa_mtm)

        ee = ene = tg = None
        epe = 0.0
        for csa_id, metrics in csa_exposures.items():
            tg = metrics['time_grid']
            if ee is None:
                ee = np.zeros_like(metrics['EE'])
                ene = np.zeros_like(metrics['EE'])
            ee = ee + metrics['EE']
            ene = ene + metrics.get('ENE', np.zeros_like(metrics['EE']))
            epe += float(metrics.get('EPE', 0.0))
        if ee is None:
            return {'EPE': 0.0, 'CVA': 0.0, 'DVA': 0.0, 'BCVA': 0.0,
                    'FVA': 0.0, 'MVA': 0.0, 'KVA': 0.0, 'EAD': 0.0, 'Capital': 0.0}

        all_ccp = all(csa_exposures.get(c, {}).get('is_ccp', False) for c in csa_exposures)

        cva_engine = CVAEngine(self.ois_curve)
        cpty_curve = build_credit_curve_from_cds(
            tenors=[1.0, 2.0, 3.0, 5.0, 7.0], spreads_bps=[cds_bps] * 5,
            recovery_rate=recovery, ois_curve=self.ois_curve)
        own_curve = CreditCurve(self.own_cds_bps)
        bcva = cva_engine.compute_bilateral_cva(ee, ene, tg, cpty_curve, own_curve)
        if all_ccp:
            bcva = {'CVA': 0.0, 'DVA': 0.0, 'Bilateral_CVA': 0.0}

        fva = FVAEngine(self.ois_curve, funding_spread_bps=funding_spread_bps,
                        bank_credit_curve=own_curve, cpty_credit_curve=cpty_curve
                        ).compute_fva(ee, ene, tg)

        total_notional = sum(float(t['Notional']) for t in trades)
        avg_mat = (sum(float(t['Notional']) * float(t['Maturity']) for t in trades)
                   / total_notional if total_notional > 0 else 5.0)
        directions = [t['Direction'] for t in trades]
        net_dir = max(set(directions), key=directions.count)
        kva = KVAEngine(self.ois_curve).compute_kva_from_saccr(
            time_grid=tg, notional=total_notional, initial_maturity=avg_mat,
            direction=net_dir, risk_weight=risk_weight, mtm_profile=ee)

        total_dv01 = 0.0
        for t in trades:
            fr = float(t['FixedRate'])
            sp = SwapPricer(notional=float(t['Notional']),
                            fixed_rate=fr / 100.0 if fr > 1.0 else fr,
                            maturity=float(t['Maturity']), direction=t['Direction'])
            total_dv01 += abs(sp.dv01(self.ois_curve))
        mva_engine = MVAEngine(ois_curve=self.ois_curve,
                               funding_spread_bps=funding_spread_bps, dv01_cr=total_dv01)
        mva = mva_engine.compute_mva(mva_engine.compute_im_profile(ee), tg)

        df = pd.DataFrame(trades).rename(columns={
            'Notional': 'notional_cr', 'Maturity': 'maturity_years', 'Direction': 'direction'})
        current_mtm = float(sum(p[:, 0].mean() for p in trade_paths.values()))
        saccr = SACCRCalculator().compute_netting_set_ead(df, mtm_total=current_mtm)
        ead = saccr['EAD']
        capital = compute_capital_requirement(compute_rwa(ead, risk_weight))

        return {'EPE': epe, 'CVA': bcva['CVA'], 'DVA': bcva['DVA'],
                'BCVA': bcva['Bilateral_CVA'], 'FVA': fva['FVA'],
                'MVA': float(mva), 'KVA': kva['KVA'], 'EAD': ead, 'Capital': capital}
