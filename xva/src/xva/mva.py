"""
Margin Valuation Adjustment (MVA) Engine.

MVA is the present value of the funding cost of posting Initial Margin
over the life of a trade. It is increasingly important for CCP-cleared
and bilaterally margined trades under BCBS/IOSCO regulations.

MVA = Funding_Spread × ∫ E[IM(t)] × DF(t) dt

Initial Margin estimate:
    DV01-based SIMM proxy:
        IM(t) ≈ |DV01| × Vol_bps × sqrt(MPOR/252) × z_confidence

where:
    DV01       = trade dollar sensitivity to 1bp rate move
    Vol_bps    = annualised rate volatility in basis points
    MPOR       = margin period of risk in business days
    z_confidence = 2.326 for 99% confidence (Basel SIMM standard)

The IM profile over time is approximated by scaling the IM at t=0
by the EE profile normalised to its peak — this captures the
typical hump shape of exposure over a swap's life.
"""

import numpy as np
from scipy.stats import norm
from typing import Optional, Dict
from src.curves.ois_curve import OISCurve

SIMM_IR_BUCKETS = [0.5/12, 1/12, 3/12, 6/12, 1.0, 2.0, 5.0, 10.0, 30.0]
# Tenor nodes in years matching ISDA SIMM 2.6 IR delta buckets

SIMM_IR_VOL_BPS = {   # prescribed SIMM risk weights (bps), approximately
    0.5/12: 109, 1/12: 109, 3/12: 95, 6/12: 74,
    1.0: 66, 2.0: 61, 5.0: 52, 10.0: 49, 30.0: 54,
}

SIMM_IR_CORR = 0.50   # intra-currency cross-bucket correlation (SIMM 2.6 Table 54)


