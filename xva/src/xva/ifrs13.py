"""
IFRS 13 XVA fair-value accounting view.

XVA is not just risk — it is a fair-value adjustment that flows through the
balance sheet and P&L under IFRS 13 ("Fair Value Measurement"). This module
packages the engine's XVA outputs into the accounting view a product-control
or financial-reporting function would use:

  - the total XVA fair-value reserve (CVA/DVA/FVA/MVA/KVA),
  - the day-over-day P&L decomposition (what moved the reserve),
  - the IFRS 13 fair-value hierarchy classification (Level 1/2/3),
  - the accounting sign conventions (CVA & FVA reduce asset fair value; DVA
    is an own-credit gain that IFRS books but many desks exclude from
    regulatory capital).

No market data required — it consumes XVA numbers already computed elsewhere.

Reference: IFRS 13; IASB; standard bank XVA accounting practice.
"""

import numpy as np
from typing import Dict, Optional
from dataclasses import dataclass, field


@dataclass
class XVAReserve:
    """A point-in-time XVA fair-value reserve (all in ₹ Cr, desk sign)."""
    cva: float = 0.0   # counterparty credit — reduces asset FV (cost, +ve)
    dva: float = 0.0   # own credit — increases FV (benefit, +ve)
    fva: float = 0.0   # funding — cost, +ve
    mva: float = 0.0   # margin funding — cost, +ve
    kva: float = 0.0   # capital — cost, +ve (often excluded from FV, info only)

    def total_fair_value_adjustment(self, include_kva: bool = False) -> float:
        """
        Net XVA adjustment to fair value (IFRS 13).

        FV adjustment = -CVA + DVA - FVA - MVA [- KVA].
        Negative ⇒ reduces the asset's carrying value.
        """
        adj = -self.cva + self.dva - self.fva - self.mva
        if include_kva:
            adj -= self.kva
        return adj


# IFRS 13 fair-value hierarchy by input observability
FV_HIERARCHY = {
    'CVA': 'Level 2',   # observable CDS / proxy spreads + model
    'DVA': 'Level 2',   # own observable spread + model
    'FVA': 'Level 3',   # funding spread partly unobservable
    'MVA': 'Level 3',   # IM funding, model-driven
    'KVA': 'Level 3',   # capital cost, highly model-dependent
}


class IFRS13XVAReporter:
    """Builds the IFRS 13 accounting view and P&L attribution for XVA."""

    def fair_value_statement(self, reserve: XVAReserve,
                             include_kva: bool = False) -> Dict:
        """
        Produce the XVA fair-value reserve statement.

        Returns the components, the net FV adjustment, and the hierarchy
        level for each component.
        """
        comps = {
            'CVA': {'amount': reserve.cva, 'fv_sign': -reserve.cva,
                    'hierarchy': FV_HIERARCHY['CVA'], 'note': 'Cost — reduces asset FV'},
            'DVA': {'amount': reserve.dva, 'fv_sign': +reserve.dva,
                    'hierarchy': FV_HIERARCHY['DVA'], 'note': 'Own-credit benefit — increases FV'},
            'FVA': {'amount': reserve.fva, 'fv_sign': -reserve.fva,
                    'hierarchy': FV_HIERARCHY['FVA'], 'note': 'Funding cost — reduces FV'},
            'MVA': {'amount': reserve.mva, 'fv_sign': -reserve.mva,
                    'hierarchy': FV_HIERARCHY['MVA'], 'note': 'IM funding cost — reduces FV'},
        }
        if include_kva:
            comps['KVA'] = {'amount': reserve.kva, 'fv_sign': -reserve.kva,
                            'hierarchy': FV_HIERARCHY['KVA'],
                            'note': 'Capital cost — reduces FV (info)'}
        net = reserve.total_fair_value_adjustment(include_kva)
        return {
            'components': comps,
            'net_fv_adjustment_CR': net,
            'gross_xva_reserve_CR': reserve.cva + reserve.fva + reserve.mva
                                    + (reserve.kva if include_kva else 0.0),
            'own_credit_benefit_CR': reserve.dva,
            'include_kva': include_kva,
        }

    def pnl_attribution(self, prev: XVAReserve, curr: XVAReserve,
                        include_kva: bool = False) -> Dict:
        """
        Day-over-day XVA P&L attribution.

        The change in each component is a P&L line. Convention: a fall in CVA
        is a P&L gain (the reserve releases), a rise is a loss.
        """
        def pnl(component_prev, component_curr, is_benefit):
            d = component_curr - component_prev
            # benefit (DVA): increase = gain; cost (CVA/FVA/...): increase = loss
            return d if is_benefit else -d

        lines = {
            'CVA_pnl': pnl(prev.cva, curr.cva, False),
            'DVA_pnl': pnl(prev.dva, curr.dva, True),
            'FVA_pnl': pnl(prev.fva, curr.fva, False),
            'MVA_pnl': pnl(prev.mva, curr.mva, False),
        }
        if include_kva:
            lines['KVA_pnl'] = pnl(prev.kva, curr.kva, False)
        total = sum(lines.values())
        return {
            'lines': lines,
            'total_xva_pnl_CR': float(total),
            'prev_net_fv': prev.total_fair_value_adjustment(include_kva),
            'curr_net_fv': curr.total_fair_value_adjustment(include_kva),
        }
