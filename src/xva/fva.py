"""
Funding Valuation Adjustment (FVA) Engine.

FVA accounts for the cost/benefit of funding uncollateralised
derivative positions using the bank's own funding curve rather
than the risk-free OIS rate.

Components:
    FCA (Funding Cost Adjustment):
        Cost of funding positive MTM positions the bank cannot
        receive collateral against.

    FBA (Funding Benefit Adjustment):
        Benefit of receiving funding from counterparty on negative
        MTM positions.

    Total FVA = FCA + FBA

Treasury Funding Curve:
    Funding Rate(t) = OIS Rate(t) + Funding Spread(t)
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional
from src.curves.ois_curve import OISCurve
from src.xva.cva import CreditCurve, build_credit_curve_from_cds


# Funding spread assumptions by entity type (bps)
FUNDING_SPREADS = {
    'PSU Bank': 25,
    'Large Private Bank': 40,
    'Private Bank': 40,
    'Mid-size Private Bank': 75,
    'Large NBFC': 150,
    'Mid NBFC': 250,
    'NBFC': 200,
    'Stressed Entity': 400,
}


class FVAEngine:
    """
    Funding Valuation Adjustment Engine.

    Computes FCA, FBA, and total FVA using exposure profiles
    and a treasury funding spread over OIS.

    Attributes:
        ois_curve: OIS discount curve.
        funding_spread_bps: Bank's funding spread over OIS in bps.
    """
    
    # Sign convention: FCA < 0 (negative = cost), FBA > 0 (positive = benefit)
    # FVA = FCA + FBA. This differs from FVAEngineV2 where both FCA and FBA
    # are positive magnitudes and FVA = FCA - FBA. Both conventions give the
    # same net FVA value. See fva_v2.py for the pathwise implementation.

    def __init__(self, ois_curve: OISCurve,
                 funding_spread_bps: float = 40.0,
                 bank_credit_curve: Optional[CreditCurve] = None,
                 cpty_credit_curve: Optional[CreditCurve] = None):
        """
        Initialise the FVA engine.

        Args:
            ois_curve: OIS discount curve.
            funding_spread_bps: Funding spread over OIS in basis points.
            bank_credit_curve: Bank's own credit curve.
            cpty_credit_curve: Counterparty credit curve.
        """
        self.ois_curve = ois_curve
        self.funding_spread = funding_spread_bps / 10000.0
        self.bank_credit_curve = bank_credit_curve
        self.cpty_credit_curve = cpty_credit_curve

    def compute_fca(self, ee_profile: np.ndarray,
                    time_grid: np.ndarray) -> float:
        """
        Compute Funding Cost Adjustment (FCA).

        FCA = -Spread × Σᵢ [EA(tᵢ) × DF(tᵢ) × δᵢ]

        where EA(t) = Expected positive exposure (asset).

        Args:
            ee_profile: Expected Exposure (positive) at each time.
            time_grid: Time grid.

        Returns:
            FCA value in ₹ Crores (negative = cost).
        """
        fca = 0.0
        for i in range(1, len(time_grid)):
            dt = time_grid[i] - time_grid[i - 1]
            t_mid = 0.5 * (time_grid[i - 1] + time_grid[i])
            ea_mid = 0.5 * (ee_profile[i - 1] + ee_profile[i])
            df = self.ois_curve.df(time_grid[i])
            
            sp_bank = self.bank_credit_curve.survival_probability(t_mid) if self.bank_credit_curve else 1.0
            sp_cpty = self.cpty_credit_curve.survival_probability(t_mid) if self.cpty_credit_curve else 1.0
            
            fca += ea_mid * sp_bank * sp_cpty * df * dt

        return -self.funding_spread * fca

    def compute_fba(self, ene_profile: np.ndarray,
                    time_grid: np.ndarray) -> float:
        """
        Compute Funding Benefit Adjustment (FBA).

        FBA = +Spread × Σᵢ [EL(tᵢ) × DF(tᵢ) × δᵢ]

        where EL(t) = Expected negative exposure (liability, positive value).

        Args:
            ene_profile: Expected Negative Exposure (negative values).
            time_grid: Time grid.

        Returns:
            FBA value in ₹ Crores (positive = benefit).
        """
        fba = 0.0
        for i in range(1, len(time_grid)):
            dt = time_grid[i] - time_grid[i - 1]
            t_mid = 0.5 * (time_grid[i - 1] + time_grid[i])
            # ENE is negative, take absolute value for liability
            el_mid = 0.5 * (abs(ene_profile[i - 1]) + abs(ene_profile[i]))
            df = self.ois_curve.df(time_grid[i])
            
            sp_bank = self.bank_credit_curve.survival_probability(t_mid) if self.bank_credit_curve else 1.0
            sp_cpty = self.cpty_credit_curve.survival_probability(t_mid) if self.cpty_credit_curve else 1.0
            
            fba += el_mid * sp_bank * sp_cpty * df * dt

        return self.funding_spread * fba

    def compute_fva(self, ee_profile: np.ndarray,
                    ene_profile: np.ndarray,
                    time_grid: np.ndarray) -> Dict[str, float]:
        """
        Compute total FVA = FCA + FBA.

        Args:
            ee_profile: Expected Exposure profile.
            ene_profile: Expected Negative Exposure profile.
            time_grid: Time grid.

        Returns:
            Dictionary with FCA, FBA, and total FVA.
        """
        fca = self.compute_fca(ee_profile, time_grid)
        fba = self.compute_fba(ene_profile, time_grid)

        return {
            'FCA': fca,
            'FBA': fba,
            'FVA': fca + fba,
            'funding_spread_bps': self.funding_spread * 10000,
        }


def compute_portfolio_fva(exposure_metrics: Dict,
                          counterparty_data: pd.DataFrame,
                          ois_curve: OISCurve) -> pd.DataFrame:
    """
    Compute FVA for each counterparty in the portfolio.

    Uses the counterparty's entity type to determine funding spread.

    Args:
        exposure_metrics: Dict mapping counterparty to exposure metrics.
        counterparty_data: DataFrame with counterparty data.
        ois_curve: OIS curve.

    Returns:
        DataFrame with FVA results per counterparty.
    """
    results = []

    for _, row in counterparty_data.iterrows():
        cpty_name = row['counterparty']
        if cpty_name not in exposure_metrics:
            continue

        metrics = exposure_metrics[cpty_name]
        funding_spread = row.get('funding_spread_bps',
                                 FUNDING_SPREADS.get(row['entity_type'], 50))

        if 'cds_spread_bps' in row and 'recovery_rate' in row:
            bank_curve = CreditCurve(40.0)
            cpty_curve = build_credit_curve_from_cds(
                tenors=[1.0, 2.0, 3.0, 5.0, 7.0],
                spreads_bps=[row['cds_spread_bps']] * 5,
                recovery_rate=row['recovery_rate'],
                ois_curve=ois_curve
            )
            engine = FVAEngine(ois_curve, funding_spread_bps=funding_spread,
                               bank_credit_curve=bank_curve,
                               cpty_credit_curve=cpty_curve)
        else:
            engine = FVAEngine(ois_curve, funding_spread_bps=funding_spread)

        time_grid = metrics['time_grid']
        ee = metrics['EE']
        ene = metrics.get('ENE', np.zeros_like(ee))

        fva_result = engine.compute_fva(ee, ene, time_grid)

        results.append({
            'counterparty': cpty_name,
            'entity_type': row['entity_type'],
            'funding_spread_bps': funding_spread,
            'FCA_cr': fva_result['FCA'],
            'FBA_cr': fva_result['FBA'],
            'FVA_cr': fva_result['FVA'],
        })

    return pd.DataFrame(results)
