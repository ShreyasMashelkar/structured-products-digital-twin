"""
Adjoint Algorithmic Differentiation (AAD) CVA Greeks engine.

Computes the FULL CVA sensitivity vector — credit spread (CS01), interest
rate (IR01), recovery, and the sensitivity to EVERY node of the expected
exposure profile — in a SINGLE reverse sweep, using the self-contained
autodiff engine in src/utils/autodiff.py.

This is the production technique: bump-and-revalue costs one full CVA
revaluation per sensitivity (N+1 valuations for N Greeks). AAD costs ~1
valuation for the entire gradient vector, independent of N. On a real
exposure grid with 60 time nodes that is a ~60× reduction in the number of
revaluations for the exposure-bucket Greeks alone.

The CVA model matches the existing CVAEngine.compute_cva exactly:
    CVA = LGD · Σ_i EE_mid(t_i) · [S(t_{i-1}) - S(t_i)] · DF(t_i)
with flat hazard S(t) = exp(-h t), h = spread / LGD, LGD = 1 - R.
Discount factors are made rate-sensitive via DF_i = DF0_i · exp(-Δr · t_i)
so IR01 is the parallel-shift sensitivity (discount component, matching
CVAEngine.ir01).
"""

import time
import numpy as np
from typing import Dict
from src.utils.autodiff import Var
from src.curves.ois_curve import OISCurve
from src.xva.cva import CreditCurve, CVAEngine


