"""
INR OIS Curve Construction Module.

Implements bootstrapping of the INR OIS discount curve from FBIL MIBOR
benchmark rates. Produces discount factors, zero rates, and forward rates
across the full tenor spectrum.

Also includes a G-Sec yield curve builder for sovereign basis analysis.

Methodology:
- Short end (O/N to 3M): Simple deposit rate bootstrapping
- Medium/long end (6M to 10Y): Iterative bootstrapping from par OIS rates
- Interpolation: Log-linear on discount factors (standard market convention)
"""

import numpy as np
from scipy.interpolate import CubicSpline
from typing import Optional, Tuple
import pandas as pd


class OISCurve:
    """
    INR OIS Discount Curve built via bootstrapping from market OIS rates.

    The curve stores discount factors at bootstrapped nodes and provides
    interpolated discount factors, zero rates, and forward rates for
    arbitrary tenors.

    Attributes:
        tenors: Array of tenor points in years.
        rates: Array of market OIS par rates at each tenor.
        discount_factors: Bootstrapped discount factors.
        day_count: Day count convention (Actual/365 for INR).
    """

    def __init__(self, tenors: np.ndarray, rates: np.ndarray,
                 day_count: float = 365.0):
        """
        Construct an OIS curve from market par rates.

        Args:
            tenors: Tenor points in years (must be sorted ascending).
            rates: Market OIS par rates corresponding to each tenor.
            day_count: Day count basis (365 for INR Act/365).
        """
        assert len(tenors) == len(rates), "Tenors and rates must have equal length"
        assert np.all(np.diff(tenors) > 0), "Tenors must be strictly increasing"

        self.tenors = tenors.copy()
        self.rates = rates.copy()
        self.day_count = day_count
        self.discount_factors = self._bootstrap()

        # Pre-compute log-DFs for fast interpolation
        self._log_dfs = np.log(self.discount_factors)

    def _bootstrap(self) -> np.ndarray:
        """
        Bootstrap discount factors from OIS par rates.

        For the short end (< 1Y), treats rates as simple deposit rates:
            DF(T) = 1 / (1 + r * T)

        For the long end (>= 1Y), solves iteratively using the OIS
        par rate relation:
            Par Rate * Σ[δᵢ * DF(tᵢ)] = 1 - DF(T)
            => DF(T) = (1 - Par Rate * Σ[δⱼ * DF(tⱼ)]) / (1 + Par Rate * δ_T)

        Returns:
            Array of discount factors at each tenor node.
        """
        n = len(self.tenors)
        dfs = np.ones(n)

        # Identify the boundary between deposit and swap bootstrapping
        # Use 1Y as the threshold (annual payment frequency for swaps)
        swap_threshold = 0.99  # Just under 1Y

        for i in range(n):
            t = self.tenors[i]
            r = self.rates[i]

            if t < swap_threshold:
                # Simple deposit rate bootstrapping
                dfs[i] = 1.0 / (1.0 + r * t)
            else:
                # Swap bootstrapping with annual fixed payments
                # Generate annual payment dates up to this tenor
                annual_dates = np.arange(1.0, t + 0.001, 1.0)
                if len(annual_dates) == 0 or annual_dates[-1] < t - 0.01:
                    annual_dates = np.append(annual_dates, t)
                else:
                    annual_dates[-1] = t  # Align last date exactly

                # Compute accrual fractions (annual = 1.0 year intervals)
                deltas = np.diff(np.concatenate([[0.0], annual_dates]))

                # Sum of known DF * delta for all periods except the last
                pv_known = 0.0
                for j in range(len(annual_dates) - 1):
                    t_j = annual_dates[j]
                    # Interpolate using already bootstrapped nodes
                    log_df_j = np.interp(t_j, self.tenors[:i], np.log(dfs[:i]))
                    df_j = np.exp(log_df_j)
                    pv_known += deltas[j] * df_j

                # Solve for DF at this tenor
                delta_last = deltas[-1]
                dfs[i] = (1.0 - r * pv_known) / (1.0 + r * delta_last)

                # Safety floor
                dfs[i] = max(dfs[i], 1e-10)

        return dfs

    def df(self, t: float) -> float:
        """
        Return the interpolated discount factor at tenor t.

        Uses log-linear interpolation on discount factors, which is the
        standard market convention ensuring positive DFs and smooth
        forward rates.

        Args:
            t: Tenor in years.

        Returns:
            Discount factor DF(0, t).
        """
        if t <= 0.0:
            return 1.0

        if t < self.tenors[0]:
            # Extrapolate from first point using flat zero rate
            df0 = np.exp(self._log_dfs[0])
            z0 = -np.log(df0) / self.tenors[0]
            return np.exp(-z0 * t)

        if t > self.tenors[-1]:
            # Flat extrapolation beyond last node
            df_last = np.exp(self._log_dfs[-1])
            z_last = -np.log(df_last) / self.tenors[-1]
            return np.exp(-z_last * t)

        # Log-linear interpolation
        log_df = np.interp(t, self.tenors, self._log_dfs)
        return np.exp(log_df)

    def df_array(self, t_array: np.ndarray) -> np.ndarray:
        """Vectorized discount factor computation for an array of tenors."""
        return np.array([self.df(t) for t in t_array])

    def zero_rate(self, t: float) -> float:
        """
        Return the continuously compounded zero rate at tenor t.

            Z(t) = -ln(DF(t)) / t

        Args:
            t: Tenor in years.

        Returns:
            Continuously compounded zero rate.
        """
        if t <= 1e-10:
            return self.rates[0]
        return -np.log(self.df(t)) / t

    def zero_rate_array(self, t_array: np.ndarray) -> np.ndarray:
        """Vectorized zero rate computation."""
        return np.array([self.zero_rate(t) for t in t_array])

    def forward_rate(self, t1: float, t2: float) -> float:
        """
        Return the simply-compounded forward rate between t1 and t2.

            F(t1, t2) = [DF(t1)/DF(t2) - 1] / (t2 - t1)

        Args:
            t1: Start of forward period (years).
            t2: End of forward period (years).

        Returns:
            Simply-compounded forward rate.
        """
        if t2 <= t1:
            raise ValueError(f"t2 ({t2}) must be greater than t1 ({t1})")

        df1 = self.df(t1)
        df2 = self.df(t2)
        return (df1 / df2 - 1.0) / (t2 - t1)

    def instantaneous_forward(self, t: float, dt: float = 1/365) -> float:
        """
        Return the instantaneous forward rate at time t.

        Approximated as the forward rate over a small interval [t, t+dt].

        Args:
            t: Time in years.
            dt: Small interval for approximation.

        Returns:
            Instantaneous forward rate.
        """
        return self.forward_rate(t, t + dt)

    def forward_curve(self, t_array: np.ndarray,
                      period: float = 0.25) -> np.ndarray:
        """
        Compute forward rates for an array of start dates.

        Args:
            t_array: Array of forward start dates in years.
            period: Length of forward period (default 3M = 0.25Y).

        Returns:
            Array of forward rates.
        """
        return np.array([
            self.forward_rate(t, t + period) for t in t_array
        ])

    def shift(self, shock_bps: float) -> 'OISCurve':
        """
        Return a new OISCurve with a parallel shift applied to all rates.

        Args:
            shock_bps: Parallel shift in basis points.

        Returns:
            New OISCurve with shifted rates.
        """
        shifted_rates = self.rates + shock_bps / 10000.0
        return OISCurve(self.tenors, shifted_rates, self.day_count)

    def bump_tenor(self, tenor_idx: int, shock_bps: float) -> 'OISCurve':
        """
        Return a new OISCurve with a single tenor node bumped.

        Used for key rate DV01 calculations.

        Args:
            tenor_idx: Index of the tenor to bump.
            shock_bps: Bump size in basis points.

        Returns:
            New OISCurve with the specified tenor bumped.
        """
        bumped_rates = self.rates.copy()
        bumped_rates[tenor_idx] += shock_bps / 10000.0
        return OISCurve(self.tenors, bumped_rates, self.day_count)

    def to_dataframe(self) -> pd.DataFrame:
        """Export curve data to a DataFrame for display/storage."""
        fwd_rates = np.array([
            self.instantaneous_forward(t) if t > 0.01 else self.rates[0]
            for t in self.tenors
        ])
        return pd.DataFrame({
            'tenor_years': self.tenors,
            'market_rate': self.rates,
            'discount_factor': self.discount_factors,
            'zero_rate': self.zero_rate_array(self.tenors),
            'forward_rate': fwd_rates,
        })


