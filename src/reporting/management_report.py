"""
Management Reporting Engine (Phase 10).

Consolidates metrics across the XVA, Risk, RAROC, Limits, and WWR engines
to produce unified daily management summary reports.
"""
from typing import Dict, Any, List
import datetime

class ManagementReportGenerator:
    def __init__(self, 
                 xva_results: Dict[str, Any],
                 limit_results: Dict[str, Any],
                 raroc_results: Dict[str, Any],
                 econ_cap_results: Dict[str, Any],
                 wwr_results: Dict[str, Any],
                 attribution_results: Dict[str, Any]):
        """
        Takes in the aggregated outputs of all institutional risk engines.
        """
        self.xva_results = xva_results
        self.limit_results = limit_results
        self.raroc_results = raroc_results
        self.econ_cap_results = econ_cap_results
        self.wwr_results = wwr_results
        self.attribution_results = attribution_results

    def generate_daily_summary(self) -> Dict[str, Any]:
        """
        Generates a consolidated dict suitable for dashboard rendering, 
        emailing, or export to PDF/Excel.
        """
        report_date = datetime.date.today().isoformat()
        
        # Extract Top-Level Metrics
        cva = self.xva_results.get('Total_CVA', 0.0)
        dva = self.xva_results.get('Total_DVA', 0.0)
        fva = self.xva_results.get('Total_FVA', 0.0)
        total_xva = cva - dva + fva  # Simple aggregation
        
        cva_dod_change = self.attribution_results.get('Total_Change', 0.0)
        
        # Capital & Returns
        portfolio_raroc = self.raroc_results.get('Portfolio_RAROC', 0.0)
        portfolio_eva = self.raroc_results.get('Portfolio_EVA', 0.0)
        econ_capital = self.econ_cap_results.get('Economic_Capital', 0.0)
        
        # Limits
        total_breaches = self.limit_results.get('Total_Breaches', 0)
        total_warnings = self.limit_results.get('Total_Warnings', 0)
        
        # WWR
        wwr_impact = self.wwr_results.get('WWR_Impact', 0.0)
        stressed_cva = self.wwr_results.get('Stressed_CVA', cva)
        
        return {
            'Report_Date': report_date,
            'Executive_Summary': {
                'Total_XVA': total_xva,
                'CVA': cva,
                'CVA_DoD_Change': cva_dod_change,
                'DVA': dva,
                'FVA': fva
            },
            'Capital_And_Returns': {
                'Economic_Capital': econ_capital,
                'Portfolio_RAROC_Pct': portfolio_raroc * 100,
                'Portfolio_EVA': portfolio_eva
            },
            'Stress_And_WWR': {
                'Stressed_CVA': stressed_cva,
                'WWR_Impact': wwr_impact,
                'Stress_Multiplier': self.wwr_results.get('Effective_Multiplier', 1.0)
            },
            'Governance': {
                'Active_Limit_Breaches': total_breaches,
                'Active_Limit_Warnings': total_warnings,
                'Status': 'RED' if total_breaches > 0 else ('AMBER' if total_warnings > 0 else 'GREEN')
            }
        }
