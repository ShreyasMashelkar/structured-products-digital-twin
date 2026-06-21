"""
CSA Cheapest-to-Deliver (CTD) Optionality Engine.

Under a standard ISDA CSA the collateral poster has the right to deliver
any eligible collateral. They choose the cheapest option:

    Net Carry Cost = Repo_Rate - Yield(collateral) + Haircut × Repo_Rate

The CTD option value = spread between best and worst eligible carry cost.

Data Sources (all free):
    - G-Sec yields:    RBI DBIE (https://dbie.rbi.org.in)
    - Repo rate:       RBI monetary policy page
    - Haircut schedule: RBI circular on margin requirements (free)
    - T-Bill yields:   RBI weekly auction results (free)

Reference:
    - RBI Circular "Margin Requirements for Non-Centrally Cleared
      Derivatives" (2020) — free at rbi.org.in
    - ISDA "Cheapest-to-Deliver" whitepaper (free at isda.org)
"""

import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class EligibleCollateral:
    """
    One eligible collateral asset under an ISDA CSA.

    Attributes:
        name:            Asset identifier (e.g. '10Y_GSEC', 'INR_Cash').
        asset_type:      'cash_inr','gsec','tbill','cash_usd','corp_bond'.
        yield_pct:       Current yield / carry rate (decimal).
        haircut_pct:     Regulatory haircut (decimal, e.g. 0.02 = 2%).
        liquidity_score: 1 (most liquid) to 5 (least liquid).
        rating:          Credit rating string.
    """
    name:            str
    asset_type:      str
    yield_pct:       float
    haircut_pct:     float
    liquidity_score: int  = 1
    rating:          str  = 'AAA'


# ── RBI Haircut Schedule (RBI Circular 2020 — free) ─────────────────────────
RBI_HAIRCUT_SCHEDULE = {
    'cash_inr':   0.000,
    'tbill_91':   0.005,
    'tbill_182':  0.005,
    'tbill_364':  0.010,
    'gsec_1_5y':  0.015,
    'gsec_5_10y': 0.025,
    'gsec_10y+':  0.040,
    'cash_usd':   0.080,
    'corp_aaa':   0.040,
    'corp_aa':    0.060,
}


def get_standard_rbi_collateral_set(
    repo_rate:  float = 0.065,
    mibor:      float = 0.068,
    gsec_10y:   float = 0.072,
    gsec_5y:    float = 0.070,
    tbill_364:  float = 0.067,
    usd_inr:    float = 84.0,
    us_sofr:    float = 0.053,
) -> List[EligibleCollateral]:
    """
    Build the standard set of RBI-eligible collateral for an ISDA CSA.

    All yield parameters are anchored to free public sources:
        repo_rate: RBI monetary policy page
        mibor:     FBIL overnight fixing
        gsec_*:    RBI DBIE G-Sec benchmark yields
        us_sofr:   US SOFR (for USD cash carry)

    Returns:
        List of EligibleCollateral objects.
    """
    return [
        EligibleCollateral('INR_Cash',  'cash_inr',   mibor,      RBI_HAIRCUT_SCHEDULE['cash_inr'],   1),
        EligibleCollateral('TBill_364', 'tbill_364',  tbill_364,  RBI_HAIRCUT_SCHEDULE['tbill_364'],  1),
        EligibleCollateral('GSec_5Y',   'gsec_1_5y',  gsec_5y,    RBI_HAIRCUT_SCHEDULE['gsec_1_5y'],  2),
        EligibleCollateral('GSec_10Y',  'gsec_5_10y', gsec_10y,   RBI_HAIRCUT_SCHEDULE['gsec_5_10y'], 2),
        EligibleCollateral('USD_Cash',  'cash_usd',   us_sofr,    RBI_HAIRCUT_SCHEDULE['cash_usd'],   1),
    ]


