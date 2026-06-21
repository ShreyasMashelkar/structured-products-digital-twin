"""
INR Interest Rate Swap Pricing Engine.

Prices INR IRS and OIS swaps using the bootstrapped OIS discount curve.
Supports:
- Receive Fixed and Pay Fixed directions
- Mark-to-Market (MTM) valuation
- Par swap rate calculation
- DV01, PV01, Key Rate DV01 risk sensitivities
- Cash flow schedule generation

Day count convention: Actual/365 (Indian market standard for IRS/OIS).
Fixed leg payment frequency: Annual (standard for INR IRS).
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple

from src.curves.ois_curve import OISCurve


class SwapPricer:
    """
    INR Interest Rate Swap Pricer.

    Prices a single swap (IRS or OIS) against an OIS discount curve.
    Generates cash flows, computes MTM, and calculates risk sensitivities.

    Attributes:
        notional: Notional amount in Crores (₹).
        fixed_rate: Fixed coupon rate.
        maturity: Maturity in years.
        direction: 'Receive Fixed' or 'Pay Fixed'.
        payment_freq: Annual payment frequency (1 = annual, 2 = semi-annual).
    """

    def __init__(self, notional: float, fixed_rate: float,
                 maturity: float, direction: str = 'Receive Fixed',
                 payment_freq: int = 1):
        """
        Initialise the swap pricer.

        Args:
            notional: Notional in ₹ Crores.
            fixed_rate: Fixed leg rate (e.g. 0.07 for 7%).
            maturity: Maturity in years.
            direction: 'Receive Fixed' or 'Pay Fixed'.
            payment_freq: Payments per year (1=annual, 2=semi-annual).
        """
        self.notional = notional
        self.fixed_rate = fixed_rate
        self.maturity = maturity
        self.direction = direction
        self.payment_freq = payment_freq

        # Generate payment dates
        self.payment_dates = self._generate_payment_dates()
        self.accrual_fractions = self._compute_accrual_fractions()

    def _generate_payment_dates(self) -> np.ndarray:
        """Generate fixed leg payment dates in years from today."""
        period = 1.0 / self.payment_freq
        dates = np.arange(period, self.maturity + period / 2, period)
        # Ensure last date aligns with maturity
        if len(dates) > 0:
            dates[-1] = self.maturity
        return dates

    def _compute_accrual_fractions(self) -> np.ndarray:
        """Compute day count fractions for each payment period."""
        dates_with_start = np.concatenate([[0.0], self.payment_dates])
        return np.diff(dates_with_start)

    def fixed_leg_pv(self, curve: OISCurve) -> float:
        """
        Compute present value of the fixed leg.

        Fixed Leg PV = K × N × Σ[δᵢ × DF(tᵢ)]

        Args:
            curve: OIS discount curve.

        Returns:
            Fixed leg present value in ₹ Crores.
        """
        dfs = curve.df_array(self.payment_dates)
        annuity = np.sum(self.accrual_fractions * dfs)
        return self.fixed_rate * self.notional * annuity

    def float_leg_pv(self, curve: OISCurve, projection_curve: Optional[OISCurve] = None) -> float:
        """
        Compute present value of the floating leg.

        If a projection_curve is provided (Multi-Curve Framework), computes explicitly:
        Float Leg PV = N × Σ[δᵢ × Fwd(tᵢ) × DF(tᵢ)]

        If no projection_curve is provided (Single Curve Framework):
        Float Leg PV = N × [DF(t_start) - DF(t_end)]

        Args:
            curve: OIS discount curve.
            projection_curve: Curve to project forward rates.

        Returns:
            Float leg present value in ₹ Crores.
        """
        if projection_curve is None:
            # Single curve par floater shortcut
            df_start = curve.df(0.0)  # = 1.0
            df_end = curve.df(self.maturity)
            return self.notional * (df_start - df_end)
        else:
            # Multi-curve explicit projection
            float_pv = 0.0
            dates_with_start = np.concatenate([[0.0], self.payment_dates])
            dfs = curve.df_array(self.payment_dates)
            for i in range(len(self.payment_dates)):
                t1 = dates_with_start[i]
                t2 = dates_with_start[i + 1]
                fwd = projection_curve.forward_rate(t1, t2)
                float_pv += fwd * self.accrual_fractions[i] * dfs[i]
            return self.notional * float_pv

    def annuity(self, curve: OISCurve) -> float:
        """
        Compute the annuity factor (PV of 1bp on fixed leg).

        Annuity = Σ[δᵢ × DF(tᵢ)]

        Args:
            curve: OIS discount curve.

        Returns:
            Annuity factor.
        """
        dfs = curve.df_array(self.payment_dates)
        return np.sum(self.accrual_fractions * dfs)

    def mtm(self, curve: OISCurve, projection_curve: Optional[OISCurve] = None) -> float:
        """
        Compute the Mark-to-Market of the swap.

        Receive Fixed: MTM = Fixed PV - Float PV
        Pay Fixed:     MTM = Float PV - Fixed PV

        Args:
            curve: OIS discount curve.
            projection_curve: Optional forward projection curve.

        Returns:
            MTM value in ₹ Crores.
        """
        fixed_pv = self.fixed_leg_pv(curve)
        float_pv = self.float_leg_pv(curve, projection_curve)

        if self.direction == 'Receive Fixed':
            return fixed_pv - float_pv
        else:
            return float_pv - fixed_pv

    def par_rate(self, curve: OISCurve, projection_curve: Optional[OISCurve] = None) -> float:
        """
        Compute the par swap rate (rate that makes MTM = 0).

        Par Rate = Float PV / Annuity

        Args:
            curve: OIS discount curve.
            projection_curve: Optional forward projection curve.

        Returns:
            Par swap rate.
        """
        ann = self.annuity(curve)
        if ann < 1e-12:
            return 0.0

        if projection_curve is None:
            df_start = curve.df(0.0)
            df_end = curve.df(self.maturity)
            return (df_start - df_end) / ann
        else:
            # Multi-curve explicit float pv (divided by notional)
            float_pv = self.float_leg_pv(curve, projection_curve)
            return float_pv / (self.notional * ann)

    def dv01(self, curve: OISCurve, bump_bps: float = 1.0, projection_curve: Optional[OISCurve] = None) -> float:
        """
        Compute DV01: change in MTM for a 1bp parallel shift.

        DV01 = MTM(curve + 1bp) - MTM(curve)

        Args:
            curve: Base OIS curve.
            bump_bps: Bump size in basis points (default 1bp).
            projection_curve: Optional forward projection curve.

        Returns:
            DV01 in ₹ Crores.
        """
        mtm_base = self.mtm(curve, projection_curve)
        curve_up = curve.shift(bump_bps)
        proj_up = projection_curve.shift(bump_bps) if projection_curve else None
        mtm_up = self.mtm(curve_up, proj_up)
        return mtm_up - mtm_base

    def pv01(self, curve: OISCurve) -> float:
        """
        Compute PV01: present value of 1bp on the fixed leg.

        PV01 = N × Annuity × 0.0001

        Args:
            curve: OIS discount curve.

        Returns:
            PV01 in ₹ Crores.
        """
        return self.notional * self.annuity(curve) * 0.0001

    def key_rate_dv01(self, curve: OISCurve,
                      bump_bps: float = 1.0) -> Dict[str, float]:
        """
        Compute Key Rate DV01: DV01 attributed to each tenor bucket.

        Bumps each curve node individually and measures the MTM change.

        Args:
            curve: Base OIS curve.
            bump_bps: Bump size in basis points.

        Returns:
            Dictionary mapping tenor label to key rate DV01 (₹ Cr).
        """
        from src.data_ingestion.market_data import OIS_TENOR_LABELS

        mtm_base = self.mtm(curve)
        kr_dv01 = {}

        for i in range(len(curve.tenors)):
            curve_bumped = curve.bump_tenor(i, bump_bps)
            mtm_bumped = self.mtm(curve_bumped)
            label = OIS_TENOR_LABELS[i] if i < len(OIS_TENOR_LABELS) else f'{curve.tenors[i]:.1f}Y'
            kr_dv01[label] = mtm_bumped - mtm_base

        return kr_dv01

    def gamma(self, curve: OISCurve, bump_bps: float = 1.0) -> float:
        """
        Compute Gamma: second-order rate sensitivity.

        Gamma = [MTM(+bump) + MTM(-bump) - 2×MTM(base)] / bump²

        Args:
            curve: Base OIS curve.
            bump_bps: Bump size in basis points.

        Returns:
            Gamma in ₹ Crores per (bp)².
        """
        mtm_base = self.mtm(curve)
        curve_up = curve.shift(bump_bps)
        curve_down = curve.shift(-bump_bps)
        mtm_up = self.mtm(curve_up)
        mtm_down = self.mtm(curve_down)

        bump = bump_bps / 10000.0
        return (mtm_up + mtm_down - 2 * mtm_base) / (bump ** 2)

    def cash_flow_schedule(self, curve: OISCurve) -> pd.DataFrame:
        """
        Generate the full cash flow schedule for the swap.

        Args:
            curve: OIS discount curve.

        Returns:
            DataFrame with columns: period, payment_date_years,
            accrual_fraction, fixed_cf, float_cf, net_cf, df, pv_net_cf
        """
        dfs = curve.df_array(self.payment_dates)
        fixed_cfs = self.fixed_rate * self.notional * self.accrual_fractions

        # Floating cash flows based on forward rates
        float_cfs = np.zeros(len(self.payment_dates))
        dates_with_start = np.concatenate([[0.0], self.payment_dates])
        for i in range(len(self.payment_dates)):
            t1 = dates_with_start[i]
            t2 = dates_with_start[i + 1]
            fwd = curve.forward_rate(t1, t2)
            float_cfs[i] = fwd * self.notional * self.accrual_fractions[i]

        if self.direction == 'Receive Fixed':
            net_cfs = fixed_cfs - float_cfs
        else:
            net_cfs = float_cfs - fixed_cfs

        return pd.DataFrame({
            'period': np.arange(1, len(self.payment_dates) + 1),
            'payment_date_years': self.payment_dates,
            'accrual_fraction': self.accrual_fractions,
            'fixed_cf_cr': fixed_cfs,
            'float_cf_cr': float_cfs,
            'net_cf_cr': net_cfs,
            'discount_factor': dfs,
            'pv_net_cf_cr': net_cfs * dfs,
        })

    def risk_summary(self, curve: OISCurve, projection_curve: Optional[OISCurve] = None) -> Dict[str, float]:
        """
        Compute a complete risk summary for the swap.

        Returns:
            Dictionary with MTM, par_rate, DV01, PV01, gamma.
        """
        return {
            'mtm_cr': self.mtm(curve, projection_curve),
            'par_rate': self.par_rate(curve, projection_curve),
            'dv01_cr': self.dv01(curve, 1.0, projection_curve),
            'pv01_cr': self.pv01(curve),
            'gamma': self.gamma(curve), # gamma is typically approximated, keeping base signature
            'notional_cr': self.notional,
            'fixed_rate': self.fixed_rate,
            'maturity_years': self.maturity,
            'direction': self.direction,
        }


def price_portfolio(portfolio_df: pd.DataFrame,
                    curve: OISCurve,
                    projection_curve: Optional[OISCurve] = None) -> pd.DataFrame:
    """
    Price an entire portfolio of swaps.

    Args:
        portfolio_df: DataFrame with columns: trade_id, notional_cr,
                      fixed_rate, maturity_years, direction.
        curve: OIS discount curve.
        projection_curve: Optional forward projection curve.

    Returns:
        DataFrame with pricing results for each trade.
    """
    results = []

    for _, trade in portfolio_df.iterrows():
        pricer = SwapPricer(
            notional=trade['notional_cr'],
            fixed_rate=trade['fixed_rate'],
            maturity=trade['maturity_years'],
            direction=trade['direction'],
        )
        summary = pricer.risk_summary(curve, projection_curve)
        summary['trade_id'] = trade['trade_id']
        summary['counterparty'] = trade['counterparty']
        results.append(summary)

    return pd.DataFrame(results)
