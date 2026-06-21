import numpy as np
import pandas as pd
from typing import Dict, List, Any
from src.sa_ccr.regulatory import SACCRCalculator, compute_rwa, compute_capital_requirement
from src.xva.kva import KVAEngine
from src.xva.cva import CVAEngine, CreditCurve
from src.xva.fva import FVAEngine

# SA-CCR alpha multiplier — used to back out an EE proxy from the EAD profile
SACCR_ALPHA = 1.4

class CapitalOptimizer:
    """Computes capital metrics and Return on Capital (RoC) to rank trades."""

    def __init__(self, ois_curve, counterparties_df: pd.DataFrame):
        self.ois_curve = ois_curve
        self.cptys = counterparties_df.set_index('Counterparty').to_dict(orient='index')
        self.saccr = SACCRCalculator()
        self.kva_engine = KVAEngine(ois_curve)
        self.cva_engine = CVAEngine(ois_curve)
        
    def evaluate_trade(self, trade: Dict[str, Any], mtm_val: float) -> Dict[str, Any]:
        """Calculates Capital and KVA for a single trade."""
        notional = float(trade['Notional'])
        maturity = float(trade['Maturity'])
        cpty_name = trade['Counterparty']
        direction = trade['Direction']
        
        # 1. SA-CCR EAD
        # Simplify to unmargined EAD for trade level
        rc = max(mtm_val, 0)
        
        # PFE
        sf = 0.005 if maturity <= 5 else 0.015
        mf = 1.0  # unmargined MF
        delta = 1.0 if direction == 'Receive Fixed' else -1.0
        
        supervisory_duration = (1.0 - np.exp(-0.05 * maturity)) / 0.05
        adjusted_notional = notional * supervisory_duration
        
        pfe = sf * abs(adjusted_notional * mf * delta)
        ead = 1.4 * (rc + pfe)
        
        # 2. Capital & KVA
        cpty = self.cptys.get(cpty_name, {})
        risk_weight = cpty.get('RiskWeight', 0.50)
        rwa = compute_rwa(ead, risk_weight)
        capital = compute_capital_requirement(rwa)

        # Proper KVA: Discounted integral of capital over time.
        # Reuse the SA-CCR EAD profile to derive an EE proxy for CVA/FVA.
        cva = 0.0
        fva = 0.0
        if maturity > 0:
            time_grid = np.linspace(0.0, maturity, max(2, int(maturity * 12) + 1))
            mtm_profile = np.full_like(time_grid, mtm_val)
            kva_res = self.kva_engine.compute_kva_from_saccr(
                time_grid=time_grid,
                notional=notional,
                initial_maturity=maturity,
                direction=direction,
                risk_weight=risk_weight,
                mtm_profile=mtm_profile
            )
            kva = kva_res['KVA']

            # EE proxy from the SA-CCR EAD profile (EE ≈ EAD / α). This is a
            # one-sided (positive) exposure, so we can compute CVA and the
            # funding cost (FCA) but not a genuine funding benefit (FBA).
            ee_profile = kva_res['ead_profile'] / SACCR_ALPHA

            # 3a. Genuine CVA from the counterparty's CDS spread & recovery.
            cds_bps = float(cpty.get('CDS_Spread_BPS', 100.0))
            recovery = float(cpty.get('RecoveryRate', 0.40))
            credit_curve = CreditCurve(cds_bps, recovery)
            cva = self.cva_engine.compute_cva(ee_profile, time_grid, credit_curve)

            # 3b. FVA as the funding cost (FCA) on the uncollateralised positive
            # exposure — the dominant, well-defined FVA term for a derivative
            # asset. FBA is omitted: no genuine negative-exposure profile exists
            # at this aggregation level. FundingSpread is a decimal (0.0050=50bps).
            funding_bps = float(cpty.get('FundingSpread', 0.0040)) * 10000.0
            fva_engine = FVAEngine(self.ois_curve, funding_spread_bps=funding_bps)
            fva = abs(fva_engine.compute_fca(ee_profile, time_grid))
        else:
            kva = 0.0

        # 4. Profit / Return on Capital
        # Revenue proxy: MTM (if positive) plus an embedded margin.
        revenue = max(mtm_val, 0) + (notional * 0.001 * maturity)  # assume 10bps embedded margin

        # RoC now charges the full XVA cost stack (CVA + FVA + KVA).
        total_xva = cva + fva + kva
        roc = (revenue - total_xva) / capital if capital > 0 else 0

        return {
            'TradeID': trade['TradeID'],
            'Counterparty': cpty_name,
            'MTM': mtm_val,
            'EAD': ead,
            'RWA': rwa,
            'Capital': capital,
            'CVA': cva,
            'FVA': fva,
            'KVA': kva,
            'Revenue': revenue,
            'RoC': roc
        }
        
    def rank_portfolio(self, trades: List[Dict[str, Any]], mtm_vals: Dict[int, float]) -> pd.DataFrame:
        """Evaluates all trades and returns a ranked dataframe by RoC."""
        import numpy as np
        
        results = []
        for trade in trades:
            tid = trade['TradeID']
            mtm = mtm_vals.get(tid, 0.0)
            res = self.evaluate_trade(trade, mtm)
            results.append(res)
            
        df = pd.DataFrame(results)
        if not df.empty:
            df = df.sort_values(by='RoC', ascending=False).reset_index(drop=True)
            
        return df
