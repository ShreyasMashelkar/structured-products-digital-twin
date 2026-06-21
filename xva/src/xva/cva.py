"""
CVA (Credit Valuation Adjustment) Engine.

Computes unilateral CVA, DVA, and bilateral CVA for counterparties
using bootstrapped hazard rate curves from synthetic CDS spreads.

CVA = -LGD × Σᵢ [EE(tᵢ) × ΔPD(tᵢ) × DF(tᵢ)]

where:
    LGD = Loss Given Default = 1 - Recovery Rate
    EE(tᵢ) = Expected Exposure at time tᵢ
    ΔPD(tᵢ) = Probability of default in period [tᵢ₋₁, tᵢ]
    DF(tᵢ) = Risk-free discount factor at time tᵢ
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, List
from src.curves.ois_curve import OISCurve
from src.curves.credit_curve_bootstrapper import CDSBootstrapper

def build_credit_curve_from_cds(tenors: List[float], spreads_bps: List[float],
                                recovery_rate: float, ois_curve: OISCurve) -> 'TermStructureCreditCurve':
    """
    Build a TermStructureCreditCurve by bootstrapping CDS spreads to capture the full term structure.
    """
    bootstrapper = CDSBootstrapper(tenors, spreads_bps, recovery_rate, ois_curve)
    return TermStructureCreditCurve(bootstrapper)


class TermStructureCreditCurve:
    """
    Credit curve built from a full CDS bootstrapper, preserving the term structure.
    
    Exposes the same interface as CreditCurve but uses piecewise-constant
    hazard rates from the bootstrapper.
    """
    
    def __init__(self, bootstrapper: CDSBootstrapper):
        self._bootstrapper = bootstrapper
        self.recovery_rate = bootstrapper.recovery_rate
        self.lgd = 1.0 - self.recovery_rate
        # Flat equivalent at 5Y for display purposes only
        self.hazard_rate = bootstrapper.to_flat_hazard_rate()
        
    def survival_probability(self, t: float) -> float:
        return self._bootstrapper.survival_probability(t)
        
    def survival_probability_array(self, t_array: np.ndarray) -> np.ndarray:
        # Note: survival_probability might be scalar, so we vectorize it
        return np.array([self.survival_probability(t) for t in t_array])
        
    def default_probability(self, t1: float, t2: float) -> float:
        return self._bootstrapper.default_probability(t1, t2)
        
    def cumulative_default_probability(self, t: float) -> float:
        return 1.0 - self.survival_probability(t)
        
    def shift(self, shock_bps: float) -> 'TermStructureCreditCurve':
        shifted_spreads = [s * 10000.0 + shock_bps for s in self._bootstrapper.spreads]
        new_bootstrapper = CDSBootstrapper(
            self._bootstrapper.tenors,
            shifted_spreads,
            self._bootstrapper.recovery_rate,
            self._bootstrapper.ois_curve
        )
        return TermStructureCreditCurve(new_bootstrapper)


class CreditCurve:
    """
    Credit curve built from CDS spread and recovery rate.

    Provides hazard rates, survival probabilities, and default
    probabilities for CVA computation.

    Attributes:
        cds_spread: CDS spread in absolute terms (e.g. 0.005 for 50bps).
        recovery_rate: Expected recovery rate (typically 0.40).
        hazard_rate: Implied constant hazard rate.
    """

    def __init__(self, cds_spread_bps: float, recovery_rate: float = 0.40):
        """
        Build a flat hazard rate curve from CDS spread.

        Args:
            cds_spread_bps: CDS spread in basis points.
            recovery_rate: Recovery rate (0 to 1).
        """
        self.cds_spread = cds_spread_bps / 10000.0
        self.recovery_rate = recovery_rate
        self.lgd = 1.0 - recovery_rate

        # Flat hazard rate: h = s / (1 - R)
        self.hazard_rate = self.cds_spread / self.lgd

    def survival_probability(self, t: float) -> float:
        """
        Survival probability to time t.

        SP(t) = exp(-h × t)

        Args:
            t: Time in years.

        Returns:
            Survival probability.
        """
        return np.exp(-self.hazard_rate * t)

    def survival_probability_array(self, t_array: np.ndarray) -> np.ndarray:
        """Vectorized survival probability."""
        return np.exp(-self.hazard_rate * t_array)

    def default_probability(self, t1: float, t2: float) -> float:
        """
        Probability of default in the interval [t1, t2].

        PD(t1, t2) = SP(t1) - SP(t2)

        Args:
            t1: Start of period.
            t2: End of period.

        Returns:
            Marginal default probability.
        """
        return self.survival_probability(t1) - self.survival_probability(t2)

    def cumulative_default_probability(self, t: float) -> float:
        """Cumulative probability of default by time t."""
        return 1.0 - self.survival_probability(t)

    def shift(self, shock_bps: float) -> 'CreditCurve':
        """
        Return a new CreditCurve with a shifted CDS spread.

        Args:
            shock_bps: Spread shock in basis points.

        Returns:
            New CreditCurve with shifted spread.
        """
        new_spread = (self.cds_spread * 10000 + shock_bps)
        return CreditCurve(cds_spread_bps=max(new_spread, 1.0),
                           recovery_rate=self.recovery_rate)


class CVAEngine:
    """
    CVA/DVA computation engine.

    Computes credit valuation adjustments using exposure profiles
    from Monte Carlo simulation and credit curves from CDS data.
    """

    def __init__(self, ois_curve: OISCurve):
        """
        Initialise the CVA engine.

        Args:
            ois_curve: OIS discount curve for present-valuing default losses.
        """
        self.ois_curve = ois_curve

    def compute_cva(self, ee_profile: np.ndarray,
                    time_grid: np.ndarray,
                    credit_curve: CreditCurve) -> float:
        """
        Compute unilateral CVA.

        CVA = -LGD × Σᵢ [EE(tᵢ) × ΔPD(tᵢ) × DF(tᵢ)]

        Note: CVA is returned as a positive number representing the
        cost of counterparty credit risk.

        Args:
            ee_profile: Expected Exposure at each time point.
            time_grid: Time grid matching the EE profile.
            credit_curve: Counterparty credit curve.

        Returns:
            CVA value in ₹ Crores (positive = cost).
        """
        lgd = credit_curve.lgd
        cva = 0.0

        for i in range(1, len(time_grid)):
            t_prev = time_grid[i - 1]
            t_curr = time_grid[i]

            ee_mid = 0.5 * (ee_profile[i - 1] + ee_profile[i])
            delta_pd = credit_curve.default_probability(t_prev, t_curr)
            df = self.ois_curve.df(t_curr)

            cva += ee_mid * delta_pd * df

        return lgd * cva

    def compute_dva(self, ene_profile: np.ndarray,
                    time_grid: np.ndarray,
                    own_credit_curve: CreditCurve) -> float:
        """
        Compute DVA (Debit Valuation Adjustment).

        DVA = -LGD_own × Σᵢ [ENE(tᵢ) × ΔPD_own(tᵢ) × DF(tᵢ)]

        DVA represents the benefit from own credit risk.

        Args:
            ene_profile: Expected Negative Exposure at each time point.
                         (Should be negative values.)
            time_grid: Time grid.
            own_credit_curve: Bank's own credit curve.

        Returns:
            DVA value in ₹ Crores (positive = benefit).
        """
        lgd = own_credit_curve.lgd
        dva = 0.0

        for i in range(1, len(time_grid)):
            t_prev = time_grid[i - 1]
            t_curr = time_grid[i]

            # ENE is negative, take absolute value
            ene_mid = 0.5 * (abs(ene_profile[i - 1]) + abs(ene_profile[i]))
            delta_pd = own_credit_curve.default_probability(t_prev, t_curr)
            df = self.ois_curve.df(t_curr)

            dva += ene_mid * delta_pd * df

        return lgd * dva

    def compute_bilateral_cva(self, ee_profile: np.ndarray,
                               ene_profile: np.ndarray,
                               time_grid: np.ndarray,
                               cpty_credit_curve: CreditCurve,
                               own_credit_curve: CreditCurve) -> Dict[str, float]:
        """
        Compute bilateral CVA = Unilateral CVA - DVA.

        Args:
            ee_profile: Expected Exposure profile.
            ene_profile: Expected Negative Exposure profile.
            time_grid: Time grid.
            cpty_credit_curve: Counterparty credit curve.
            own_credit_curve: Bank's own credit curve.

        Returns:
            Dictionary with 'CVA', 'DVA', 'Bilateral_CVA'.
        """
        cva = self.compute_cva(ee_profile, time_grid, cpty_credit_curve)
        dva = self.compute_dva(ene_profile, time_grid, own_credit_curve)

        return {
            'CVA': cva,
            'DVA': dva,
            'Bilateral_CVA': cva - dva,
        }

    def cva_sensitivity(self,
                        ee_profile: np.ndarray,
                        time_grid: np.ndarray,
                        credit_curve: 'CreditCurve',
                        shock_bps: float = 1.0) -> float:
        """
        CVA sensitivity to a 1bp parallel shift in CDS spread (alias for cs01).

        Args:
            ee_profile:   EE profile.
            time_grid:    Time grid.
            credit_curve: Base credit curve.
            shock_bps:    Spread bump size in bps.

        Returns:
            Change in CVA for a 1bp spread widening (₹ Cr).
        """
        cva_base  = self.compute_cva(ee_profile, time_grid, credit_curve)
        shifted   = credit_curve.shift(shock_bps)
        cva_shock = self.compute_cva(ee_profile, time_grid, shifted)
        return cva_shock - cva_base

    def cs01(self,
             ee_profile: np.ndarray,
             time_grid: np.ndarray,
             credit_curve: 'CreditCurve',
             bump_bps: float = 1.0) -> float:
        """
        CS01: Change in CVA for a 1bp widening in CDS spread.

        CS01 = CVA(s + 1bp) - CVA(s)

        Positive CS01 means CVA increases when spreads widen — the
        primary credit hedge ratio used by CVA desks.

        Args:
            ee_profile:   Expected Exposure profile.
            time_grid:    Time grid.
            credit_curve: Counterparty credit curve.
            bump_bps:     Bump size in bps (default 1bp).

        Returns:
            CS01 in ₹ Crores per basis point.
        """
        return self.cva_sensitivity(ee_profile, time_grid, credit_curve, bump_bps)

    def ir01(self,
             ee_profile: np.ndarray,
             time_grid: np.ndarray,
             credit_curve: 'CreditCurve',
             bump_bps: float = 1.0) -> float:
        """
        IR01: Change in CVA for a 1bp parallel shift in the OIS curve.

        When rates rise, discount factors fall, reducing PV of future
        expected losses → CVA decreases → IR01 is typically negative.

        This is the discount-factor IR01 only (standard CVA desk reportable).
        Full IR01 including EE re-simulation is not computed here.

        Args:
            ee_profile:   Expected Exposure profile.
            time_grid:    Time grid.
            credit_curve: Counterparty credit curve.
            bump_bps:     Bump size in bps (default 1bp).

        Returns:
            IR01 in ₹ Crores per basis point.
        """
        cva_base    = self.compute_cva(ee_profile, time_grid, credit_curve)
        bumped_ois  = OISCurve(
            self.ois_curve.tenors,
            self.ois_curve.rates + bump_bps / 10000.0
        )
        cva_bumped  = CVAEngine(bumped_ois).compute_cva(
            ee_profile, time_grid, credit_curve
        )
        return (cva_bumped - cva_base) / bump_bps

    def cva_sensitivity_grid(self,
                              ee_profile: np.ndarray,
                              ene_profile: np.ndarray,
                              time_grid: np.ndarray,
                              credit_curve: 'CreditCurve',
                              own_curve: 'CreditCurve') -> dict:
        """
        Full CVA/DVA sensitivity grid for daily CCR desk risk reporting.

        Returns a complete risk pack:
            CVA, DVA, Bilateral_CVA
            CS01_CVA:  CVA per 1bp counterparty spread widening
            CS01_DVA:  DVA per 1bp own spread widening
            IR01_CVA:  CVA per 1bp rate rise (discount only)
            IR01_DVA:  DVA per 1bp rate rise (discount only)
            CDS_Gamma: Second-order credit sensitivity (₹ Cr/bp²)

        Args:
            ee_profile:   Expected Exposure profile.
            ene_profile:  Expected Negative Exposure profile.
            time_grid:    Time grid.
            credit_curve: Counterparty credit curve.
            own_curve:    Bank's own credit curve (for DVA).

        Returns:
            Dictionary of risk sensitivities in ₹ Cr/bp.
        """
        bilateral = self.compute_bilateral_cva(
            ee_profile, ene_profile, time_grid, credit_curve, own_curve
        )

        cs01_cva = self.cs01(ee_profile, time_grid, credit_curve)

        # CS01 on DVA (own spread)
        dva_base    = self.compute_cva(-ene_profile, time_grid, own_curve)
        dva_bumped  = self.compute_cva(-ene_profile, time_grid, own_curve.shift(1.0))
        cs01_dva    = dva_bumped - dva_base

        ir01_cva = self.ir01(ee_profile, time_grid, credit_curve)

        # IR01 on DVA
        bumped_ois = OISCurve(self.ois_curve.tenors,
                               self.ois_curve.rates + 1.0/10000.0)
        ir01_dva = (CVAEngine(bumped_ois).compute_cva(-ene_profile, time_grid, own_curve)
                    - self.compute_cva(-ene_profile, time_grid, own_curve))

        # CDS Gamma: second-order sensitivity
        cva_up    = self.compute_cva(ee_profile, time_grid, credit_curve.shift(1.0))
        cva_dn    = self.compute_cva(ee_profile, time_grid, credit_curve.shift(-1.0))
        cds_gamma = cva_up - 2*bilateral['CVA'] + cva_dn

        return {
            'CVA':           bilateral['CVA'],
            'DVA':           bilateral['DVA'],
            'Bilateral_CVA': bilateral['Bilateral_CVA'],
            'CS01_CVA':      cs01_cva,
            'CS01_DVA':      cs01_dva,
            'IR01_CVA':      ir01_cva,
            'IR01_DVA':      ir01_dva,
            'CDS_Gamma':     cds_gamma,
        }


def compute_portfolio_cva(exposure_metrics: Dict,
                          counterparty_data: pd.DataFrame,
                          ois_curve: OISCurve,
                          own_cds_bps: float = 40.0) -> pd.DataFrame:
    """
    Compute CVA/DVA for each counterparty in the portfolio.

    Args:
        exposure_metrics: Dict mapping counterparty to exposure metrics.
        counterparty_data: DataFrame with counterparty credit data.
        ois_curve: OIS discount curve.
        own_cds_bps: Bank's own CDS spread in bps.

    Returns:
        DataFrame with CVA/DVA results per counterparty.
    """
    engine = CVAEngine(ois_curve)
    own_curve = CreditCurve(own_cds_bps)

    results = []

    for _, row in counterparty_data.iterrows():
        cpty_name = row['counterparty']
        if cpty_name not in exposure_metrics:
            continue

        metrics = exposure_metrics[cpty_name]
        tenors = [1.0, 2.0, 3.0, 5.0, 7.0]
        spreads = [row['cds_spread_bps']] * 5
        cpty_curve = build_credit_curve_from_cds(
            tenors=tenors,
            spreads_bps=spreads,
            recovery_rate=row['recovery_rate'],
            ois_curve=ois_curve
        )

        time_grid = metrics['time_grid']
        ee = metrics['EE']
        ene = metrics.get('ENE', np.zeros_like(ee))

        bilateral = engine.compute_bilateral_cva(
            ee, ene, time_grid, cpty_curve, own_curve
        )

        results.append({
            'counterparty': cpty_name,
            'cds_spread_bps': row['cds_spread_bps'],
            'recovery_rate': row['recovery_rate'],
            'hazard_rate_pct': cpty_curve.hazard_rate * 100,
            'survival_5y': cpty_curve.survival_probability(5.0),
            'CVA_cr': bilateral['CVA'],
            'DVA_cr': bilateral['DVA'],
            'Bilateral_CVA_cr': bilateral['Bilateral_CVA'],
        })

    return pd.DataFrame(results)
