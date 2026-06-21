"""
CDS Curve Bootstrapper.

Implements proper iterative bootstrapping of a piecewise-constant hazard
rate term structure from a market CDS spread curve.

Methodology (standard market convention):
    At each tenor T_i, the CDS par spread s(T_i) satisfies:
        Protection Leg PV = Premium Leg PV

    Protection Leg PV = LGD × Σⱼ [SP(t_{j-1}) - SP(t_j)] × DF(t_j)

    Premium Leg PV = s × Σⱼ [SP(t_j) × δ_j × DF(t_j)]
                    + s × Σⱼ [(SP(t_{j-1}) - SP(t_j)) × δ_j/2 × DF(t_j)]
                    (accrual on default — the second term)

    Hazard rates are piecewise-constant between tenor nodes.
    At each node i, h_i is solved such that the above equality holds,
    keeping h_1, ..., h_{i-1} fixed (the bootstrap property).

    SP(t) = exp(-Σⱼ h_j × Δt_j) for t in bucket j.

Unlike the simplified h = s / LGD formula (which only works for a flat curve
and ignores the time-value of money), this properly accounts for discounting
and the term structure of default probabilities.
"""

import numpy as np
from scipy.optimize import brentq
from typing import List, Optional
from src.curves.ois_curve import OISCurve


