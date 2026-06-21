"""
Incremental XVA Engine (Phase 1) — additive layer.

Computes the MARGINAL XVA of a proposed trade against its counterparty's
existing netting set:

    IncrementalMetric = Metric(NettingSet + {trade}) - Metric(NettingSet)

Uses a single PortfolioXVAContext so both runs share identical Monte Carlo
paths (common random numbers). XVA is NOT additive across trades (netting and
collateral), so this two-run difference is the only correct way to get the
marginal number.
"""
from typing import Dict, List, Any, Optional
import pandas as pd

from src.workflow.portfolio_xva import PortfolioXVAContext
from src.data_ingestion.portfolio_manager import PortfolioManager


class IncrementalXVAEngine:
    def __init__(self, context: Optional[PortfolioXVAContext] = None):
        self.ctx = context or PortfolioXVAContext()

    def compute(self, proposed_trade: Dict[str, Any],
                existing_trades: Optional[List[Dict[str, Any]]] = None
                ) -> Dict[str, Any]:
        cpty = proposed_trade.get('Counterparty')
        if existing_trades is None:
            port = PortfolioManager.load_portfolio().to_dict('records')
            existing_trades = [t for t in port if t.get('Counterparty') == cpty]

        base = self.ctx.netting_set_xva(existing_trades, cpty)
        with_trade = self.ctx.netting_set_xva(existing_trades + [proposed_trade], cpty)

        incr = {k: with_trade[k] - base[k] for k in base}
        incr['Total_XVA'] = incr['CVA'] + incr['FVA'] + incr['MVA'] + incr['KVA']
        return {'base': base, 'with_trade': with_trade, 'incremental': incr}

    def impact_report(self, proposed_trade: Dict[str, Any],
                      existing_trades: Optional[List[Dict[str, Any]]] = None
                      ) -> pd.DataFrame:
        incr = self.compute(proposed_trade, existing_trades)['incremental']
        rows = [('CVA', incr['CVA']), ('FVA', incr['FVA']), ('MVA', incr['MVA']),
                ('KVA', incr['KVA']), ('Total XVA', incr['Total_XVA']),
                ('Incremental EAD', incr['EAD']), ('Incremental Capital', incr['Capital'])]
        return pd.DataFrame(rows, columns=['Component', 'Incremental Impact (Cr)'])
