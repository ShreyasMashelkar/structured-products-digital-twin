"""
Wrong-Way Risk (WWR) Governance and Stress Testing Engine (Phase 9).

Identifies Specific and General Wrong-Way Risk in portfolios and applies 
stress multipliers to Expected Positive Exposure (EPE) or Probability of Default (PD).
"""
import numpy as np
from typing import Dict, Any, List

class WWREngine:
    def __init__(self, general_wwr_multiplier: float = 1.2, specific_wwr_multiplier: float = 1.5):
        """
        general_wwr_multiplier: Multiplier for macro-driven WWR.
        specific_wwr_multiplier: Multiplier for specific WWR (e.g., selling puts on counterparty stock).
        """
        self.general_wwr_multiplier = general_wwr_multiplier
        self.specific_wwr_multiplier = specific_wwr_multiplier

    def detect_wwr(self, trade: Dict[str, Any], counterparty_sector: str) -> str:
        """
        Detects if a trade exhibits WWR.
        Returns 'SPECIFIC', 'GENERAL', or 'NONE'.
        """
        trade_type = trade.get('Direction', '').upper()
        # Specific WWR: e.g., derivatives directly linked to the counterparty or its immediate sector
        if 'SPECIFIC_WWR' in str(trade.get('Tags', '')).upper():
            return 'SPECIFIC'
            
        # General WWR: e.g., macro correlation (Pay Fixed in a high inflation macro regime against a weak corporate)
        if trade_type == 'PAY' and counterparty_sector == 'HIGH_YIELD':
            return 'GENERAL'
            
        return 'NONE'

    def apply_wwr_stress(self, 
                         ee_profile: np.ndarray, 
                         wwr_type: str) -> np.ndarray:
        """
        Applies a deterministic multiplier to the Expected Exposure (EE) profile
        based on the detected WWR severity.
        """
        if wwr_type == 'SPECIFIC':
            return ee_profile * self.specific_wwr_multiplier
        elif wwr_type == 'GENERAL':
            return ee_profile * self.general_wwr_multiplier
        return ee_profile

    def calculate_stressed_cva(self, 
                               base_cva: float, 
                               portfolio_trades: List[Dict[str, Any]],
                               cpty_sector: str = 'INVESTMENT_GRADE') -> Dict[str, float]:
        """
        Calculates a stressed CVA for the portfolio by bumping the aggregate CVA
        proportionally to the WWR risk detected in the trades.
        (A simplified proxy for full path-dependent WWR re-simulation).
        """
        wwr_flags = [self.detect_wwr(t, cpty_sector) for t in portfolio_trades]
        
        specific_count = wwr_flags.count('SPECIFIC')
        general_count = wwr_flags.count('GENERAL')
        total_trades = len(portfolio_trades)
        
        if total_trades == 0:
            return {'Base_CVA': base_cva, 'Stressed_CVA': base_cva, 'WWR_Impact': 0.0}
            
        # Weighted average stress multiplier
        specific_weight = specific_count / total_trades
        general_weight = general_count / total_trades
        none_weight = 1.0 - (specific_weight + general_weight)
        
        effective_multiplier = (
            specific_weight * self.specific_wwr_multiplier +
            general_weight * self.general_wwr_multiplier +
            none_weight * 1.0
        )
        
        stressed_cva = base_cva * effective_multiplier
        
        return {
            'Base_CVA': base_cva,
            'Stressed_CVA': stressed_cva,
            'WWR_Impact': stressed_cva - base_cva,
            'Effective_Multiplier': effective_multiplier
        }