class AADCVAEngine:
    """
    AAD-based CVA and full Greek vector in one reverse sweep.

    Usage:
        eng = AADCVAEngine(ois_curve)
        out = eng.cva_and_greeks(ee_profile, time_grid, credit_curve)
        out['CVA'], out['CS01'], out['IR01'], out['EE_deltas'] ...
    """

    def __init__(self, ois_curve: OISCurve):
        self.ois_curve = ois_curve

    def _build_cva(self, ee_arr: np.ndarray, time_grid: np.ndarray,
                   spread_dec: float, recovery: float, df0: np.ndarray):
        """
        Build the CVA computation graph and return (cva_node, input_nodes).

        Inputs that we differentiate:
            ee     : Var over the EE profile (vector)
            spread : Var scalar (CDS spread, decimal)
            R      : Var scalar (recovery)
            dr     : Var scalar (parallel rate shift, decimal; value 0)
        """
        ee = Var(ee_arr.astype(float))
        spread = Var(float(spread_dec))
        R = Var(float(recovery))
        dr = Var(0.0)

        lgd = 1.0 - R
        h = spread / lgd

        t = time_grid.astype(float)
        # Survival S(t_i) = exp(-h * t_i)  → build per-node then difference
        # S as a vector node:
        neg_h_t = (h * Var(t)) * (-1.0)
        S = neg_h_t.exp()                       # Var vector, length n
        S_prev = S.slice_to(slice(0, -1))       # S(t_{i-1})
        S_curr = S.slice_to(slice(1, None))     # S(t_i)
        dp = S_prev - S_curr                     # default prob over each step

        # Rate-sensitive discount factors: DF_i = DF0_i * exp(-dr * t_i)
        df_decay = ((dr * Var(t)) * (-1.0)).exp()
        df = Var(df0.astype(float)) * df_decay
        df_curr = df.slice_to(slice(1, None))    # DF(t_i)

        ee_prev = ee.slice_to(slice(0, -1))
        ee_curr = ee.slice_to(slice(1, None))
        ee_mid = (ee_prev + ee_curr) * 0.5

        contrib = (ee_mid * dp) * df_curr        # vector
        cva = lgd * contrib.sum()
        return cva, {'ee': ee, 'spread': spread, 'R': R, 'dr': dr}

    def cva_and_greeks(self, ee_profile: np.ndarray, time_grid: np.ndarray,
                       credit_curve: CreditCurve) -> Dict:
        """
        Compute CVA and its full Greek vector in one reverse sweep.

        Returns dict:
            CVA          : value (₹ Cr)
            CS01         : dCVA per +1bp CDS spread (₹ Cr/bp)
            IR01         : dCVA per +1bp parallel rate (₹ Cr/bp)
            Recovery01   : dCVA per +1% recovery (₹ Cr/%)
            EE_deltas    : vector dCVA/dEE_i (one entry per exposure node)
            n_sensitivities : total Greeks obtained in the single sweep
        """
        df0 = np.array([self.ois_curve.df(float(t)) for t in time_grid])
        cva, nodes = self._build_cva(
            ee_profile, time_grid, credit_curve.cds_spread,
            credit_curve.recovery_rate, df0)
        cva.backward()

        # spread is in decimal; +1bp = +1e-4 → CS01 = d/dspread * 1e-4
        cs01 = float(nodes['spread'].grad) * 1e-4
        # dr is decimal parallel shift; +1bp = +1e-4 → IR01 per bp
        ir01 = float(nodes['dr'].grad) * 1e-4
        rec01 = float(nodes['R'].grad) * 0.01  # per +1% recovery
        ee_deltas = np.asarray(nodes['ee'].grad, dtype=float)

        return {
            'CVA': float(cva.value),
            'CS01': cs01,
            'IR01': ir01,
            'Recovery01': rec01,
            'EE_deltas': ee_deltas,
            'n_sensitivities': 3 + len(ee_deltas),
        }

    # ── benchmark vs bump-and-revalue ────────────────────────────────────
    def benchmark_vs_bump(self, ee_profile: np.ndarray, time_grid: np.ndarray,
                          credit_curve: CreditCurve, n_reps: int = 50) -> Dict:
        """
        Benchmark AAD (one sweep, all Greeks) against bump-and-revalue.

        Compares:
            - CS01 and IR01 agreement (AAD vs finite-difference)
            - the FULL exposure-bucket Greek vector: AAD computes all in one
              sweep; bump-and-revalue needs one revaluation per bucket.
            - wall-clock cost and the implied revaluation-count ratio.

        Returns a dict of timings, agreement, and speed-up.
        """
        bump_engine = CVAEngine(self.ois_curve)
        n_nodes = len(time_grid)

        # AAD: full gradient, timed
        t0 = time.perf_counter()
        for _ in range(n_reps):
            aad = self.cva_and_greeks(ee_profile, time_grid, credit_curve)
        t_aad = (time.perf_counter() - t0) / n_reps

        # Bump-and-revalue: CS01, IR01, + every EE bucket Greek
        df0 = np.array([self.ois_curve.df(float(t)) for t in time_grid])

        def _cva_plain(ee, spread_dec, recovery, dr):
            lgd = 1.0 - recovery
            h = spread_dec / lgd
            S = np.exp(-h * time_grid)
            dp = S[:-1] - S[1:]
            df = df0 * np.exp(-dr * time_grid)
            ee_mid = 0.5 * (ee[:-1] + ee[1:])
            return lgd * np.sum(ee_mid * dp * df[1:])

        base = _cva_plain(ee_profile, credit_curve.cds_spread,
                          credit_curve.recovery_rate, 0.0)
        t0 = time.perf_counter()
        for _ in range(n_reps):
            cs01_b = (_cva_plain(ee_profile, credit_curve.cds_spread + 1e-4,
                                 credit_curve.recovery_rate, 0.0) - base)
            ir01_b = (_cva_plain(ee_profile, credit_curve.cds_spread,
                                 credit_curve.recovery_rate, 1e-4) - base)
            ee_deltas_b = np.zeros(n_nodes)
            for i in range(n_nodes):
                bumped = ee_profile.copy()
                h_ = max(abs(ee_profile[i]) * 1e-4, 1e-8)
                bumped[i] += h_
                ee_deltas_b[i] = (_cva_plain(bumped, credit_curve.cds_spread,
                                             credit_curve.recovery_rate, 0.0) - base) / h_
        t_bump = (time.perf_counter() - t0) / n_reps

        cs01_err = abs(aad['CS01'] - cs01_b)
        ir01_err = abs(aad['IR01'] - ir01_b)
        ee_err = float(np.max(np.abs(aad['EE_deltas'] - ee_deltas_b)))

        return {
            'CVA': aad['CVA'],
            'n_sensitivities': aad['n_sensitivities'],
            'aad_ms': t_aad * 1e3,
            'bump_ms': t_bump * 1e3,
            'speedup': (t_bump / t_aad) if t_aad > 0 else float('nan'),
            'CS01_aad': aad['CS01'], 'CS01_bump': cs01_b, 'CS01_abs_err': cs01_err,
            'IR01_aad': aad['IR01'], 'IR01_bump': ir01_b, 'IR01_abs_err': ir01_err,
            'EE_delta_max_abs_err': ee_err,
            'bump_revaluations': 1 + 2 + n_nodes,   # base + CS01 + IR01 + each node
            'aad_revaluations': 1,
        }
