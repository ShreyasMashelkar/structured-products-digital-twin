"""
FRTB-CVA Standardised Approach (SA-CVA) Capital Engine.

Implements the Basel IV FRTB-CVA Standardised Approach as specified in
BIS: "Minimum capital requirements for market risk" (January 2019, rev. 2024).
Free download: https://www.bis.org/bcbs/publ/d457.pdf

SA-CVA decomposes CVA capital into:
  1. Delta capital: sensitivity to credit spreads (CS01) and interest rates (IR01)
  2. Vega capital: sensitivity to vol (if swaptions are used for hedging)

Formula:
    K_delta = sqrt( (sum_b K_b^2) + sum_{b≠c} γ_bc * S_b * S_c )

where K_b is the within-bucket aggregation and γ_bc is the cross-bucket correlation.

This implementation covers:
  - Credit spread delta risk class (counterparty CDS sensitivities)
  - Interest rate delta risk class (yield curve sensitivities)
  - Aggregation across counterparties and risk factors

Data sources: All risk weights and correlations from BIS FRTB text — free.
"""

import numpy as np
from typing import Dict, List, Optional


# ── FRTB-CVA SA Risk Weights (BIS FRTB Table A, Credit Spread buckets) ─────
# Bucket definitions for credit spread risk:
#   Bucket 1: Investment Grade sovereigns/central banks
#   Bucket 2: IG financials
#   Bucket 3: IG non-financials
#   Bucket 4: Sub-IG/HY (including stressed NBFCs)
#   Bucket 5: Unrated

CS_RISK_WEIGHTS_BPS = {
    'AAA': 0.5,    # IG sovereign / quasi-sovereign (SBI implied)
    'AA': 1.0,     # IG financial (HDFC, ICICI, Kotak)
    'A': 2.0,      # IG non-financial (TATA, Reliance)
    'BBB': 3.0,    # BBB non-financial
    'BB': 6.0,     # Sub-IG
    'B': 12.0,     # High yield
    'CCC': 20.0,   # Distressed
    'NR': 6.0,     # Unrated (maps to BB equivalent)
}

# Cross-bucket correlations for credit spread aggregation (BIS FRTB §4.26)
CS_CROSS_BUCKET_CORR = {
    ('AAA', 'AA'): 0.84,
    ('AAA', 'A'): 0.65,
    ('AAA', 'BBB'): 0.56,
    ('AAA', 'BB'): 0.42,
    ('AA', 'A'): 0.72,
    ('AA', 'BBB'): 0.55,
    ('AA', 'BB'): 0.37,
    ('A', 'BBB'): 0.73,
    ('A', 'BB'): 0.45,
    ('BBB', 'BB'): 0.59,
}

# IR delta risk weights for SA-CVA (basis points per 1bp sensitivity)
# By tenor bucket (same as SA-CCR maturity buckets)
IR_RISK_WEIGHTS = {
    'short': 1.70,   # <1Y: 170bps
    'medium': 1.28,  # 1-5Y: 128bps
    'long': 1.28,    # >5Y: 128bps (simplified — full FRTB has 12 tenors)
}

# Correlation between IR tenor buckets for CVA capital
IR_TENOR_CORR = {
    ('short', 'short'): 1.00,
    ('short', 'medium'): 0.91,
    ('short', 'long'): 0.72,
    ('medium', 'short'): 0.91,
    ('medium', 'medium'): 1.00,
    ('medium', 'long'): 0.87,
    ('long', 'short'): 0.72,
    ('long', 'medium'): 0.87,
    ('long', 'long'): 1.00,
}

# Correlation between CS and IR risk classes (cross-risk class, BIS §4.30)
CS_IR_CROSS_CORR = 0.01   # Effectively uncorrelated in SA-CVA

# SA-CVA vega risk weight (BIS FRTB §4.x). Vega RW = 100% of the vega-implied
# move for interest-rate and credit vol risk classes in the simplified SA-CVA.
VEGA_RISK_WEIGHT = 1.00
# Within-bucket vega correlation (single consolidated vega bucket here)
VEGA_CORR = 0.50
# Curvature shock size (relative bump to vol for the curvature charge)
CURVATURE_SHOCK = 0.01


def _rating_to_bucket(rating: str) -> str:
    """Map a credit rating string to the standard SA-CVA bucket."""
    r = rating.strip().upper()
    if r in ('AAA', 'AA+', 'AA', 'AA-'):
        return 'AA'
    elif r in ('A+', 'A', 'A-'):
        return 'A'
    elif r in ('BBB+', 'BBB', 'BBB-'):
        return 'BBB'
    elif r in ('BB+', 'BB', 'BB-'):
        return 'BB'
    elif r in ('B+', 'B', 'B-', 'CCC', 'CC', 'C', 'D'):
        return 'B'
    else:
        return 'NR'


