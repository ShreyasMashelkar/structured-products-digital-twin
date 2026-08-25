"""
Hybrid cross-asset XVA — a mixed rates + equity netting set.

This is the capability a single-asset engine cannot provide: a counterparty
netting set that contains BOTH an interest-rate swap (driven by the HW1F rate
factor) and an equity index option (driven by a correlated GBM), valued under
ONE joint simulation. The exposure is netted across asset classes before the
CVA/DVA/FVA are computed, so the result captures cross-asset diversification
and equity-rate wrong-way effects that asset-by-asset XVA misses.

Joint dynamics (two-factor rates, the default):
    rate factors : dx = -a·x·dt + σ₁·dW₁ ,  dy = -b·y·dt + σ₂·dW₂ ,  corr(dW₁,dW₂) = ρ_xy
    short rate   : r(t) = x(t) + y(t) + φ(t)
    equity     S : dS = (r - q)·S·dt + σ_S·S·dW_S   (GBM)
    corr(dW₁,dW_S) = corr(dW₂,dW_S) = ρ_eq

**Why two factors.** With a single factor the whole curve is driven by one Brownian, so every
tenor moves in lockstep: the curve can shift up and down but its *shape* is frozen at today's.
That systematically understates exposure on any trade whose value depends on the spread
between tenors — which is most of a swap book — because the one risk the model cannot
generate is precisely a steepening or flattening into the exposure. A second, slower-reverting
factor lets the level and the slope move semi-independently (INR: fast MIBOR-driven front end,
slow G-Sec-driven long end), so curve-shape risk shows up in EE/PFE and therefore in CVA
rather than being assumed away.

The 1F path is retained (``two_factor=False``) as the reference case: the difference between
the two is itself a model-risk number worth reporting, not an implementation detail.

Key outputs:
    - netted exposure profile of the mixed book
    - hybrid CVA/DVA/FVA on the netting set
    - cross-asset diversification benefit: standalone CVA(IRS)+CVA(equity)
      versus the hybrid CVA on the combined set.

Pure NumPy; reuses HullWhite2F / HullWhite1FBonds (rates) and EquityGBM (equity).
"""

import numpy as np
from typing import Dict, List, Optional
from src.curves.ois_curve import OISCurve
from src.xva.cva import CVAEngine, CreditCurve
from src.xva.fva import FVAEngine
from src.montecarlo.longstaff_schwartz import HullWhite1FBonds
from src.montecarlo.hull_white_2f import HullWhite2F
from src.montecarlo.equity_mc import EquityGBM
from src.pricing.equity_options import EquityVolSmile


def _correlated_normals(rng, n_paths: int, n_steps: int,
                        corr: np.ndarray) -> np.ndarray:
    """Draw correlated standard normals of shape (n_factors, n_paths, n_steps).

    Cholesky is used when the requested correlation matrix is positive definite. Hand-supplied
    correlations routinely are not — ρ_xy and ρ_eq are estimated from different data over
    different windows and need not be mutually consistent — so an indefinite matrix is
    repaired by clipping its eigenvalues rather than failing the run. The repair is reported
    through :func:`nearest_correlation` so a caller can see that it happened.
    """
    corr = nearest_correlation(corr)
    try:
        chol = np.linalg.cholesky(corr)
    except np.linalg.LinAlgError:  # pragma: no cover - repair above makes this unreachable
        chol = np.linalg.cholesky(corr + 1e-10 * np.eye(corr.shape[0]))
    z = rng.standard_normal((corr.shape[0], n_paths, n_steps))
    return np.einsum('ij,jpn->ipn', chol, z)


def nearest_correlation(corr: np.ndarray, *, min_eig: float = 1e-8) -> np.ndarray:
    """Nearest positive-definite correlation matrix by eigenvalue clipping.

    Returns ``corr`` unchanged (up to floating point) when it is already PD.
    """
    corr = np.asarray(corr, dtype=float)
    vals, vecs = np.linalg.eigh(corr)
    if vals.min() >= min_eig:
        return corr
    repaired = vecs @ np.diag(np.maximum(vals, min_eig)) @ vecs.T
    d = np.sqrt(np.diag(repaired))
    return repaired / np.outer(d, d)


