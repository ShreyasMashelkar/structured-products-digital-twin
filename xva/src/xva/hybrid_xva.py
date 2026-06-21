"""
Hybrid cross-asset XVA — a mixed rates + equity netting set.

This is the capability a single-asset engine cannot provide: a counterparty
netting set that contains BOTH an interest-rate swap (driven by the HW1F rate
factor) and an equity index option (driven by a correlated GBM), valued under
ONE joint simulation. The exposure is netted across asset classes before the
CVA/DVA/FVA are computed, so the result captures cross-asset diversification
and equity-rate wrong-way effects that asset-by-asset XVA misses.

Joint dynamics:
    rate factor  x : dx = -a·x·dt + σ_r·dW_r        (Hull-White 1F)
    equity       S : dS = (r - q)·S·dt + σ_S·S·dW_S  (GBM, r = x + f(0,t))
    corr(dW_r, dW_S) = ρ

Key outputs:
    - netted exposure profile of the mixed book
    - hybrid CVA/DVA/FVA on the netting set
    - cross-asset diversification benefit: standalone CVA(IRS)+CVA(equity)
      versus the hybrid CVA on the combined set.

Pure NumPy; reuses HullWhite1FBonds (rates) and EquityGBM (equity).
"""

import numpy as np
from typing import Dict, List, Optional
from src.curves.ois_curve import OISCurve
from src.xva.cva import CVAEngine, CreditCurve
from src.xva.fva import FVAEngine
from src.montecarlo.longstaff_schwartz import HullWhite1FBonds
from src.montecarlo.equity_mc import EquityGBM
from src.pricing.equity_options import EquityVolSmile


