"""
Risk-Adjusted Return on Capital (RAROC) Framework (Phase 5).

Calculates the true economic profitability of trades and portfolios by factoring in
revenue, expected credit losses, XVA funding costs, and allocated capital.
"""
from typing import Dict, Any

class RAROCEngine:
    def __init__(self, hurdle_rate: float = 0.10):
        """
        hurdle_rate: The minimum acceptable RAROC (e.g., 10%).
        """
        self.hurdle_rate = hurdle_rate

    def compute_raroc(self, revenue: float,
                      expected_loss: float,
                      expenses: float,
                      xva_costs: float,
                      allocated_capital: float) -> Dict[str, Any]:
        """
        Compute standard RAROC.
        """
        net_income = revenue - expected_loss - expenses - xva_costs
        
        if allocated_capital <= 0.0:
            raroc = float('inf') if net_income > 0 else float('-inf')
        else:
            raroc = net_income / allocated_capital
            
        is_accretive = raroc >= self.hurdle_rate
        
        return {
            'Revenue': revenue,
            'Expected_Loss': expected_loss,
            'Expenses': expenses,
            'XVA_Costs': xva_costs,
            'Allocated_Capital': allocated_capital,
            'Net_Income': net_income,
            'RAROC': raroc,
            'Economic_Value_Added': net_income - (allocated_capital * self.hurdle_rate),
            'Is_Accretive': is_accretive
        }

    def evaluate_incremental_trade(self,
                                   base_revenue: float, base_el: float, base_xva: float, base_cap: float,
                                   incr_revenue: float, incr_el: float, incr_xva: float, incr_cap: float,
                                   expenses: float = 0.0) -> Dict[str, Any]:
        """
        Evaluates whether an incremental trade improves the portfolio RAROC.
        """
        base_metrics = self.compute_raroc(base_revenue, base_el, expenses, base_xva, base_cap)
        
        new_rev = base_revenue + incr_revenue
        new_el = base_el + incr_el
        new_xva = base_xva + incr_xva
        new_cap = base_cap + incr_cap
        
        new_metrics = self.compute_raroc(new_rev, new_el, expenses, new_xva, new_cap)
        trade_standalone = self.compute_raroc(incr_revenue, incr_el, 0.0, incr_xva, incr_cap)
        
        return {
            'Base_RAROC': base_metrics['RAROC'],
            'New_RAROC': new_metrics['RAROC'],
            'Trade_Standalone_RAROC': trade_standalone['RAROC'],
            'Improves_Portfolio': new_metrics['RAROC'] > base_metrics['RAROC'],
            'Meets_Hurdle': trade_standalone['Is_Accretive']
        }