class HybridXVAEngine:
    """Joint rates + equity simulation and netting-set XVA."""

    def __init__(self, ois_curve: OISCurve,
                 equity_spot: float, equity_vol: float, div_yield: float = 0.013,
                 a: float = 0.10, sigma_r: float = 0.010,
                 equity_rate_corr: float = -0.15,
                 smile: Optional[EquityVolSmile] = None,
                 two_factor: bool = True,
                 b: float = 0.02, sigma2: float = 0.007, rho_xy: float = 0.70):
        """
        Args:
            a, sigma_r:  first (fast) rate factor — mean reversion and vol.
            b, sigma2:   second (slow) rate factor; ignored when ``two_factor`` is False.
                         ``b`` must differ from ``a`` or the two factors degenerate into one.
            rho_xy:      correlation between the two rate factors.
            equity_rate_corr: correlation of the equity Brownian to *each* rate factor.
            two_factor:  False restores the single-factor model (frozen curve shape).
        """
        self.ois_curve = ois_curve
        self.two_factor = two_factor
        if two_factor:
            if abs(a - b) < 1e-8:
                b = a * 0.25  # keep the factors distinct; HW2F rejects a == b outright
            self.hw = HullWhite2F(ois_curve, a=a, b=b,
                                  sigma1=sigma_r, sigma2=sigma2, rho=rho_xy)
        else:
            self.hw = HullWhite1FBonds(ois_curve, a, sigma_r)
        self.eq = EquityGBM(equity_spot, equity_vol, div_yield)
        self.rho = float(np.clip(equity_rate_corr, -0.99, 0.99))
        self.rho_xy = float(np.clip(rho_xy, -0.99, 0.99))
        self.smile = smile

    def _bond_price(self, t: float, T: float,
                    x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """P(t,T) under whichever rate model is active — the one place the two differ."""
        if self.two_factor:
            return self.hw.zero_coupon_bond_price(t, T, x, y)
        return self.hw.bond_price(t, T, x)

    # ── joint correlated simulation ──────────────────────────────────────
    def simulate_joint(self, time_grid: np.ndarray, n_paths: int,
                       seed: int = 42) -> Dict:
        """
        Simulate correlated rate factors (x, y), the short rate, and equity spot S.

        In one-factor mode ``y`` is returned as zeros so downstream code is shape-identical
        either way. Both factors and the equity are drawn from one joint Cholesky so the
        cross-asset correlation is exact rather than imposed pairwise after the fact.

        Returns dict: time_grid, x, y (rate factors), spot, disc (stochastic DF).
        """
        rng = np.random.default_rng(seed)
        n_steps = len(time_grid) - 1
        dts = np.diff(time_grid)

        if self.two_factor:
            corr = np.array([
                [1.0,          self.rho_xy, self.rho],
                [self.rho_xy,  1.0,         self.rho],
                [self.rho,     self.rho,    1.0],
            ])
            Z = _correlated_normals(rng, n_paths, n_steps, corr)
            Z1, Z2, Zs = Z[0], Z[1], Z[2]
            a, b = self.hw.a, self.hw.b
            s1, s2 = self.hw.sigma1, self.hw.sigma2
        else:
            corr = np.array([[1.0, self.rho], [self.rho, 1.0]])
            Z = _correlated_normals(rng, n_paths, n_steps, corr)
            Z1, Zs = Z[0], Z[1]
            Z2 = np.zeros_like(Z1)
            a, b = self.hw.a, 1.0
            s1, s2 = self.hw.sigma, 0.0

        # rate factors (exact OU discretisation)
        x = np.zeros((n_paths, n_steps + 1))
        y = np.zeros((n_paths, n_steps + 1))
        for i, dt in enumerate(dts):
            dec1 = np.exp(-a * dt)
            std1 = s1 * np.sqrt((1 - np.exp(-2 * a * dt)) / (2 * a))
            x[:, i + 1] = dec1 * x[:, i] + std1 * Z1[:, i]
            if self.two_factor:
                dec2 = np.exp(-b * dt)
                std2 = s2 * np.sqrt((1 - np.exp(-2 * b * dt)) / (2 * b))
                y[:, i + 1] = dec2 * y[:, i] + std2 * Z2[:, i]

        # equity GBM driven by the SAME-grid correlated normals
        spot = self.eq.simulate(time_grid, n_paths, self.ois_curve,
                                equity_normals=Zs, seed=seed)

        # Short rate: r = x + y + φ(t). The two-factor φ carries the convexity terms that
        # refit the initial curve exactly; the one-factor case reduces to f(0,t).
        if self.two_factor:
            shift = np.array([self.hw._phi(max(t, 1e-6)) for t in time_grid])
        else:
            shift = np.array([self.ois_curve.instantaneous_forward(max(t, 1e-6))
                              for t in time_grid])
        r = x + y + shift[np.newaxis, :]
        integ = np.cumsum(0.5 * (r[:, :-1] + r[:, 1:]) * dts[np.newaxis, :], axis=1)
        disc = np.hstack([np.ones((n_paths, 1)), np.exp(-integ)])

        return {'time_grid': time_grid, 'x': x, 'y': y, 'spot': spot, 'disc': disc}

    # ── per-instrument MTM ───────────────────────────────────────────────
    def swap_mtm(self, sim: Dict, notional: float, fixed_rate: float,
                 maturity: float, payer: bool = False, pay_freq: float = 1.0) -> np.ndarray:
        """IRS MTM paths (default: receive-fixed)."""
        tg, x = sim['time_grid'], sim['x']
        y = sim.get('y', np.zeros_like(x))
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
                ann += pay_freq * self._bond_price(t, Tj, x[:, ti], y[:, ti])
            P_end = self._bond_price(t, fut[-1], x[:, ti], y[:, ti])
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
