"""
Basel BA-CVA (Basic Approach for CVA capital).

The BA-CVA is the standardised fallback for banks that do not use SA-CVA.
It is fully specified in BIS d424/d457 (free) and needs no market data —
only EAD, effective maturity, and a supervisory risk weight per counterparty.

Reduced version (no hedging recognised):
    K_reduced = sqrt( (ρ · Σ_c SCVA_c)² + (1-ρ²) · Σ_c SCVA_c² )
with ρ = 0.5 and
    SCVA_c = (1/α) · RW_c · Σ_NS ( M_NS · EAD_NS · DF_NS )
    DF_NS  = (1 - e^{-0.05·M}) / (0.05·M)      (supervisory discount factor)
    α      = 1.4

Full version recognises single-name and index CDS hedges. This module
implements the reduced approach plus a simplified hedged variant.

Reference: BIS "Basel III: Finalising post-crisis reforms" (d424), CVA chapter.
"""

import numpy as np
from typing import Dict, List, Optional

ALPHA = 1.4
RHO = 0.5

# BA-CVA supervisory risk weights RW_c (%) by sector × credit quality
# (BIS d424, MAR50.x). IG = investment grade, HY = high-yield/unrated.
BA_CVA_RISK_WEIGHTS = {
    'Sovereign':   {'IG': 0.5, 'HY': 3.0},
    'LocalGovt':   {'IG': 1.0, 'HY': 4.0},
    'Financial':   {'IG': 5.0, 'HY': 12.0},
    'Materials':   {'IG': 3.0, 'HY': 7.0},
    'Consumer':    {'IG': 3.0, 'HY': 8.5},
    'Tech':        {'IG': 2.0, 'HY': 5.5},
    'Healthcare':  {'IG': 1.5, 'HY': 5.0},
    'Other':       {'IG': 5.0, 'HY': 12.0},
}

_IG_RATINGS = {'AAA', 'AA+', 'AA', 'AA-', 'A+', 'A', 'A-',
               'BBB+', 'BBB', 'BBB-'}


def _credit_quality(rating: str) -> str:
    return 'IG' if str(rating).strip().upper() in _IG_RATINGS else 'HY'


def supervisory_df(maturity: float) -> float:
    """Supervisory discount factor DF = (1 - e^{-0.05M}) / (0.05M)."""
    m = max(maturity, 1e-6)
    return (1.0 - np.exp(-0.05 * m)) / (0.05 * m)


def scva(rw_pct: float, ead: float, maturity: float) -> float:
    """Standalone CVA capital contribution for one counterparty (single netting set)."""
    return (1.0 / ALPHA) * (rw_pct / 100.0) * maturity * ead * supervisory_df(maturity)


class BACVAEngine:
    """Basel Basic Approach CVA capital calculator."""

    def __init__(self, capital_ratio: float = 0.105):
        self.capital_ratio = capital_ratio

    def risk_weight(self, sector: str, rating: str) -> float:
        sec = sector if sector in BA_CVA_RISK_WEIGHTS else 'Other'
        return BA_CVA_RISK_WEIGHTS[sec][_credit_quality(rating)]

    def compute_reduced(self, counterparties: List[Dict]) -> Dict:
        """
        Reduced BA-CVA (no hedges).

        Args:
            counterparties: list of dicts with keys:
                name, sector, rating, ead, maturity

        Returns:
            Dict with per-counterparty SCVA, K_reduced, and capital.
        """
        scva_list = []
        details = []
        for c in counterparties:
            rw = self.risk_weight(c.get('sector', 'Other'), c.get('rating', 'NR'))
            s = scva(rw, float(c['ead']), float(c['maturity']))
            scva_list.append(s)
            details.append({'name': c['name'], 'rw_pct': rw, 'scva': s,
                            'ead': float(c['ead']), 'maturity': float(c['maturity'])})

        scva_arr = np.array(scva_list)
        sum_scva = scva_arr.sum()
        sum_scva_sq = (scva_arr ** 2).sum()
        k_reduced = np.sqrt((RHO * sum_scva) ** 2 + (1 - RHO ** 2) * sum_scva_sq)

        return {
            'details': details,
            'sum_scva': float(sum_scva),
            'K_reduced': float(k_reduced),
            'BA_CVA_capital_CR': float(k_reduced * self.capital_ratio),
            'systematic_component': float(RHO * sum_scva),
            'idiosyncratic_component': float(np.sqrt((1 - RHO ** 2) * sum_scva_sq)),
        }

    def compute_full(self, counterparties: List[Dict],
                     beta: float = 0.25) -> Dict:
        """
        Full BA-CVA with a simplified hedging benefit.

        DS_hedge (single-name CDS notional × RW × DF) reduces the effective
        SCVA. We apply an aggregate hedging-effectiveness factor β (0..1):
            K_hedged ≈ (1-β)·K_reduced  (β = recognised hedge benefit)
        plus the regulatory floor K_full = β_floor·K_reduced + (1-β_floor)·K_hedged
        with β_floor = 0.25 (BIS supervisory floor on hedge benefit).

        Args:
            counterparties: as in compute_reduced (may include 'cds_hedge_notional').
            beta: fraction of SCVA hedged by single-name CDS (0..1).

        Returns:
            Dict with K_reduced, K_hedged, K_full, capital.
        """
        red = self.compute_reduced(counterparties)
        k_reduced = red['K_reduced']
        beta = float(np.clip(beta, 0.0, 1.0))
        k_hedged = (1.0 - beta) * k_reduced
        beta_floor = 0.25   # supervisory floor: at most 75% benefit
        k_full = beta_floor * k_reduced + (1.0 - beta_floor) * k_hedged
        return {
            **red,
            'hedge_fraction_beta': beta,
            'K_hedged': float(k_hedged),
            'K_full': float(k_full),
            'BA_CVA_capital_full_CR': float(k_full * self.capital_ratio),
        }
