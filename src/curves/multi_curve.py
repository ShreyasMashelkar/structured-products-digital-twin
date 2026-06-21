"""
Multi-Curve Framework: OIS Discounting + MIBOR Projection.

Creates a dual-curve environment where discounting is strictly OIS,
and forward rates are projected using a distinct MIBOR curve.
Builds on top of the existing `OISCurve` and uses free market data fetchers.
"""

import numpy as np
from typing import Optional
from src.curves.ois_curve import OISCurve
from src.data_ingestion.market_data import get_ois_market_data, get_historical_mibor


class MultiCurveFramework:
    """
    Manages the dual-curve environment required for modern INR valuation.
    Discounting: OIS Curve (from FIMMDA/FBIL)
    Projection: MIBOR Curve (derived via basis over OIS)
    """

    def __init__(self, discount_curve: OISCurve,
                 mibor_curve: OISCurve,
                 basis_bps: Optional[float] = None):
        """
        Args:
            discount_curve: The OIS curve used for all discounting
            mibor_curve: The curve used for projecting MIBOR forwards
            basis_bps: The average basis between the two curves (for reporting)
        """
        self.discount = discount_curve
        self.mibor = mibor_curve
        self.basis_bps = basis_bps

    def df(self, t: float) -> float:
        """Discount factor is strictly from the OIS curve."""
        return self.discount.df(t)

    def forward_rate(self, t1: float, t2: float) -> float:
        """Forward rate is strictly from the MIBOR curve."""
        if t2 <= t1:
            return 0.0
        df1 = self.mibor.df(t1)
        df2 = self.mibor.df(t2)
        return (df1 / df2 - 1.0) / (t2 - t1)

    @classmethod
    def build_from_market_data(cls) -> 'MultiCurveFramework':
        """
        Builds the multi-curve framework using only FREE data sources.

        Data Sources:
          1. OIS curve: Fetched live from FIMMDA via existing market_data.py
          2. O/N MIBOR: Fetched live from RBI DBIE via existing market_data.py
          3. Term Basis: Since Term MIBOR / OIS basis swaps are not freely
             published via API, we use a historically parameterized term
             structure for the basis, anchored to the true DBIE O/N spread.
        """
        # 1. Get real OIS Curve
        ois_df = get_ois_market_data()
        ois_curve = OISCurve(tenors=ois_df['tenor_years'].values,
                             rates=ois_df['ois_rate'].values)

        # 2. Get real O/N MIBOR and compute spot basis
        mibor_history = get_historical_mibor(n_days=1)
        if mibor_history.empty:
            spot_mibor = ois_curve.rates[0] + 0.0015  # Fallback: +15bps
        else:
            spot_mibor = float(mibor_history.iloc[0]['mibor_rate']) / 100.0

        spot_ois = ois_curve.rates[0]
        spot_basis = spot_mibor - spot_ois

        # 3. Construct Term MIBOR basis (Synthetic, parameterized)
        # In INR, short-end basis is volatile (liquidity), long-end basis is
        # driven by credit/term premiums and usually compresses or stabilizes.
        # We model this as a mean-reverting basis curve.
        long_term_basis = 0.0025  # 25 bps long-term average basis

        mibor_rates = []
        for t, r_ois in zip(ois_curve.tenors, ois_curve.rates):
            # Exponential decay of spot basis towards long-term basis
            basis_t = long_term_basis + (spot_basis - long_term_basis) * np.exp(-0.5 * t)
            mibor_rates.append(r_ois + basis_t)

        mibor_curve = OISCurve(tenors=ois_curve.tenors,
                               rates=np.array(mibor_rates))

        avg_basis_bps = np.mean(np.array(mibor_rates) - ois_curve.rates) * 10000

        return cls(discount_curve=ois_curve,
                   mibor_curve=mibor_curve,
                   basis_bps=avg_basis_bps)
