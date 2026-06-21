"""
Trade Approval Workflow Engine (Phase 6).

Orchestrates XVA Impact, Limit checks, and RAROC accretion to automatically 
approve, reject, or flag trades for manual review.
"""
from typing import Dict, Any, List
import pandas as pd


class TradeApprovalWorkflow:
    def __init__(self, limit_engine, raroc_engine, incremental_xva_engine):
        self.limit_engine = limit_engine
        self.raroc_engine = raroc_engine
        self.incremental_xva_engine = incremental_xva_engine

    def evaluate_trade(self,
                       trade: Dict[str, Any],
                       base_portfolio: List[Dict[str, Any]],
                       base_metrics: Dict[str, Any],
                       entity_limits_base: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
        """
        Evaluates a proposed trade.
        
        base_metrics expects:
            - 'Revenue'
            - 'Expected_Loss'
            - 'XVA_Costs'
            - 'Capital'
        """
        # 1. Compute Incremental XVA
        incr_xva_res = self.incremental_xva_engine.compute_incremental_impact(trade, base_portfolio)
        trade_xva = incr_xva_res['Incremental_Total_XVA']
        
        # Proxy metrics for the new trade (in a real system, these come from upstream pricing)
        trade_notional = float(trade.get('Notional', 100000000))
        trade_revenue = float(trade.get('ExpectedRevenue', trade_notional * 0.005))
        trade_el = float(trade.get('ExpectedLoss', trade_notional * 0.001))
        trade_cap = float(trade.get('CapitalRequired', trade_notional * 0.05))
        trade_ead = float(trade.get('EstimatedEAD', trade_notional * 0.10))
        trade_pfe = float(trade.get('EstimatedPFE', trade_notional * 0.15))
        
        # 2. Check Limits
        le_id = trade.get('LegalEntityID', f"LE_{trade.get('Counterparty')}")
        incr_limit_metrics = {'EAD': trade_ead, 'PFE_95': trade_pfe}
        limit_res_df = self.limit_engine.pre_trade_check(entity_limits_base, incr_limit_metrics, le_id)
        
        limit_status = 'PASS'
        if not limit_res_df.empty:
            if 'BREACH' in limit_res_df['Status'].values:
                limit_status = 'FAIL'
            elif 'AMBER' in limit_res_df['Status'].values:
                limit_status = 'WARNING'
        
        # 3. Check RAROC Accretion
        raroc_res = self.raroc_engine.evaluate_incremental_trade(
            base_revenue=base_metrics.get('Revenue', 0.0),
            base_el=base_metrics.get('Expected_Loss', 0.0),
            base_xva=base_metrics.get('XVA_Costs', 0.0),
            base_cap=base_metrics.get('Capital', 0.0),
            incr_revenue=trade_revenue,
            incr_el=trade_el,
            incr_xva=trade_xva,
            incr_cap=trade_cap
        )
        
        # Decision Logic
        decision = 'MANUAL_REVIEW'
        reasons = []
        
        if limit_status == 'FAIL':
            decision = 'REJECTED'
            reasons.append("Limit Breach Detected.")
        
        if not raroc_res['Meets_Hurdle']:
            reasons.append("Trade standalone RAROC below hurdle.")
            if decision != 'REJECTED':
                decision = 'MANUAL_REVIEW'
                
        if not raroc_res['Improves_Portfolio']:
            reasons.append("Trade dilutes portfolio RAROC.")
            
        if limit_status == 'PASS' and raroc_res['Meets_Hurdle'] and raroc_res['Improves_Portfolio']:
            decision = 'APPROVED'
            reasons.append("Trade is accretive and within limits.")
            
        if limit_status == 'WARNING':
            reasons.append("Approaching Limit (Amber).")
            if decision == 'APPROVED':
                decision = 'MANUAL_REVIEW'

        return {
            'TradeID': trade.get('TradeID', 'NEW'),
            'Decision': decision,
            'Reasons': reasons,
            'Incremental_XVA': trade_xva,
            'Trade_RAROC': raroc_res['Trade_Standalone_RAROC'],
            'Portfolio_RAROC_Impact': raroc_res['New_RAROC'] - raroc_res['Base_RAROC'],
            'Limit_Status': limit_status
        }
