"""
Cross-currency swap exposure — 3-factor IR/IR/FX model (FX-XVA).

Cross-currency swaps carry the largest CCR exposures on most bank books
because the final notional exchange is fully exposed to FX moves. A single-
currency rates model cannot capture this; the standard approach is a
three-factor model:

    domestic short rate  r_d : Hull-White 1F
    foreign short rate   r_f : Hull-White 1F
    FX spot              X(t): log-normal, drift = r_d - r_f (covered
                               interest parity), correlated Brownians.

Calibrated to free public data:
    r_d : INR OIS  (FIMMDA / RBI DBIE)
    r_f : USD SOFR level (~5.3%, public)
    X0  : USD/INR RBI reference rate (~84)
    σ_X : USD/INR realised vol (~5%, from RBI reference-rate history)

This module simulates the joint dynamics and computes the EE/ENE/PFE profile
of a fixed-vs-fixed cross-currency swap (with final notional exchange),
expressed in domestic (INR) currency.

Pure NumPy.
"""

import numpy as np
from typing import Dict, Optional
from src.curves.ois_curve import OISCurve
from src.montecarlo.longstaff_schwartz import HullWhite1FBonds


class CrossCurrencySwapModel:
    """
    3-factor (r_d, r_f, X) cross-currency swap exposure engine.

    Convention: domestic = INR (receive domestic fixed), foreign = USD
    (pay foreign fixed). MTM is in domestic currency (₹ Cr).
    """

    def __init__(self,
                 dom_curve: OISCurve,
                 for_rate: float = 0.053,         # flat USD curve level
                 fx_spot: float = 84.0,           # INR per USD
                 fx_vol: float = 0.05,            # USD/INR realised vol
                 a_dom: float = 0.10, sig_dom: float = 0.010,
                 a_for: float = 0.10, sig_for: float = 0.008,
                 rho_dom_for: float = 0.20,
                 rho_dom_fx: float = -0.15,
                 rho_for_fx: float = 0.10):
        self.dom = HullWhite1FBonds(dom_curve, a_dom, sig_dom)
        self.dom_curve = dom_curve
        self.for_rate = for_rate
        self.fx_spot = fx_spot
        self.fx_vol = fx_vol
        self.a_for, self.sig_for = a_for, sig_for
        # 3x3 correlation among (dW_d, dW_f, dW_X)
        self.corr = np.array([
            [1.0, rho_dom_for, rho_dom_fx],
            [rho_dom_for, 1.0, rho_for_fx],
            [rho_dom_fx, rho_for_fx, 1.0],
        ])

    def _for_bond(self, t: float, T: float, xf: np.ndarray) -> np.ndarray:
        """Foreign ZCB under flat-curve HW1F (analytic)."""
        B = (1.0 - np.exp(-self.a_for * (T - t))) / self.a_for
        P0t = np.exp(-self.for_rate * t)
        P0T = np.exp(-self.for_rate * T)
        y = (self.sig_for ** 2) / (2 * self.a_for) * (1 - np.exp(-2 * self.a_for * t))
        A = (P0T / P0t) * np.exp(-0.5 * B ** 2 * y)
        return A * np.exp(-B * xf)

    def simulate(self, n_paths: int, time_grid: np.ndarray,
                 seed: int = 42) -> Dict[str, np.ndarray]:
        """Simulate (x_dom, x_for, FX) with correlated Brownian increments."""
        rng = np.random.default_rng(seed)
        n_steps = len(time_grid) - 1
        L = np.linalg.cholesky(self.corr)

        x_d = np.zeros((n_paths, n_steps + 1))
        x_f = np.zeros((n_paths, n_steps + 1))
        logX = np.full((n_paths, n_steps + 1), np.log(self.fx_spot))

        f0d = np.array([self.dom_curve.instantaneous_forward(max(t, 1e-6)) for t in time_grid])

        for i in range(n_steps):
            dt = time_grid[i + 1] - time_grid[i]
            sdt = np.sqrt(dt)
            Z = rng.standard_normal((n_paths, 3)) @ L.T   # correlated normals

            # domestic OU factor
            dec_d = np.exp(-self.dom.a * dt)
            std_d = self.dom.sigma * np.sqrt((1 - np.exp(-2 * self.dom.a * dt)) / (2 * self.dom.a))
            x_d[:, i + 1] = dec_d * x_d[:, i] + std_d * Z[:, 0]

            # foreign OU factor
            dec_f = np.exp(-self.a_for * dt)
            std_f = self.sig_for * np.sqrt((1 - np.exp(-2 * self.a_for * dt)) / (2 * self.a_for))
            x_f[:, i + 1] = dec_f * x_f[:, i] + std_f * Z[:, 1]

            # FX: dlogX = (r_d - r_f - 0.5 σ²) dt + σ dW_X
            r_d = x_d[:, i] + f0d[i]
            r_f = x_f[:, i] + self.for_rate
            drift = (r_d - r_f - 0.5 * self.fx_vol ** 2) * dt
            logX[:, i + 1] = logX[:, i] + drift + self.fx_vol * sdt * Z[:, 2]

        return {'time_grid': time_grid, 'x_dom': x_d, 'x_for': x_f,
                'FX': np.exp(logX)}

    def swap_mtm_paths(self, sim: Dict, dom_notional: float,
                       dom_fixed: float, for_fixed: float,
                       maturity: float, pay_freq: float = 1.0) -> np.ndarray:
        """
        Fixed-vs-fixed CCS MTM in domestic ccy.

        Receive domestic-fixed on N_d; pay foreign-fixed on N_f = N_d / X0;
        exchange notionals at maturity. MTM(t) in ₹ Cr.
        """
        tg = sim['time_grid']
        x_d, x_f, FX = sim['x_dom'], sim['x_for'], sim['FX']
        n_paths, n_time = x_d.shape
        N_d = dom_notional
        N_f = dom_notional / self.fx_spot
        pay_dates = np.arange(pay_freq, maturity + 1e-8, pay_freq)
        mtm = np.zeros((n_paths, n_time))

        for ti in range(n_time):
            t = tg[ti]
            fut = pay_dates[pay_dates > t]
            if len(fut) == 0:
                continue
            ann_d = np.zeros(n_paths); ann_f = np.zeros(n_paths)
            for Tj in fut:
                ann_d += pay_freq * self.dom.bond_price(t, Tj, x_d[:, ti])
                ann_f += pay_freq * self._for_bond(t, Tj, x_f[:, ti])
            Pd_end = self.dom.bond_price(t, fut[-1], x_d[:, ti])
            Pf_end = self._for_bond(t, fut[-1], x_f[:, ti])

            # domestic leg PV (₹): coupons + notional redemption
            dom_leg = N_d * (dom_fixed * ann_d + Pd_end)
            # foreign leg PV (USD) → convert at FX(t)
            for_leg_usd = N_f * (for_fixed * ann_f + Pf_end)
            for_leg_inr = FX[:, ti] * for_leg_usd

            mtm[:, ti] = dom_leg - for_leg_inr

        return mtm

    @staticmethod
    def exposure_metrics(mtm: np.ndarray, time_grid: np.ndarray) -> Dict:
        pos = np.maximum(mtm, 0.0); neg = np.minimum(mtm, 0.0)
        ee = pos.mean(0); ene = neg.mean(0)
        pfe = np.percentile(pos, 95, axis=0)
        dt = np.diff(time_grid, prepend=0.0)
        T = max(float(time_grid[-1]), 1e-8)
        epe = float(np.dot(ee, dt) / T)
        return {'time_grid': time_grid, 'EE': ee, 'ENE': ene, 'PFE': pfe, 'EPE': epe}