class CDSBootstrapper:
    """
    Iterative CDS bootstrapper producing a piecewise-constant hazard rate
    term structure from market CDS par spreads.

    Attributes:
        tenors: Tenor nodes in years (e.g. [1, 2, 3, 5, 7, 10]).
        spreads_bps: Market CDS par spreads in basis points at each tenor.
        recovery_rate: Recovery rate assumption (default 0.40).
        ois_curve: OIS discount curve for present-valuing CDS legs.
        hazard_rates: Bootstrapped piecewise-constant hazard rates.
    """

    def __init__(self, tenors: List[float], spreads_bps: List[float],
                 recovery_rate: float = 0.40,
                 ois_curve: Optional[OISCurve] = None):
        """
        Initialise the bootstrapper.

        Args:
            tenors: CDS tenor nodes in years. Must be sorted ascending.
            spreads_bps: Market CDS par spreads in basis points.
            recovery_rate: Recovery rate (0 to 1). LGD = 1 - recovery_rate.
            ois_curve: OIS curve for discounting. If None, uses flat 7% rate.
        """
        self.tenors = np.array(sorted(tenors), dtype=float)
        self.spreads = np.array(spreads_bps, dtype=float) / 10000.0
        self.recovery_rate = recovery_rate
        self.lgd = 1.0 - recovery_rate
        self.ois_curve = ois_curve

        assert len(self.tenors) == len(self.spreads), \
            "tenors and spreads_bps must have the same length"

        self.hazard_rates = self._bootstrap()

    def _df(self, t: float) -> float:
        """Risk-free discount factor at t (from OIS curve or flat 7%)."""
        if self.ois_curve is not None:
            return self.ois_curve.df(t)
        return np.exp(-0.07 * t)  # Flat 7% fallback

    def _survival_prob(self, t: float) -> float:
        """
        Compute survival probability to t using bootstrapped hazard rates.

        SP(t) = exp(-Σⱼ h_j × min(t, T_j) - max(0, t - T_{j-1}))
        """
        if t <= 0:
            return 1.0

        sp = 1.0
        t_prev = 0.0
        for i, T_i in enumerate(self.tenors):
            if i >= len(self.hazard_rates):
                break
            dt = min(t, T_i) - t_prev
            if dt <= 0:
                break
            sp *= np.exp(-self.hazard_rates[i] * dt)
            t_prev = T_i
            if t <= T_i:
                break

        return sp

    def _cds_pv(self, h_new: float, tenor_idx: int, spread: float) -> float:
        """
        Compute the net PV of a CDS at tenor_idx given a trial hazard rate h_new.

        Returns zero when the CDS is priced at par (objective function for solver).
        """
        # Temporarily set the new hazard rate for this bucket
        h_backup = self.hazard_rates[tenor_idx] if tenor_idx < len(self.hazard_rates) else None
        if tenor_idx < len(self.hazard_rates):
            self.hazard_rates[tenor_idx] = h_new
        else:
            self.hazard_rates = np.append(self.hazard_rates, h_new)

        T = self.tenors[tenor_idx]
        n_steps = max(4 * int(T), 4)  # quarterly steps minimum
        step_dates = np.linspace(0, T, n_steps + 1)[1:]  # exclude t=0

        protection_pv = 0.0
        premium_pv = 0.0
        accrual_pv = 0.0

        sp_prev = 1.0
        t_prev = 0.0

        for t_j in step_dates:
            sp_j = self._survival_prob(t_j)
            df_j = self._df(t_j)
            delta_j = t_j - t_prev
            d_pd = sp_prev - sp_j         # marginal default probability

            protection_pv += self.lgd * d_pd * df_j
            premium_pv += sp_j * delta_j * df_j
            accrual_pv += d_pd * (delta_j / 2.0) * df_j  # accrual on default

            sp_prev = sp_j
            t_prev = t_j

        net_pv = protection_pv - spread * (premium_pv + accrual_pv)

        # Restore
        if h_backup is not None:
            self.hazard_rates[tenor_idx] = h_backup
        elif tenor_idx < len(self.hazard_rates):
            self.hazard_rates = self.hazard_rates[:-1]

        return net_pv

    def _bootstrap(self) -> np.ndarray:
        """
        Bootstrap piecewise-constant hazard rates iteratively.

        Returns:
            Array of hazard rates, one per tenor bucket.
        """
        n = len(self.tenors)
        self.hazard_rates = np.zeros(n)

        for i in range(n):
            spread_i = self.spreads[i]

            # Simple initial guess: h ≈ s / LGD
            h_guess = spread_i / self.lgd

            try:
                # Brent's method: find h such that CDS net PV = 0
                h_solved = brentq(
                    lambda h: self._cds_pv(h, i, spread_i),
                    a=1e-6,
                    b=min(h_guess * 10, 0.99),
                    xtol=1e-8,
                    maxiter=100,
                )
            except (ValueError, RuntimeError):
                # Fallback to flat approximation
                h_solved = h_guess

            self.hazard_rates[i] = h_solved

        return self.hazard_rates

    def survival_probability(self, t: float) -> float:
        """Survival probability to time t using bootstrapped curve."""
        return self._survival_prob(t)

    def hazard_rate_at(self, t: float) -> float:
        """Piecewise-constant hazard rate at time t."""
        for i, T_i in enumerate(self.tenors):
            if t <= T_i:
                return float(self.hazard_rates[i])
        return float(self.hazard_rates[-1])

    def default_probability(self, t1: float, t2: float) -> float:
        """Marginal default probability in [t1, t2]."""
        return self.survival_probability(t1) - self.survival_probability(t2)

    def to_flat_hazard_rate(self) -> float:
        """
        Return a single flat (5Y-equivalent) hazard rate for compatibility
        with the existing CreditCurve class in src/xva/cva.py.

        Uses the 5Y tenor if available, otherwise the longest tenor.
        """
        t_target = 5.0
        idx = np.argmin(np.abs(self.tenors - t_target))
        # Back-solve flat h from 5Y survival prob
        sp5 = self.survival_probability(t_target)
        if sp5 > 1e-10:
            return -np.log(sp5) / t_target
        return float(self.hazard_rates[idx])

    def to_summary_dataframe(self) -> 'pd.DataFrame':
        """Export bootstrapped curve to a DataFrame."""
        import pandas as pd
        rows = []
        for i, T in enumerate(self.tenors):
            rows.append({
                'tenor_years': T,
                'cds_spread_bps': self.spreads[i] * 10000,
                'hazard_rate': self.hazard_rates[i],
                'hazard_rate_pct': self.hazard_rates[i] * 100,
                'survival_prob': self.survival_probability(T),
                'cumulative_pd': 1.0 - self.survival_probability(T),
            })
        return pd.DataFrame(rows)