class GSecCurve:
    """
    Indian Government Securities (G-Sec) Yield Curve.

    Builds a sovereign yield curve from T-Bill and G-Sec benchmark yields.
    Uses cubic spline interpolation on zero rates for smooth curve.
    """

    def __init__(self, tenors: np.ndarray, yields: np.ndarray):
        """
        Construct a G-Sec curve from benchmark yields.

        Args:
            tenors: Tenor points in years.
            yields: G-Sec yields (semi-annual compounded by convention,
                    but treated as continuously compounded here for
                    consistency with OIS curve).
        """
        self.tenors = tenors.copy()
        self.yields = yields.copy()

        # Convert to continuously compounded zero rates
        # (approximation: for small rates, semi-annual ≈ continuous)
        self.zero_rates = yields.copy()

        # Cubic spline interpolation on zero rates
        self._spline = CubicSpline(tenors, self.zero_rates,
                                    bc_type='natural')

    def zero_rate(self, t: float) -> float:
        """Interpolated continuously compounded zero rate at tenor t."""
        if t <= 0:
            return float(self.zero_rates[0])
        t_clamped = np.clip(t, self.tenors[0], self.tenors[-1])
        return float(self._spline(t_clamped))

    def df(self, t: float) -> float:
        """Discount factor from the G-Sec curve."""
        if t <= 0:
            return 1.0
        return np.exp(-self.zero_rate(t) * t)

    def spread_over_ois(self, ois_curve: OISCurve,
                        t_array: np.ndarray) -> np.ndarray:
        """
        Compute the G-Sec vs OIS spread (sovereign basis) at each tenor.

        Args:
            ois_curve: The OIS curve for comparison.
            t_array: Tenors at which to compute the spread.

        Returns:
            Array of spreads in absolute terms (not bps).
        """
        gsec_zeros = np.array([self.zero_rate(t) for t in t_array])
        ois_zeros = ois_curve.zero_rate_array(t_array)
        return gsec_zeros - ois_zeros

    def to_dataframe(self) -> pd.DataFrame:
        """Export G-Sec curve to DataFrame."""
        dfs = np.array([self.df(t) for t in self.tenors])
        return pd.DataFrame({
            'tenor_years': self.tenors,
            'yield_rate': self.yields,
            'zero_rate': self.zero_rates,
            'discount_factor': dfs,
        })


def build_curves_from_market_data() -> Tuple[OISCurve, GSecCurve]:
    """
    Convenience function: build both OIS and G-Sec curves from
    the default synthetic market data.

    Returns:
        Tuple of (OISCurve, GSecCurve).
    """
    from src.data_ingestion.market_data import get_ois_market_data, get_gsec_market_data

    ois_data = get_ois_market_data()
    gsec_data = get_gsec_market_data()

    ois_curve = OISCurve(
        tenors=ois_data['tenor_years'].values,
        rates=ois_data['ois_rate'].values
    )

    gsec_curve = GSecCurve(
        tenors=gsec_data['tenor_years'].values,
        yields=gsec_data['yield_rate'].values
    )

    return ois_curve, gsec_curve

def build_dual_curve(base_ois: OISCurve, basis_bps: float) -> OISCurve:
    """Build a projection curve by applying a constant basis spread to the OIS curve."""
    return base_ois.shift(basis_bps)
