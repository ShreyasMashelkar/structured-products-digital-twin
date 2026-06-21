"""
Counterparty Limit Management Engine (Phase 4).

Monitors and enforces limits on various exposure metrics (MTM, EPE, PFE, EAD)
at the Legal Entity level.
"""
from typing import Dict, List, Any
import pandas as pd


class LimitEngine:
    def __init__(self, limits: List[Dict[str, Any]]):
        """
        limits: List of dictionaries containing:
            - LegalEntityID
            - Metric (e.g., 'MTM', 'PFE_95', 'EAD', 'EPE')
            - LimitAmount (float)
        """
        self.limits_df = pd.DataFrame(limits)

    def check_limits(self, entity_metrics: Dict[str, Dict[str, float]]) -> pd.DataFrame:
        """
        Check actual metrics against limits for each entity.
        
        entity_metrics: Dict mapping LegalEntityID -> Dict of metric names to values.
            e.g., {'LE_HDFC': {'MTM': 50.0, 'PFE_95': 120.0}}
            
        Returns a DataFrame with the status of each limit.
        """
        results = []
        if self.limits_df.empty:
            return pd.DataFrame()
            
        for _, limit in self.limits_df.iterrows():
            le = limit['LegalEntityID']
            metric = limit['Metric']
            limit_amt = float(limit['LimitAmount'])
            
            actual = entity_metrics.get(le, {}).get(metric, 0.0)
            utilization = actual / limit_amt if limit_amt > 0 else 0.0
            
            status = 'GREEN'
            if utilization >= 1.0:
                status = 'BREACH'
            elif utilization >= 0.8:
                status = 'AMBER'
                
            results.append({
                'LegalEntityID': le,
                'Metric': metric,
                'LimitAmount': limit_amt,
                'ActualAmount': actual,
                'Utilization': utilization,
                'Status': status
            })
            
        return pd.DataFrame(results)

    def pre_trade_check(self, entity_metrics_base: Dict[str, Dict[str, float]],
                        incremental_metrics: Dict[str, float],
                        target_entity: str) -> pd.DataFrame:
        """
        Evaluates limit status after adding the incremental metrics of a proposed trade.
        """
        # Create a combined metrics view
        combined = {le: dict(metrics) for le, metrics in entity_metrics_base.items()}
        if target_entity not in combined:
            combined[target_entity] = {}
            
        for m, val in incremental_metrics.items():
            combined[target_entity][m] = combined[target_entity].get(m, 0.0) + val
            
        return self.check_limits(combined)
