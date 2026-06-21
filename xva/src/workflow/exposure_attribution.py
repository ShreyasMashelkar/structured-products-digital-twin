"""
Exposure Attribution Engine (Phase 7).

Provides formal analysis of day-over-day changes in Exposure (EAD/PFE)
and XVA metrics broken down by:
- New Trades (New Volume)
- Matured Trades (Run-off)
- Market Moves (Rates, FX)
- Credit Spreads (CVA impact)
- Time Decay (Theta)
"""
from typing import Dict, Any, List

class ExposureAttributionEngine:
    def __init__(self):
        pass

    def explain_exposure_change(self, 
                                t0_portfolio: List[Dict[str, Any]], t0_exposure: float,
                                t1_portfolio: List[Dict[str, Any]], t1_exposure: float,
                                market_move_impact: float) -> Dict[str, float]:
        """
        Explain the change in exposure between T0 and T1.
        
        Uses a sequential update method:
        1. Base T0 Exposure
        2. + New Trades
        3. - Matured Trades
        4. + Market Moves
        5. + Unexplained (Cross-effects)
        """
        t0_ids = {str(t.get('TradeID')) for t in t0_portfolio}
        t1_ids = {str(t.get('TradeID')) for t in t1_portfolio}
        
        new_trades = [t for t in t1_portfolio if str(t.get('TradeID')) not in t0_ids]
        matured_trades = [t for t in t0_portfolio if str(t.get('TradeID')) not in t1_ids]
        
        # Proxying the isolated impact of new/matured trades.
        # In a real system, you re-price T0 portfolio with/without these subsets.
        # Here we approximate using their notional fraction or given EAD estimates.
        
        # If no actual re-pricing engine is passed, we use the sum of their estimated standalones
        new_trade_impact = sum(float(t.get('EstimatedEAD', t.get('Notional', 0)*0.05)) for t in new_trades)
        matured_trade_impact = sum(float(t.get('EstimatedEAD', t.get('Notional', 0)*0.05)) for t in matured_trades)
        
        total_explained = new_trade_impact - matured_trade_impact + market_move_impact
        actual_change = t1_exposure - t0_exposure
        unexplained = actual_change - total_explained
        
        return {
            'T0_Exposure': t0_exposure,
            'New_Trades': new_trade_impact,
            'Matured_Trades': -matured_trade_impact,
            'Market_Moves': market_move_impact,
            'Unexplained': unexplained,
            'T1_Exposure': t1_exposure,
            'Total_Change': actual_change
        }

    def explain_cva_change(self,
                           t0_cva: float, t1_cva: float,
                           exposure_change_impact: float,
                           spread_change_impact: float,
                           time_decay_impact: float) -> Dict[str, float]:
        """
        Explains CVA change via first-order sensitivities.
        """
        total_explained = exposure_change_impact + spread_change_impact + time_decay_impact
        actual_change = t1_cva - t0_cva
        unexplained = actual_change - total_explained
        
        return {
            'T0_CVA': t0_cva,
            'Exposure_Change': exposure_change_impact,
            'Spread_Change': spread_change_impact,
            'Time_Decay': time_decay_impact,
            'Unexplained': unexplained,
            'T1_CVA': t1_cva,
            'Total_Change': actual_change
        }