class MVAEngine:
    """
    Margin Valuation Adjustment Engine.

    Computes the present value of funding costs for posting Initial Margin
    over the lifetime of a collateralised or CCP-cleared trade.

    Attributes:
        ois_curve: OIS discount curve for present-valuing IM costs.
        funding_spread: Funding spread over OIS (as a decimal).
        dv01_cr: Trade DV01 in ₹ Crores (used for IM estimation).
        vol_bps: Annualised rate volatility in basis points (default 100).
        mpor_days: Margin Period of Risk in business days (default 10).
        confidence: Confidence level for IM calculation (default 0.99).
    """

    def __init__(self, ois_curve: OISCurve,
                 funding_spread_bps: float = 40.0,
                 dv01_cr: float = 0.0,
                 vol_bps: float = 100.0,
                 mpor_days: int = 10,
                 confidence: float = 0.99):
        """
        Initialise the MVA engine.

        Args:
            ois_curve: OIS discount curve for PV discounting.
            funding_spread_bps: Funding spread over OIS in basis points.
            dv01_cr: Trade/netting set DV01 in ₹ Crores. Used for SIMM IM proxy.
            vol_bps: Rate vol in bps for IM estimation (annualised).
            mpor_days: Margin Period of Risk in business days.
            confidence: Confidence level for IM (0.99 = 99%).
        """
        self.ois_curve = ois_curve
        self.funding_spread = funding_spread_bps / 10000.0
        self.dv01_cr = dv01_cr
        self.vol_bps = vol_bps
        self.mpor_days = mpor_days
        self.confidence = confidence

    def compute_initial_margin_at_t0(self) -> float:
        """
        Compute the Initial Margin at t=0 using a DV01-based SIMM proxy.

        IM = |DV01| × Vol_bps × sqrt(MPOR / 252) × z_confidence

        Returns:
            IM at inception in ₹ Crores.
        """
        z = norm.ppf(self.confidence)
        vol_decimal = self.vol_bps / 10000.0
        horizon_scale = np.sqrt(self.mpor_days / 252.0)
        return abs(self.dv01_cr) * vol_decimal * horizon_scale * z

    def compute_simm_im(self, key_rate_dv01s: Dict[float, float]) -> float:
        """
        Compute Initial Margin using a simplified single-currency SIMM IR delta.

        Args:
            key_rate_dv01s: Dict of {tenor_years: dv01_cr} for each SIMM bucket.
                            DV01 should be signed (positive = receive fixed).

        Returns:
            SIMM IM estimate in INR Crores.

        Method:
            Weighted sensitivity s_k = dv01_k * RW_k for each bucket k.
            Aggregate: IM = sqrt( Σ_k s_k² + Σ_{k≠l} ρ * s_k * s_l )
                         = sqrt( (Σ s_k)² * ρ + Σ s_k² * (1-ρ) )
            This is the standard SIMM single-currency aggregation formula.
        """
        rho = SIMM_IR_CORR
        weighted = {}
        for tenor, dv01 in key_rate_dv01s.items():
            # Find nearest SIMM bucket
            nearest = min(SIMM_IR_BUCKETS, key=lambda b: abs(b - tenor))
            rw = SIMM_IR_VOL_BPS.get(nearest, 75) / 10000.0   # convert bps to decimal
            weighted[tenor] = dv01 * rw   # signed weighted sensitivity

        s = list(weighted.values())
        if not s:
            return 0.0

        sum_sq = sum(si**2 for si in s)
        sum_cross = sum(s_i * s_j for i, s_i in enumerate(s)
                        for j, s_j in enumerate(s) if i != j)
        variance = sum_sq + rho * sum_cross
        return float(np.sqrt(max(variance, 0.0)))

    def compute_im_profile(self, ee_profile: np.ndarray, im_t0: Optional[float] = None) -> np.ndarray:
        """
        Estimate the Initial Margin profile over time.

        Scales the t=0 IM estimate by the shape of the EE profile
        normalised to its peak, producing a forward IM profile that
        follows the exposure hump of the trade.

        If DV01 is zero, falls back to a simplified EPE-based proxy.

        Args:
            ee_profile: Expected Exposure profile (n_steps+1,).
            im_t0: Pre-computed IM at t=0 (optional).

        Returns:
            Estimated IM profile in ₹ Crores.
        """
        if im_t0 is None:
            im_t0 = self.compute_initial_margin_at_t0()

        if im_t0 < 1e-12:
            # Fallback: 15% of EE (simplified assumption)
            return ee_profile * 0.15

        # Normalise EE profile to [0,1] and scale by IM at inception
        ee_max = np.max(ee_profile)
        if ee_max < 1e-12:
            return np.zeros_like(ee_profile)

        shape = ee_profile / ee_max
        return im_t0 * shape

    def compute_mva(self, im_profile: np.ndarray,
                    time_grid: np.ndarray) -> float:
        """
        Compute MVA as the present value of funding costs on IM.

        MVA = Funding_Spread × Σᵢ [IM_mid(tᵢ) × DF(tᵢ) × δᵢ]

        Args:
            im_profile: Expected IM at each time step (₹ Crores).
            time_grid: Time grid matching the IM profile.

        Returns:
            MVA in ₹ Crores.
        """
        mva = 0.0
        for i in range(1, len(time_grid)):
            dt = time_grid[i] - time_grid[i - 1]
            im_mid = 0.5 * (im_profile[i - 1] + im_profile[i])
            df = self.ois_curve.df(time_grid[i])   # discount factor
            mva += im_mid * df * dt

        return self.funding_spread * mva

    def full_mva_calculation(self, ee_profile: np.ndarray,
                              time_grid: np.ndarray,
                              key_rate_dv01s: Optional[Dict[float, float]] = None) -> dict:
        """
        Convenience method: compute IM profile and MVA in one call.

        Args:
            ee_profile: Expected Exposure profile.
            time_grid: Time grid.
            key_rate_dv01s: Optional dict of DV01 per tenor for SIMM IM.

        Returns:
            Dictionary with 'im_t0', 'im_profile', 'MVA', 'funding_spread_bps', 'im_method'.
        """
        if key_rate_dv01s:
            im_t0 = self.compute_simm_im(key_rate_dv01s)
            im_method = 'SIMM'
        else:
            im_t0 = self.compute_initial_margin_at_t0()
            im_method = 'DV01_proxy'

        im_profile = self.compute_im_profile(ee_profile, im_t0=im_t0)
        mva = self.compute_mva(im_profile, time_grid)

        return {
            'im_t0_cr': im_t0,
            'im_profile': im_profile,
            'MVA': mva,
            'funding_spread_bps': self.funding_spread * 10000,
            'dv01_cr': self.dv01_cr,
            'vol_bps': self.vol_bps,
            'mpor_days': self.mpor_days,
            'im_method': im_method,
        }
