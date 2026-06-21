"""
Credit-Contingent CVA and CDS Hedge Effectiveness Engine.

Models the imperfect hedge between CVA and CDS protection.

Indian market context:
    - Liquid CDS on Indian banks NOT available domestically
    - Some protection via offshore SNAC contracts (major banks only)
    - Banks typically use G-Sec shorts or credit bond proxies
    - SEBI/RBI developing domestic CDS market

References:
    - Brigo, Pallavicini (2014), CDO and Credit CVA
    - BIS Working Paper on CVA hedging (free at bis.org)
    - RBI Discussion Paper "Corporate Bond and Credit Derivatives" (free)
"""

import numpy as np
from typing import Dict, Optional
from src.curves.ois_curve import OISCurve
from src.xva.cva import CreditCurve, CVAEngine


class CDSHedgeEngine:
    """
    CDS hedge of CVA risk with basis risk and hedge effectiveness analysis.

    Basis risk parameters are from published CCIL/BIS research on
    Indian credit instruments — all free sources.
    """

    # Annualised basis risk as fraction of CDS spread (from BIS/CCIL research)
    INDIA_BASIS_RISK = {
        'PSU_Bank':     0.15,
        'Private_Bank': 0.25,
        'NBFC':         0.40,
        'Corporate_IG': 0.30,
        'Corporate_HY': 0.50,
        'Sovereign':    0.10,
    }

    def __init__(self, ois_curve: OISCurve):
        self.ois_curve  = ois_curve
        self.cva_engine = CVAEngine(ois_curve)

    def compute_cds_hedge_notional(
        self,
        ee_profile:    np.ndarray,
        time_grid:     np.ndarray,
        credit_curve:  CreditCurve,
        hedge_tenor:   float = 5.0,
    ) -> Dict:
        """
        Compute CDS notional required to delta-hedge CVA.

        Hedge ratio = CS01_CVA / CS01_CDS(hedge_tenor)
        CS01_CDS ≈ risky_annuity × LGD / 10000

        Args:
            ee_profile:   Expected Exposure profile.
            time_grid:    Time grid.
            credit_curve: Counterparty credit curve.
            hedge_tenor:  Maturity of hedging CDS in years.

        Returns:
            Dict with hedge_notional_cr, cs01_cva_cr_per_bp, and premium.
        """
        cs01_cva = self.cva_engine.cs01(ee_profile, time_grid, credit_curve)

        h        = credit_curve.hazard_rate
        recovery = credit_curve.recovery_rate
        lgd      = 1.0 - recovery

        # Risky annuity: Σ DF(t) × SP(t) × 0.25 (quarterly payments)
        payment_dates = np.arange(0.25, hedge_tenor + 0.01, 0.25)
        annuity = sum(
            self.ois_curve.df(t) * np.exp(-h * t) * 0.25
            for t in payment_dates
        )

        cs01_cds_unit   = annuity / 10000.0
        hedge_notional  = cs01_cva / cs01_cds_unit if abs(cs01_cds_unit) > 1e-12 else 0.0

        cds_spread_bps  = credit_curve.cds_spread * 10000  # decimal → bps
        annual_premium  = hedge_notional * cds_spread_bps / 10000.0
        pv_premium      = annual_premium * annuity

        return {
            'cs01_cva_cr_per_bp':     cs01_cva,
            'cs01_cds_unit':          cs01_cds_unit,
            'hedge_notional_cr':      hedge_notional,
            'hedge_tenor_years':      hedge_tenor,
            'cds_annual_premium_cr':  annual_premium,
            'cds_premium_pv_cr':      pv_premium,
        }

    def hedge_effectiveness(
        self,
        sector:        str,
        cva_vol:       float,
        cds_available: bool = False,
    ) -> Dict:
        """
        Estimate hedge effectiveness under Indian market conditions.

        Args:
            sector:        Counterparty sector (for basis risk lookup).
            cva_vol:       Annualised CVA P&L volatility (₹ Cr).
            cds_available: Whether liquid CDS is available.

        Returns:
            Dict with effectiveness ratio and residual risk.
        """
        basis_risk = self.INDIA_BASIS_RISK.get(sector, 0.30)

        if cds_available:
            effectiveness = max(0.0, 1.0 - basis_risk)
            hedge_type    = 'Direct CDS'
        else:
            effectiveness = max(0.0, 1.0 - basis_risk * 2.0)
            hedge_type    = 'Proxy (G-Sec/Bond)'

        residual_vol = cva_vol * np.sqrt(max(1.0 - effectiveness**2, 0.0))

        return {
            'hedge_type':             hedge_type,
            'sector':                 sector,
            'effectiveness':          effectiveness,
            'basis_risk_pct':         basis_risk,
            'cva_vol_cr':             cva_vol,
            'residual_cva_vol_cr':    residual_vol,
            'hedge_ratio_recommended':effectiveness,
            'india_market_note': (
                'Direct CDS on Indian entities limited to offshore SNAC contracts. '
                'Most Indian banks hedge CVA via G-Sec/credit spread proxies. '
                'RBI working paper recommends development of domestic CDS market.'
            ),
        }

    def unhedged_cva_pnl_variance(
        self,
        ee_profile:    np.ndarray,
        time_grid:     np.ndarray,
        credit_curve:  CreditCurve,
        cs_vol_bps:    float = 20.0,
        ir_vol_bps:    float = 15.0,
    ) -> Dict:
        """
        Estimate daily CVA P&L variance from unhedged risks.

        Daily CVA P&L ≈ CS01 × ΔCS + IR01 × ΔIR

        Var(P&L) = CS01²σ_CS² + IR01²σ_IR² + 2ρ·CS01·IR01·σ_CS·σ_IR

        Args:
            ee_profile:   EE profile.
            time_grid:    Time grid.
            credit_curve: Credit curve.
            cs_vol_bps:   Daily vol of CDS spread (bps). ~20bps/day for India.
            ir_vol_bps:   Daily vol of OIS rate (bps). ~15bps/day for India.

        Returns:
            Dict with daily CVA P&L vol and 99% VaR.
        """
        cs01 = self.cva_engine.cs01(ee_profile, time_grid, credit_curve)
        ir01 = self.cva_engine.ir01(ee_profile, time_grid, credit_curve)

        cs_ir_corr = -0.20   # Mild negative corr: rates up → spreads wider

        var_pnl = (
            (cs01 * cs_vol_bps)**2 +
            (ir01 * ir_vol_bps)**2 +
            2 * cs_ir_corr * cs01 * ir01 * cs_vol_bps * ir_vol_bps
        )
        vol_pnl = float(np.sqrt(max(var_pnl, 0.0)))

        return {
            'CS01_cr_per_bp':    cs01,
            'IR01_cr_per_bp':    ir01,
            'daily_cva_vol_cr':  vol_pnl,
            'daily_cva_var99_cr':vol_pnl * 2.326,
            'cs_vol_bps':        cs_vol_bps,
            'ir_vol_bps':        ir_vol_bps,
        }