class CTDEngine:
    """
    Cheapest-to-Deliver Optionality Engine for ISDA CSA collateral.

    CTD Spread = OIS_rate - [Yield(CTD_asset) - Haircut_cost]

    A positive CTD spread means the receiver implicitly subsidises the
    poster's funding — this is captured in FVA under a sophisticated XVA
    framework.
    """

    def __init__(self, ois_rate: float = 0.068):
        self.ois_rate = ois_rate

    def net_carry_cost(self, asset: EligibleCollateral,
                       repo_rate: float) -> float:
        """
        Net carry cost = Repo_Rate - Yield(asset) + Haircut × Repo_Rate

        Args:
            asset:     The eligible collateral asset.
            repo_rate: Cost of borrowing (RBI repo or TREPS).

        Returns:
            Net carry cost as a decimal annual rate.
        """
        return repo_rate - asset.yield_pct + asset.haircut_pct * repo_rate

    def find_ctd(self, eligible_assets: List[EligibleCollateral],
                 repo_rate: float) -> Dict:
        """
        Identify the cheapest-to-deliver collateral asset.

        Args:
            eligible_assets: List of eligible collateral assets.
            repo_rate:       Current repo rate.

        Returns:
            Dict with ctd_asset, all carry costs, and optionality spread.
        """
        costs = sorted([
            {
                'name':           a.name,
                'asset_type':     a.asset_type,
                'yield_pct':      a.yield_pct,
                'haircut_pct':    a.haircut_pct,
                'net_carry_cost': self.net_carry_cost(a, repo_rate),
                'liquidity_score':a.liquidity_score,
            }
            for a in eligible_assets
        ], key=lambda x: x['net_carry_cost'])

        ctd_spread_bps = (costs[-1]['net_carry_cost'] - costs[0]['net_carry_cost']) * 10000
        ois_spread_bps = (self.ois_rate - costs[0]['yield_pct']) * 10000

        return {
            'ctd_asset':                costs[0],
            'all_assets':               costs,
            'ctd_optionality_spread_bps': ctd_spread_bps,
            'ctd_ois_spread_bps':        ois_spread_bps,
            'n_eligible':               len(eligible_assets),
        }

    def ctd_adjusted_fva(self, ee_profile: np.ndarray,
                          time_grid: np.ndarray,
                          eligible_assets: List[EligibleCollateral],
                          repo_rate: float,
                          ois_curve) -> Dict:
        """
        Compute FVA adjustment for CTD optionality.

        CTD-FVA = CTD_spread × ∫ EE(t) × DF(t) dt

        For a fully-collateralised trade EE(t) ≈ posted collateral(t).

        Args:
            ee_profile:      Expected Exposure profile (n_steps+1,).
            time_grid:       Time grid (n_steps+1,).
            eligible_assets: List of eligible collateral assets.
            repo_rate:       Current repo rate.
            ois_curve:       OIS discount curve.

        Returns:
            Dict with CTD_FVA, ctd_spread_bps, ctd_optionality_spread_bps.
        """
        ctd_result  = self.find_ctd(eligible_assets, repo_rate)
        # Use the CTD optionality spread (worst − best carry, always ≥ 0) — the
        # genuine value of the delivery option — rather than the raw OIS spread,
        # which can go negative when the cheapest asset out-yields OIS.
        ctd_spread  = ctd_result['ctd_optionality_spread_bps'] / 10000.0

        ctd_fva = 0.0
        for i in range(1, len(time_grid)):
            dt     = time_grid[i] - time_grid[i-1]
            ee_mid = 0.5 * (ee_profile[i-1] + ee_profile[i])
            df     = ois_curve.df(time_grid[i])
            ctd_fva += ctd_spread * ee_mid * df * dt

        return {
            'CTD_FVA':                    ctd_fva,
            'ctd_spread_bps':             ctd_result['ctd_ois_spread_bps'],
            'ctd_optionality_spread_bps': ctd_result['ctd_optionality_spread_bps'],
            'ctd_asset_name':             ctd_result['ctd_asset']['name'],
        }
