"""
SA-CCR (Standardised Approach for Counterparty Credit Risk) Module.

Implements Basel III/IV SA-CCR for computing Exposure at Default (EAD)
for INR OTC interest rate derivatives.

EAD = α × (RC + PFE)    where α = 1.4

Components:
    RC (Replacement Cost):
        Unmargined: max(V - C, 0)
        Margined: max(V - C, TH + MTA - NICA, 0)

    PFE (Potential Future Exposure) Add-On:
        Add-On = SF × Effective Notional × δ × MF

Supervisory factors for IR derivatives:
    < 1Y:  0.50%
    1-5Y:  0.50%
    > 5Y:  1.50%
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional


# Basel supervisory factors for interest rate derivatives
SUPERVISORY_FACTORS = {
    'short': 0.005,     # < 1Y: 0.50%
    'medium': 0.005,    # 1-5Y: 0.50%
    'long': 0.015,      # > 5Y: 1.50%
}

# Basel correlation between maturity buckets
MATURITY_BUCKET_CORR = {
    ('short', 'short'): 1.0,
    ('short', 'medium'): 0.7,
    ('short', 'long'): 0.3,
    ('medium', 'short'): 0.7,
    ('medium', 'medium'): 1.0,
    ('medium', 'long'): 0.7,
    ('long', 'short'): 0.3,
    ('long', 'medium'): 0.7,
    ('long', 'long'): 1.0,
}

# RBI Basel III risk weights by counterparty type
RISK_WEIGHTS = {
    'PSU Bank': 0.20,
    'Private Bank': 0.20,
    'Foreign Bank': 0.20,
    'Large NBFC': 0.75,
    'Mid NBFC': 1.00,
    'NBFC': 0.75,
    'Large Corporate (IG)': 0.50,
    'Large Corporate (Sub-IG)': 1.00,
    'Stressed Entity': 1.50,
}

# Alpha multiplier (Basel standard)
ALPHA = 1.4

# RBI minimum capital ratio
CAPITAL_RATIO = 0.105  # 10.5% CET1 + buffer


class SACCRCalculator:
    """
    SA-CCR calculator for a netting set of INR interest rate trades.

    Computes Replacement Cost, PFE Add-On, EAD, and RWA following
    Basel III standardised methodology.
    """

    def __init__(self):
        """Initialise the SA-CCR calculator."""
        pass

    @staticmethod
    def maturity_bucket(end_year: float) -> str:
        """
        Assign a trade to a maturity bucket.

        Args:
            end_year: Residual maturity in years.

        Returns:
            'short', 'medium', or 'long'.
        """
        if end_year <= 1.0:
            return 'short'
        elif end_year <= 5.0:
            return 'medium'
        else:
            return 'long'

    @staticmethod
    def supervisory_duration(start: float, end: float) -> float:
        """
        Compute the supervisory duration.

        SD = (exp(-0.05 × S) - exp(-0.05 × E)) / 0.05

        Args:
            start: Start of rate period in years.
            end: End of rate period in years.

        Returns:
            Supervisory duration.
        """
        return (np.exp(-0.05 * start) - np.exp(-0.05 * end)) / 0.05

    @staticmethod
    def maturity_factor(maturity: float, margined: bool = False,
                        mpor_days: int = 10) -> float:
        """
        Compute the maturity factor.

        Unmargined: MF = sqrt(min(M, 1) / 1)
        Margined: MF = 1.5 × sqrt(MPOR / 252)

        Args:
            maturity: Residual maturity in years.
            margined: Whether the trade is margined.
            mpor_days: Margin Period of Risk in days.

        Returns:
            Maturity factor.
        """
        if margined:
            return 1.5 * np.sqrt(mpor_days / 252)
        else:
            return np.sqrt(min(maturity, 1.0))

    def compute_trade_addon(self, notional: float, maturity: float,
                            direction: str, start: float = 0.0,
                            margined: bool = False,
                            mpor_days: int = 10) -> Dict[str, float]:
        """
        Compute the PFE add-on for a single trade.

        Add-On = SF × |d| × MF

        where:
            d = Adjusted Notional × δ
            Adjusted Notional = Trade Notional × Supervisory Duration
            δ = +1 (receive fixed) or -1 (pay fixed)

        Args:
            notional: Trade notional in ₹ Crores.
            maturity: Residual maturity in years.
            direction: 'Receive Fixed' or 'Pay Fixed'.
            start: Start of rate period (0 for spot-starting).
            margined: Whether margined.
            mpor_days: MPOR in days.

        Returns:
            Dictionary with trade-level SA-CCR components.
        """
        # Delta
        delta = 1.0 if direction == 'Receive Fixed' else -1.0

        # Supervisory Duration
        sd = self.supervisory_duration(start, maturity)

        # Adjusted Notional
        adj_notional = notional * sd

        # Effective Notional (with delta)
        eff_notional = adj_notional * delta

        # Maturity Factor
        mf = self.maturity_factor(maturity, margined, mpor_days)

        # Maturity bucket and supervisory factor
        bucket = self.maturity_bucket(maturity)
        sf = SUPERVISORY_FACTORS[bucket]

        # Trade-level contribution (signed for aggregation)
        d_i = eff_notional * mf

        # Trade add-on (unsigned)
        addon = sf * abs(d_i)

        return {
            'delta': delta,
            'supervisory_duration': sd,
            'adjusted_notional': adj_notional,
            'effective_notional': eff_notional,
            'maturity_factor': mf,
            'maturity_bucket': bucket,
            'supervisory_factor': sf,
            'd_i': d_i,
            'trade_addon': addon,
        }

    def compute_replacement_cost(self, mtm: float, collateral: float = 0.0,
                                  threshold: float = 0.0,
                                  mta: float = 0.0,
                                  nica: float = 0.0,
                                  margined: bool = False) -> float:
        """
        Compute Replacement Cost.

        Unmargined: RC = max(V - C, 0)
        Margined: RC = max(V - C, TH + MTA - NICA, 0)

        Args:
            mtm: Current MTM of netting set (₹ Cr).
            collateral: Current collateral held (₹ Cr).
            threshold: CSA threshold (₹ Cr).
            mta: Minimum Transfer Amount (₹ Cr).
            nica: Net Independent Collateral Amount (₹ Cr).
            margined: Whether the netting set is margined.

        Returns:
            Replacement Cost in ₹ Crores.
        """
        if not margined:
            return max(mtm - collateral, 0.0)
        else:
            return max(mtm - collateral, threshold + mta - nica, 0.0)

    def compute_netting_set_ead(self, trades: pd.DataFrame,
                                 mtm_total: float,
                                 collateral: float = 0.0,
                                 margined: bool = False,
                                 threshold: float = 0.0,
                                 mta: float = 0.0,
                                 nica: float = 0.0,
                                 mpor_days: int = 10) -> Dict[str, float]:
        """
        Compute EAD for a netting set of trades.

        EAD = α × (RC + PFE)

        Args:
            trades: DataFrame with columns: notional_cr, maturity_years,
                    direction.
            mtm_total: Total MTM of the netting set.
            collateral: Collateral held.
            margined: Whether margined.
            threshold: CSA threshold.
            mta: MTA.
            nica: NICA.
            mpor_days: MPOR days.

        Returns:
            Dictionary with RC, PFE, EAD, and trade details.
        """
        # Step 1: Replacement Cost
        rc = self.compute_replacement_cost(
            mtm_total, collateral, threshold, mta, nica, margined
        )

        # Step 2: Compute trade-level add-ons
        bucket_d = {'short': 0.0, 'medium': 0.0, 'long': 0.0}
        trade_details = []

        for _, trade in trades.iterrows():
            result = self.compute_trade_addon(
                notional=trade['notional_cr'],
                maturity=trade['maturity_years'],
                direction=trade['direction'],
                margined=margined,
                mpor_days=mpor_days
            )
            trade_details.append(result)
            bucket_d[result['maturity_bucket']] += result['d_i']

        # Step 3: Aggregate across maturity buckets with correlations
        # Add-On_IR = sqrt(Σ_i Σ_j ρᵢⱼ × Dᵢ × Dⱼ)
        buckets = ['short', 'medium', 'long']
        total_sq = 0.0
        for b1 in buckets:
            for b2 in buckets:
                rho = MATURITY_BUCKET_CORR[(b1, b2)]
                # Use SF for each bucket
                sf1 = SUPERVISORY_FACTORS[b1]
                sf2 = SUPERVISORY_FACTORS[b2]
                total_sq += rho * sf1 * bucket_d[b1] * sf2 * bucket_d[b2]

        pfe_addon = np.sqrt(max(total_sq, 0.0))

        # Step 4: Apply multiplier (simplified — full multiplier depends on V-C)
        v_minus_c = mtm_total - collateral
        if v_minus_c < 0:
            multiplier = min(1.0, 0.05 + 0.95 * np.exp(v_minus_c / (2 * max(pfe_addon, 1e-10))))
        else:
            multiplier = 1.0

        pfe = multiplier * pfe_addon

        # Step 5: EAD
        ead = ALPHA * (rc + pfe)

        return {
            'RC': rc,
            'PFE_addon': pfe_addon,
            'multiplier': multiplier,
            'PFE': pfe,
            'EAD': ead,
            'alpha': ALPHA,
            'bucket_D': bucket_d,
            'trade_details': trade_details,
        }


def compute_rwa(ead: float, risk_weight: float) -> float:
    """
    Compute Risk-Weighted Assets.

    RWA = EAD × Risk Weight

    Args:
        ead: Exposure at Default in ₹ Crores.
        risk_weight: Counterparty risk weight (0.20 for banks, etc.).

    Returns:
        RWA in ₹ Crores.
    """
    return ead * risk_weight


def compute_capital_requirement(rwa: float,
                                 capital_ratio: float = CAPITAL_RATIO) -> float:
    """
    Compute regulatory capital requirement.

    Capital = RWA × Capital Ratio

    Args:
        rwa: Risk-Weighted Assets in ₹ Crores.
        capital_ratio: Minimum capital ratio (10.5% per RBI).

    Returns:
        Capital requirement in ₹ Crores.
    """
    return rwa * capital_ratio


def compute_portfolio_saccr(portfolio_df: pd.DataFrame,
                             trade_mtms: Dict[str, float],
                             counterparty_data: pd.DataFrame) -> pd.DataFrame:
    """
    Compute SA-CCR EAD and RWA for each counterparty netting set.

    Args:
        portfolio_df: Trade portfolio DataFrame.
        trade_mtms: Dictionary of trade_id → MTM value.
        counterparty_data: Counterparty data with risk weights.

    Returns:
        DataFrame with SA-CCR results per counterparty.
    """
    calculator = SACCRCalculator()
    results = []

    # Group trades by counterparty (netting set)
    for cpty, trades in portfolio_df.groupby('counterparty'):
        # Get counterparty risk weight
        cpty_row = counterparty_data[
            counterparty_data['counterparty'] == cpty
        ]
        if len(cpty_row) == 0:
            rw = 0.50  # Default
        else:
            rw = cpty_row.iloc[0]['risk_weight']

        # Total MTM for netting set
        mtm_total = sum(trade_mtms.get(tid, 0.0)
                        for tid in trades['trade_id'])

        # Determine if margined
        csa_types = trades['csa_type'].unique()
        margined = any(t in ['Fully Collateralised', 'CCP-Cleared']
                       for t in csa_types)

        # Compute EAD
        ead_result = calculator.compute_netting_set_ead(
            trades=trades,
            mtm_total=mtm_total,
            margined=margined,
        )

        rwa = compute_rwa(ead_result['EAD'], rw)
        capital = compute_capital_requirement(rwa)

        results.append({
            'counterparty': cpty,
            'n_trades': len(trades),
            'MTM_cr': mtm_total,
            'RC_cr': ead_result['RC'],
            'PFE_cr': ead_result['PFE'],
            'EAD_cr': ead_result['EAD'],
            'risk_weight': rw,
            'RWA_cr': rwa,
            'capital_req_cr': capital,
            'margined': margined,
        })

    return pd.DataFrame(results)