class HybridXVAEngine:
    """Joint rates + equity simulation and netting-set XVA."""

    def __init__(self, ois_curve: OISCurve,
                 equity_spot: float, equity_vol: float, div_yield: float = 0.013,
                 a: float = 0.10, sigma_r: float = 0.010,
                 equity_rate_corr: float = -0.15,
                 smile: Optional[EquityVolSmile] = None):
        self.ois_curve = ois_curve
        self.hw = HullWhite1FBonds(ois_curve, a, sigma_r)
        self.eq = EquityGBM(equity_spot, equity_vol, div_yield)
        self.rho = float(np.clip(equity_rate_corr, -0.99, 0.99))
        self.smile = smile

    # ── joint correlated simulation ──────────────────────────────────────
    def simulate_joint(self, time_grid: np.ndarray, n_paths: int,
                       seed: int = 42) -> Dict:
        """
        Simulate correlated (rate factor x, short rate r, equity spot S).

        Returns dict: time_grid, x (rate factor), spot, disc (stochastic DF).
        """
        rng = np.random.default_rng(seed)
        n_steps = len(time_grid) - 1
        Zr = rng.standard_normal((n_paths, n_steps))
        Zind = rng.standard_normal((n_paths, n_steps))
        Zs = self.rho * Zr + np.sqrt(1 - self.rho ** 2) * Zind   # equity Brownian

        # rate factor (exact OU)
        x = np.zeros((n_paths, n_steps + 1))
        f0 = np.array([self.ois_curve.instantaneous_forward(max(t, 1e-6)) for t in time_grid])
        for i in range(n_steps):
            dt = time_grid[i + 1] - time_grid[i]
            dec = np.exp(-self.hw.a * dt)
            std = self.hw.sigma * np.sqrt((1 - np.exp(-2 * self.hw.a * dt)) / (2 * self.hw.a))
            x[:, i + 1] = dec * x[:, i] + std * Zr[:, i]

        # equity GBM driven by the SAME-grid correlated normals
        spot = self.eq.simulate(time_grid, n_paths, self.ois_curve,
                                equity_normals=Zs, seed=seed)

        # stochastic discount factor from the short-rate path
        r = x + f0[np.newaxis, :]
        dt = np.diff(time_grid)
        integ = np.cumsum(0.5 * (r[:, :-1] + r[:, 1:]) * dt[np.newaxis, :], axis=1)
        disc = np.hstack([np.ones((n_paths, 1)), np.exp(-integ)])

        return {'time_grid': time_grid, 'x': x, 'spot': spot, 'disc': disc}

    # ── per-instrument MTM ───────────────────────────────────────────────
    def swap_mtm(self, sim: Dict, notional: float, fixed_rate: float,
                 maturity: float, payer: bool = False, pay_freq: float = 1.0) -> np.ndarray:
        """IRS MTM paths (default: receive-fixed)."""
        tg, x = sim['time_grid'], sim['x']
        n_paths, n_time = x.shape
        pay = np.arange(pay_freq, maturity + 1e-8, pay_freq)
        mtm = np.zeros((n_paths, n_time))
        for ti in range(n_time):
            t = tg[ti]
            fut = pay[pay > t]
            if len(fut) == 0:
                continue
            ann = np.zeros(n_paths)
            for Tj in fut:
                ann += pay_freq * self.hw.bond_price(t, Tj, x[:, ti])
            P_end = self.hw.bond_price(t, fut[-1], x[:, ti])
            val = notional * ((1.0 - P_end) - fixed_rate * ann)   # payer
            mtm[:, ti] = val if payer else -val
        return mtm

    def equity_option_mtm(self, sim: Dict, strike: float, maturity: float,
                          units: float, call: bool = True) -> np.ndarray:
        """Equity option MTM paths repriced along the joint simulation."""
        return self.eq.option_mtm_paths(sim['spot'], sim['time_grid'], self.ois_curve,
                                        strike, maturity, units, call, self.smile)

    # ── netting & XVA ────────────────────────────────────────────────────
    @staticmethod
    def _ee_ene(mtm: np.ndarray):
        return np.maximum(mtm, 0.0).mean(0), np.minimum(mtm, 0.0).mean(0)

    def compute_hybrid_xva(self, sim: Dict, trade_mtms: List[np.ndarray],
                           credit_curve: CreditCurve,
                           own_cds_bps: float = 40.0,
                           funding_spread_bps: float = 60.0) -> Dict:
        """
        Compute netting-set XVA on a mixed book and the cross-asset
        diversification benefit.

        Args:
            sim:          output of simulate_joint.
            trade_mtms:   list of (n_paths, n_time) MTM arrays (one per trade).
            credit_curve: counterparty credit curve.
            own_cds_bps:  bank's own spread (for DVA).
            funding_spread_bps: funding spread (for FVA).

        Returns:
            Dict with netted exposure, hybrid CVA/DVA/FVA, standalone CVAs,
            and the diversification benefit.
        """
        tg = sim['time_grid']
        cva_eng = CVAEngine(self.ois_curve)
        fva_eng = FVAEngine(self.ois_curve, funding_spread_bps)
        own = CreditCurve(own_cds_bps)

        # netted MTM across all trades in the set
        netted = np.sum(trade_mtms, axis=0)
        ee_net, ene_net = self._ee_ene(netted)
        pfe_net = np.percentile(np.maximum(netted, 0.0), 95, axis=0)

        cva_hybrid = cva_eng.compute_cva(ee_net, tg, credit_curve)
        dva_hybrid = cva_eng.compute_dva(ene_net, tg, own)
        fva_hybrid = fva_eng.compute_fva(ee_net, ene_net, tg)['FVA']

        # standalone CVAs (no cross-asset netting)
        standalone_cva = []
        standalone_ee = []
        for m in trade_mtms:
            ee_i, _ = self._ee_ene(m)
            standalone_ee.append(ee_i)
            standalone_cva.append(cva_eng.compute_cva(ee_i, tg, credit_curve))
        sum_standalone_cva = float(np.sum(standalone_cva))

        return {
            'time_grid': tg,
            'EE_netted': ee_net, 'ENE_netted': ene_net, 'PFE_netted': pfe_net,
            'standalone_EE': standalone_ee,
            'CVA_hybrid': float(cva_hybrid),
            'DVA_hybrid': float(dva_hybrid),
            'FVA_hybrid': float(abs(fva_hybrid)),
            'BCVA_hybrid': float(cva_hybrid - dva_hybrid),
            'standalone_cva': [float(c) for c in standalone_cva],
            'sum_standalone_cva': sum_standalone_cva,
            'diversification_benefit_cva': float(sum_standalone_cva - cva_hybrid),
            'netting_benefit_pct': float(100.0 * (1 - cva_hybrid / sum_standalone_cva))
                                   if sum_standalone_cva > 1e-12 else 0.0,
        }
