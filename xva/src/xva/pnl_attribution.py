"""
Swap PnL Attribution — daily decomposition of IRS mark-to-market change.

Data source: Daily OIS curves from FIMMDA (free, existing market_data.py).
For multi-day backtesting, daily MIBOR history from RBI DBIE [FREE].

Decomposes day-over-day PnL:
  1. Carry        — fixed coupon accrual for one day
  2. Roll-Down    — MTM change as swap moves one day closer to maturity
  3. Delta        — Σ DV01_k × Δrate_k (first-order rate-move PnL)
  4. Gamma        — ½ Σ Γ_k × (Δrate_k)² (convexity)
  5. New Fixing   — floating rate reset effect (MIBOR change)
  6. Unexplained  — total - sum(1..5)

Distinct from XVAAttribution (explains CVA/DVA changes).
Used by Product Control for trader P&L verification.
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, List
from src.curves.ois_curve import OISCurve
from src.data_ingestion.market_data import get_ois_market_data, get_historical_mibor


class SwapPnLAttribution:
    """
    Daily PnL attribution for a plain vanilla INR IRS.

    All curve data sourced from free existing fetchers (FIMMDA, DBIE).
    No paid data required.
    """

    def __init__(self, notional: float, fixed_rate: float,
                 maturity_years: float, pay_freq: float = 0.5):
        """
        Args:
            notional: Swap notional in INR crores
            fixed_rate: Fixed leg rate
            maturity_years: Remaining maturity in years
            pay_freq: Payment frequency in years (0.5 = semi-annual)
        """
        self.notional   = notional
        self.fixed_rate = fixed_rate
        self.maturity   = maturity_years
        self.pay_freq   = pay_freq

    def _price_swap(self, curve: OISCurve, elapsed: float = 0.0) -> float:
        """Price the swap using the given curve. elapsed = days elapsed since inception."""
        remaining = self.maturity - elapsed
        if remaining <= 0:
            return 0.0
        payment_times = np.arange(self.pay_freq, remaining + 1e-6, self.pay_freq)
        if len(payment_times) == 0:
            return 0.0
        dfs = np.array([curve.df(t) for t in payment_times])
        fixed_pv = self.notional * self.fixed_rate * self.pay_freq * np.sum(dfs)
        float_pv = self.notional * (1 - curve.df(remaining))
        return float_pv - fixed_pv

    def _compute_dv01_vector(self, curve: OISCurve, elapsed: float = 0.0,
                              bump_bps: float = 1.0) -> Dict[str, float]:
        """DV01 per tenor bucket by bump-and-reprice. Uses OISCurve.bump_tenor()."""
        base = self._price_swap(curve, elapsed)
        dv01s = {}
        for i, t in enumerate(curve.tenors):
            bumped = curve.bump_tenor(i, bump_bps)
            dv01s[f'{t:.2f}Y'] = (self._price_swap(bumped, elapsed) - base) / bump_bps
        return dv01s

    def _compute_gamma_vector(self, curve: OISCurve, elapsed: float = 0.0,
                               bump_bps: float = 1.0) -> Dict[str, float]:
        """Gamma per tenor bucket: (V(+bump) - 2V + V(-bump)) / bump²."""
        base = self._price_swap(curve, elapsed)
        gammas = {}
        for i, t in enumerate(curve.tenors):
            bumped_up = self._price_swap(curve.bump_tenor(i, +bump_bps), elapsed)
            bumped_dn = self._price_swap(curve.bump_tenor(i, -bump_bps), elapsed)
            gammas[f'{t:.2f}Y'] = (bumped_up - 2*base + bumped_dn) / (bump_bps**2)
        return gammas

    def compute_carry(self, curve: OISCurve, dt_days: float = 1.0) -> float:
        """
        Carry = coupon income for dt_days.
        For a receive-fixed swap: fixed coupon accrual - overnight floating accrual.
        """
        dt = dt_days / 365
        on_rate = curve.zero_rate(dt)
        fixed_accrual    = self.notional * self.fixed_rate * dt
        floating_accrual = self.notional * on_rate * dt
        return fixed_accrual - floating_accrual

    def compute_rolldown(self, curve: OISCurve, dt_days: float = 1.0) -> float:
        """
        Roll-down = MTM change if rate curve stays flat but time advances.
        Price at (maturity - dt) using same curve vs price at maturity.
        """
        dt = dt_days / 365
        price_today    = self._price_swap(curve, 0.0)
        price_tomorrow = self._price_swap(curve, dt)
        return price_tomorrow - price_today

    def compute_delta_pnl(self, curve_t1: OISCurve,
                           curve_t0: OISCurve) -> Dict:
        """
        Delta PnL: Σ DV01_k × Δrate_k using yesterday's DV01s.
        """
        dv01s = self._compute_dv01_vector(curve_t0)
        delta_pnl = {}
        total = 0.0
        for i, (label, dv01) in enumerate(dv01s.items()):
            if i < len(curve_t0.tenors) and i < len(curve_t1.tenors):
                rate_move_bps = (curve_t1.rates[i] - curve_t0.rates[i]) * 10000
                pnl = dv01 * rate_move_bps
                delta_pnl[label] = pnl
                total += pnl
        delta_pnl['_total'] = total
        return delta_pnl

    def compute_gamma_pnl(self, curve_t1: OISCurve,
                           curve_t0: OISCurve) -> float:
        """
        Gamma PnL: ½ × Σ Γ_k × (Δrate_k)²
        """
        gammas = self._compute_gamma_vector(curve_t0)
        total = 0.0
        for i, label in enumerate(gammas):
            if i < len(curve_t0.tenors) and i < len(curve_t1.tenors):
                move = (curve_t1.rates[i] - curve_t0.rates[i]) * 10000
                total += 0.5 * gammas[label] * move**2
        return total

    def compute_fixing_pnl(self, old_fixing: float, new_fixing: float) -> float:
        """
        PnL from MIBOR reset: receive benefit (or pay cost) of rate change.
        Source: RBI DBIE MIBOR history [FREE] via get_historical_mibor().
        """
        n_remaining = int(self.maturity / self.pay_freq)
        return self.notional * (new_fixing - old_fixing) * self.pay_freq * n_remaining

    def full_attribution(self, curve_today: OISCurve,
                          curve_yesterday: OISCurve,
                          old_mibor: Optional[float] = None,
                          new_mibor: Optional[float] = None,
                          dt_days: float = 1.0) -> pd.DataFrame:
        """
        Full daily PnL attribution. Uses FIMMDA OIS curves (free).
        MIBOR fixing from DBIE (free) if provided; else skipped.

        Returns styled attribution DataFrame.
        """
        actual_pnl = (self._price_swap(curve_today)
                      - self._price_swap(curve_yesterday))

        carry   = self.compute_carry(curve_yesterday, dt_days)
        roll    = self.compute_rolldown(curve_yesterday, dt_days)
        delta_d = self.compute_delta_pnl(curve_today, curve_yesterday)
        delta   = delta_d['_total']
        gamma   = self.compute_gamma_pnl(curve_today, curve_yesterday)
        fixing  = (self.compute_fixing_pnl(old_mibor, new_mibor)
                   if old_mibor is not None and new_mibor is not None else 0.0)

        explained   = carry + roll + delta + gamma + fixing
        unexplained = actual_pnl - explained

        rows = [
            ('Carry',        carry,       carry / abs(actual_pnl) * 100 if actual_pnl else 0),
            ('Roll-Down',    roll,         roll / abs(actual_pnl) * 100 if actual_pnl else 0),
            ('Delta',        delta,        delta / abs(actual_pnl) * 100 if actual_pnl else 0),
            ('Gamma',        gamma,        gamma / abs(actual_pnl) * 100 if actual_pnl else 0),
            ('New Fixing',   fixing,       fixing / abs(actual_pnl) * 100 if actual_pnl else 0),
            ('Unexplained',  unexplained,  unexplained / abs(actual_pnl) * 100 if actual_pnl else 0),
            ('TOTAL',        actual_pnl,   100.0),
        ]
        return pd.DataFrame(rows, columns=['Effect', 'PnL (₹ Cr)', '% of Total'])

    @staticmethod
    def build_daily_curve_sequence(n_days: int = 5) -> List[OISCurve]:
        """
        Build a sequence of daily OIS curves from free market data.

        Uses today's FIMMDA curve and replays historical daily moves
        calibrated to actual MIBOR history from RBI DBIE [FREE].
        """
        from src.data_ingestion.market_data import get_ois_market_data, get_historical_mibor
        from src.curves.ois_curve import OISCurve

        ois_df = get_ois_market_data()
        mibor_df = get_historical_mibor(n_days=max(252, n_days + 1))

        # Replay historical daily MIBOR shifts
        mibor_df = mibor_df.sort_values('date').reset_index(drop=True)
        rates = mibor_df['mibor_rate'].values
        shifts = np.diff(rates)[-n_days:]

        curves = []
        tenors = ois_df['tenor_years'].values
        current_rates = ois_df['ois_rate'].values.copy()

        for shift in shifts:
            curves.append(OISCurve(tenors, current_rates.copy()))
            # Parallel shift by historical mibor change
            current_rates = np.maximum(current_rates + shift, 0.001)
            
        # Pad if we didn't have enough history
        while len(curves) < n_days:
            curves.append(OISCurve(tenors, current_rates.copy()))

        return curves