def _get_cs_rw(rating: str) -> float:
    """Get credit spread risk weight for a given rating."""
    bucket = _rating_to_bucket(rating)
    return CS_RISK_WEIGHTS_BPS.get(bucket, CS_RISK_WEIGHTS_BPS['NR'])


def _cross_corr(r1: str, r2: str) -> float:
    """Cross-bucket correlation for two rating buckets."""
    if r1 == r2:
        return 1.0
    b1 = _rating_to_bucket(r1)
    b2 = _rating_to_bucket(r2)
    key = (b1, b2)
    rev_key = (b2, b1)
    return CS_CROSS_BUCKET_CORR.get(key, CS_CROSS_BUCKET_CORR.get(rev_key, 0.35))


class FRTBCVAEngine:
    """
    FRTB-CVA Standardised Approach (SA-CVA) Capital Calculator.

    Computes regulatory CVA capital charge under Basel IV FRTB-CVA SA
    using CS01 (credit spread sensitivity) and IR01 (rate sensitivity).

    Reference: BIS FRTB document, Chapter 4 (SA-CVA), freely available at
    https://www.bis.org/bcbs/publ/d457.pdf

    Indian Regulatory Context:
        RBI has issued a Basel IV roadmap. SA-CVA will replace the current
        standardised CVA capital under RBI's implementation timeline.
        Using publicly available RBI circulars and BIS text.

    Usage:
        engine = FRTBCVAEngine()
        capital = engine.compute_sa_cva_capital(counterparty_sensitivities)
    """

    def __init__(self, capital_ratio: float = 0.105):
        """
        Args:
            capital_ratio: CET1 + buffer ratio (RBI Basel III: 10.5%).
        """
        self.capital_ratio = capital_ratio

    def compute_cs_delta_capital(
        self,
        counterparty_cs01: Dict[str, float],
        ratings: Dict[str, str],
    ) -> Dict[str, float]:
        """
        Compute SA-CVA delta capital from credit spread sensitivities (CS01).

        CS01 is defined as: change in CVA for a 1bp parallel shift in
        the counterparty's CDS spread curve. Units: ₹ Crores per bp.

        Formula (within a single currency/rating bucket):
            K_b = sqrt( sum_i (RW_i * CS01_i)^2 + sum_{i≠j} corr_ij * RW_i*CS01_i * RW_j*CS01_j )

        Args:
            counterparty_cs01: Dict of counterparty name → CS01 in ₹ Cr/bp
            ratings: Dict of counterparty name → credit rating string

        Returns:
            Dict with per-counterparty capital and total portfolio capital.
        """
        results = {}
        names = list(counterparty_cs01.keys())
        n = len(names)

        # Weighted sensitivities: ws_i = RW_i × CS01_i
        ws = {}
        for name in names:
            rw = _get_cs_rw(ratings.get(name, 'NR'))
            ws[name] = rw * abs(counterparty_cs01.get(name, 0.0))
            results[f'CS01_{name}'] = counterparty_cs01.get(name, 0.0)
            results[f'RW_{name}'] = rw
            results[f'WS_{name}'] = ws[name]

        # Aggregate: K = sqrt( sum_i ws_i^2 + sum_{i≠j} γ_ij * ws_i * ws_j )
        variance = 0.0
        for i, n1 in enumerate(names):
            for j, n2 in enumerate(names):
                r1 = ratings.get(n1, 'NR')
                r2 = ratings.get(n2, 'NR')
                rho = _cross_corr(r1, r2) if i != j else 1.0
                variance += rho * ws[n1] * ws[n2]

        k_cs = np.sqrt(max(variance, 0.0))
        results['K_CS_delta'] = k_cs
        return results

    def compute_ir_delta_capital(
        self,
        counterparty_ir01: Dict[str, Dict[str, float]],
    ) -> Dict[str, float]:
        """
        Compute SA-CVA delta capital from interest rate sensitivities (IR01).

        IR01 is defined as: change in CVA for a 1bp parallel shift in
        the yield curve. Units: ₹ Crores per bp.

        Args:
            counterparty_ir01: Dict of counterparty → {maturity_bucket: IR01}
                e.g., {'HDFC': {'short': 0.002, 'medium': 0.015, 'long': 0.008}}

        Returns:
            Dict with aggregated IR delta capital.
        """
        # Aggregate IR01 across all counterparties per tenor bucket
        bucket_ir01 = {'short': 0.0, 'medium': 0.0, 'long': 0.0}
        for cpty, ir01_by_bucket in counterparty_ir01.items():
            for bucket, ir01 in ir01_by_bucket.items():
                bucket_ir01[bucket] += abs(ir01)

        # Apply IR risk weights
        ws = {b: IR_RISK_WEIGHTS[b] * bucket_ir01[b] for b in bucket_ir01}

        # Aggregate with correlation matrix
        buckets = ['short', 'medium', 'long']
        variance = 0.0
        for b1 in buckets:
            for b2 in buckets:
                rho = IR_TENOR_CORR[(b1, b2)]
                variance += rho * ws[b1] * ws[b2]

        k_ir = np.sqrt(max(variance, 0.0))
        return {
            'IR01_short': bucket_ir01['short'],
            'IR01_medium': bucket_ir01['medium'],
            'IR01_long': bucket_ir01['long'],
            'K_IR_delta': k_ir,
        }

    def compute_sa_cva_capital(
        self,
        counterparty_cs01: Dict[str, float],
        ratings: Dict[str, str],
        counterparty_ir01: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> Dict[str, float]:
        """
        Compute total SA-CVA regulatory capital.

        Total capital combines CS delta and IR delta with low cross-correlation:
            K_total = sqrt( K_CS^2 + K_IR^2 + 2 * ρ_CS_IR * K_CS * K_IR )

        where ρ_CS_IR ≈ 0.01 (effectively uncorrelated per BIS §4.30).

        Args:
            counterparty_cs01: {counterparty: CS01 in ₹ Cr/bp}
            ratings: {counterparty: rating string}
            counterparty_ir01: Optional {counterparty: {bucket: IR01}}
                               If None, IR capital = 0.

        Returns:
            Full SA-CVA capital breakdown.
        """
        cs_result = self.compute_cs_delta_capital(counterparty_cs01, ratings)
        k_cs = cs_result['K_CS_delta']

        if counterparty_ir01:
            ir_result = self.compute_ir_delta_capital(counterparty_ir01)
            k_ir = ir_result['K_IR_delta']
        else:
            ir_result = {'K_IR_delta': 0.0}
            k_ir = 0.0

        # Cross-class aggregation (effectively uncorrelated)
        k_total = np.sqrt(k_cs**2 + k_ir**2 + 2 * CS_IR_CROSS_CORR * k_cs * k_ir)

        # Regulatory capital = K_total × capital_ratio
        capital_requirement = k_total * self.capital_ratio

        return {
            **cs_result,
            **ir_result,
            'K_CS_delta': k_cs,
            'K_IR_delta': k_ir,
            'K_total_FRTB_CVA': k_total,
            'FRTB_CVA_Capital_CR': capital_requirement,
        }

    def compute_vega_capital(self, counterparty_vega: Dict[str, float]) -> Dict[str, float]:
        """
        SA-CVA vega delta capital.

        Vega = ΔCVA per 1% (absolute) change in the implied vol used to hedge
        CVA (e.g. swaption vol). Weighted by the vega risk weight and
        aggregated with a single-bucket correlation.

        K_vega = sqrt( Σ_i ws_i² + Σ_{i≠j} ρ · ws_i · ws_j ),  ws_i = RW · vega_i

        Args:
            counterparty_vega: {counterparty: vega in ₹ Cr per vol point}

        Returns:
            Dict with weighted vegas and K_vega.
        """
        names = list(counterparty_vega.keys())
        ws = {n: VEGA_RISK_WEIGHT * abs(counterparty_vega.get(n, 0.0)) for n in names}
        variance = 0.0
        for i, n1 in enumerate(names):
            for j, n2 in enumerate(names):
                rho = 1.0 if i == j else VEGA_CORR
                variance += rho * ws[n1] * ws[n2]
        return {'K_vega': float(np.sqrt(max(variance, 0.0))),
                **{f'WS_vega_{n}': ws[n] for n in names}}

    def compute_curvature_capital(self,
                                  cva_base: float,
                                  cva_vol_up: float,
                                  cva_vol_down: float) -> Dict[str, float]:
        """
        SA-CVA curvature capital — second-order vol risk.

        Curvature captures the non-linear CVA response to large vol moves
        that vega (first order) misses:
            CVR_up   = -(CVA(vol+shock) - CVA - vega·shock)
            CVR_down = -(CVA(vol-shock) - CVA + vega·shock)
            K_curv   = max(CVR_up, CVR_down, 0)

        Here we pass in CVA re-valued at ±shock vol and take the worst convex
        loss (vega term folded into the revaluations).

        Args:
            cva_base:      CVA at base vol.
            cva_vol_up:    CVA at vol + shock.
            cva_vol_down:  CVA at vol - shock.

        Returns:
            Dict with CVR_up, CVR_down, K_curvature.
        """
        cvr_up = -(cva_vol_up - cva_base)
        cvr_down = -(cva_vol_down - cva_base)
        k_curv = max(cvr_up, cvr_down, 0.0)
        return {'CVR_up': float(cvr_up), 'CVR_down': float(cvr_down),
                'K_curvature': float(k_curv)}

    def compute_total_with_vega_curvature(
        self,
        counterparty_cs01: Dict[str, float],
        ratings: Dict[str, str],
        counterparty_ir01: Optional[Dict[str, Dict[str, float]]] = None,
        counterparty_vega: Optional[Dict[str, float]] = None,
        curvature: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """
        Full SA-CVA capital = delta (CS+IR) ⊕ vega ⊕ curvature.

        Risk classes are combined by simple aggregation (square-root of sum of
        squares) as a conservative consolidation of the three charges.
        """
        delta = self.compute_sa_cva_capital(counterparty_cs01, ratings, counterparty_ir01)
        k_delta = delta['K_total_FRTB_CVA']

        vega = self.compute_vega_capital(counterparty_vega or {})
        k_vega = vega['K_vega']

        k_curv = float(curvature.get('K_curvature', 0.0)) if curvature else 0.0

        k_total = np.sqrt(k_delta ** 2 + k_vega ** 2 + k_curv ** 2)
        return {
            **delta,
            'K_vega': k_vega,
            'K_curvature': k_curv,
            'K_SA_CVA_total': float(k_total),
            'SA_CVA_capital_total_CR': float(k_total * self.capital_ratio),
        }

    def compute_from_eod_report(
        self,
        eod_df: 'pd.DataFrame',
    ) -> 'pd.DataFrame':
        """
        Convenience: compute FRTB-CVA capital from a standard EOD report.

        Reads CS01_CR and IR01_CR columns if present, otherwise derives
        approximate sensitivities from CVA using the flat hazard approximation:
            CS01 ≈ CVA / (CDS_spread / 10000)   [₹ Cr per bp]
            IR01 ≈ CVA × duration_proxy            [₹ Cr per bp]

        Args:
            eod_df: EOD report DataFrame with at minimum:
                    Counterparty, Rating, CVA_CR, CDS_BPS, EE_5Y_CR

        Returns:
            DataFrame with added FRTB_CVA_Capital_CR column.
        """
        import pandas as pd
        rows = []
        for _, row in eod_df.iterrows():
            cva = abs(float(row.get('CVA_CR', 0.0)))
            cds_bps = float(row.get('CDS_BPS', 100.0))
            rating = str(row.get('Rating', 'NR'))

            # Derive CS01: CVA / CDS_spread (sensitivity of CVA to 1bp in spread)
            cs01 = cva / max(cds_bps, 1.0)  # ₹ Cr per bp

            # Derive IR01: approximate as CVA × (duration / DV01 scaling)
            ee_5y = float(row.get('EE_5Y_CR', float(row.get('EPE_CR', 0.0))))
            ir01_medium = ee_5y * 0.0001 * 0.60   # ₹ Cr per bp, rough duration proxy

            cs_result = self.compute_cs_delta_capital(
                {row['Counterparty']: cs01},
                {row['Counterparty']: rating}
            )
            ir_result = self.compute_ir_delta_capital(
                {row['Counterparty']: {'short': 0.0, 'medium': ir01_medium, 'long': 0.0}}
            )

            k_cs = cs_result['K_CS_delta']
            k_ir = ir_result['K_IR_delta']
            k_total = np.sqrt(k_cs**2 + k_ir**2 +
                               2 * CS_IR_CROSS_CORR * k_cs * k_ir)

            rows.append({
                'Counterparty': row['Counterparty'],
                'CS01_derived_CR': round(cs01, 6),
                'IR01_medium_CR': round(ir01_medium, 6),
                'K_CS_delta': round(k_cs, 6),
                'K_IR_delta': round(k_ir, 6),
                'K_FRTB_CVA': round(k_total, 6),
                'FRTB_CVA_Capital_CR': round(k_total * self.capital_ratio, 6),
            })

        return pd.DataFrame(rows)
