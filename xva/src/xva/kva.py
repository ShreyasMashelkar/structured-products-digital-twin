"""
Capital Valuation Adjustment (KVA) Engine.

KVA is the adjustment to derivative pricing to account for the cost
of holding regulatory capital against the trade over its lifetime.

KVA = Cost_of_Capital × ∫ EK(t) × DF(t) dt

where:
    EK(t) = Expected regulatory capital at time t
    DF(t) = Risk-free discount factor
    Cost_of_Capital = Bank's cost of equity capital (RoE target)

Workflow:
    Trade → SA-CCR EAD → RWA → Capital Requirement → KVA
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional
from src.curves.ois_curve import OISCurve
from src.sa_ccr.regulatory import (SACCRCalculator, compute_rwa,
                                     CAPITAL_RATIO, RISK_WEIGHTS)


# Cost of capital for Indian banks (RoE target - cost of debt)
DEFAULT_COST_OF_CAPITAL = 0.12  # ~12%


class KVAEngine:
    """
    Capital Valuation Adjustment Engine.

    Computes the present value of the cost of holding regulatory
    capital over the life of a trade.

    Attributes:
        ois_curve: OIS discount curve.
        cost_of_capital: Annual cost of equity capital.
        capital_ratio: Minimum capital ratio.
    """

    def __init__(self, ois_curve: OISCurve,
                 cost_of_capital: float = DEFAULT_COST_OF_CAPITAL,
                 capital_ratio: float = CAPITAL_RATIO):
        """
        Initialise the KVA engine.

        Args:
            ois_curve: OIS discount curve.
            cost_of_capital: Cost of equity capital (e.g. 0.12 for 12%).
            capital_ratio: Minimum capital ratio (0.105 for RBI 10.5%).
        """
        self.ois_curve = ois_curve
        self.cost_of_capital = cost_of_capital
        self.capital_ratio = capital_ratio

    def compute_kva(self, ead_profile: np.ndarray,
                    time_grid: np.ndarray,
                    risk_weight: float) -> float:
        """
        Compute KVA from an EAD profile over time.

        KVA = CoC × Σᵢ [Capital(tᵢ) × DF(tᵢ) × δᵢ]

        where Capital(tᵢ) = EAD(tᵢ) × RW × Capital_Ratio

        Args:
            ead_profile: EAD at each time point (₹ Cr).
            time_grid: Time grid.
            risk_weight: Counterparty risk weight.

        Returns:
            KVA value in ₹ Crores.
        """
        kva = 0.0

        for i in range(1, len(time_grid)):
            dt = time_grid[i] - time_grid[i - 1]

            # Capital at this time point
            ead_mid = 0.5 * (ead_profile[i - 1] + ead_profile[i])
            rwa = ead_mid * risk_weight
            capital = rwa * self.capital_ratio

            # Discount
            df = self.ois_curve.df(time_grid[i])

            kva += capital * df * dt

        return self.cost_of_capital * kva

    def compute_kva_from_saccr(
        self,
        time_grid: np.ndarray,
        notional: float,
        initial_maturity: float,
        direction: str,
        risk_weight: float,
        mtm_profile: np.ndarray,
        margined: bool = False,
        mpor_days: int = 10,
    ) -> Dict[str, float]:
        """
        Compute KVA using proper SA-CCR EAD at each time node.
        """
        ead_profile = np.zeros_like(time_grid)
        calculator = SACCRCalculator()

        for i, t_i in enumerate(time_grid):
            remaining_maturity = max(initial_maturity - t_i, 0.01)
            trades_df = pd.DataFrame([{
                'notional_cr': notional,
                'maturity_years': remaining_maturity,
                'direction': direction
            }])
            
            ead = calculator.compute_netting_set_ead(
                trades=trades_df,
                mtm_total=mtm_profile[i],
                margined=margined,
                mpor_days=mpor_days
            )
            ead_profile[i] = ead['EAD']

        kva = self.compute_kva(ead_profile, time_grid, risk_weight)
        capital_profile = ead_profile * risk_weight * self.capital_ratio

        return {
            'KVA': kva,
            'peak_capital_cr': np.max(capital_profile),
            'avg_capital_cr': np.mean(capital_profile),
            'cost_of_capital_pct': self.cost_of_capital * 100,
            'risk_weight': risk_weight,
            'capital_ratio': self.capital_ratio,
            'ead_profile': ead_profile,
            'capital_profile': capital_profile,
            'method': 'SA-CCR'
        }

    def compute_kva_from_exposure(self, ee_profile: np.ndarray,
                                   time_grid: np.ndarray,
                                   risk_weight: float,
                                   notional: float = 500.0) -> Dict[str, float]:
        """
        Compute KVA from an EE profile by constructing an approximate
        EAD profile using SA-CCR alpha multiplier.

        EAD(t) ≈ α × EE(t)  (simplified approximation)

        Args:
            ee_profile: Expected Exposure profile.
            time_grid: Time grid.
            risk_weight: Counterparty risk weight.
            notional: Trade notional for context.

        Returns:
            Dictionary with KVA, peak_capital, avg_capital.
        """
        # Approximate EAD from EE
        alpha = 1.4
        ead_profile = alpha * ee_profile

        kva = self.compute_kva(ead_profile, time_grid, risk_weight)

        # Capital profile
        capital_profile = ead_profile * risk_weight * self.capital_ratio

        return {
            'KVA': kva,
            'peak_capital_cr': np.max(capital_profile),
            'avg_capital_cr': np.mean(capital_profile),
            'cost_of_capital_pct': self.cost_of_capital * 100,
            'risk_weight': risk_weight,
            'capital_ratio': self.capital_ratio,
            'ead_profile': ead_profile,
            'capital_profile': capital_profile,
            'method': 'alpha_EE_proxy'
        }


def compute_portfolio_kva(exposure_metrics: Dict,
                          counterparty_data: pd.DataFrame,
                          ois_curve: OISCurve) -> pd.DataFrame:
    """
    Compute KVA for each counterparty in the portfolio.

    Args:
        exposure_metrics: Dict mapping counterparty to exposure metrics.
        counterparty_data: DataFrame with counterparty data.
        ois_curve: OIS curve.

    Returns:
        DataFrame with KVA results per counterparty.
    """
    engine = KVAEngine(ois_curve)
    results = []

    for _, row in counterparty_data.iterrows():
        cpty_name = row['counterparty']
        if cpty_name not in exposure_metrics:
            continue

        metrics = exposure_metrics[cpty_name]
        risk_weight = row.get('risk_weight', 0.50)

        # Use SA-CCR if trade data is available in metrics, else fallback to exposure proxy
        if 'notional_cr' in metrics and 'maturity_years' in metrics and 'direction' in metrics:
            kva_result = engine.compute_kva_from_saccr(
                time_grid=metrics['time_grid'],
                notional=metrics['notional_cr'],
                initial_maturity=metrics['maturity_years'],
                direction=metrics['direction'],
                risk_weight=risk_weight,
                mtm_profile=metrics['EE'],  # Proxy EE for MTM
                margined=metrics.get('margined', False),
                mpor_days=metrics.get('mpor_days', 10)
            )
        else:
            kva_result = engine.compute_kva_from_exposure(
                ee_profile=metrics['EE'],
                time_grid=metrics['time_grid'],
                risk_weight=risk_weight,
            )

        results.append({
            'counterparty': cpty_name,
            'entity_type': row['entity_type'],
            'risk_weight': risk_weight,
            'KVA_cr': kva_result['KVA'],
            'peak_capital_cr': kva_result['peak_capital_cr'],
            'avg_capital_cr': kva_result['avg_capital_cr'],
        })

    return pd.DataFrame(results)
