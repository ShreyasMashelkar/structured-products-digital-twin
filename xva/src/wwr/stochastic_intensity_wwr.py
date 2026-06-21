"""
Stochastic-intensity (Cox process) Wrong-Way Risk.

The most rigorous WWR model: the counterparty's default intensity λ(t) is a
stochastic process correlated with the market risk factor that drives the
exposure. When the correlation is positive, the states of the world in which
exposure is high are also the states in which default is more likely — the
exact definition of wrong-way risk — and CVA rises accordingly.

Model:
    short rate  r(t) : Hull-White 1F   (drives swap exposure)
    intensity   λ(t) : CIR process     dλ = κ(θ-λ)dt + ξ√λ dW_λ
    corr(dW_r, dW_λ) = ρ               (ρ>0 ⇒ wrong-way)

Default time τ is the first time the integrated intensity ∫λ exceeds an
independent unit-exponential threshold (Cox / doubly-stochastic construction).
CVA = E[ LGD · EE(τ) · D(0,τ) · 1{τ ≤ T} ].

Comparing CVA(ρ) to CVA(ρ=0) gives the genuine WWR multiplier — a function
of the *dynamics*, not a static correlation fudge factor.

Pure NumPy. References: Brigo, Pallavicini, Papatheodorou (2011); Lando (1998).
"""

import numpy as np
from typing import Dict, Optional
from src.curves.ois_curve import OISCurve
from src.montecarlo.longstaff_schwartz import HullWhite1FBonds


class StochasticIntensityWWR:
    """
    Cox-process WWR-CVA with a CIR default intensity correlated to rates.
    """

    def __init__(self, curve: OISCurve,
                 a: float = 0.10, sigma: float = 0.012,
                 kappa: float = 0.50, theta: float = 0.03,
                 xi: float = 0.08, lambda0: Optional[float] = None,
                 recovery: float = 0.40):
        self.curve = curve
        self.hw = HullWhite1FBonds(curve, a, sigma)
        self.kappa = kappa          # intensity mean-reversion speed
        self.theta = theta          # long-run mean intensity (~ hazard rate)
        self.xi = xi                # intensity vol
        self.lambda0 = theta if lambda0 is None else lambda0
        self.recovery = recovery
        self.lgd = 1.0 - recovery

    def _swap_value(self, t: float, x: np.ndarray, notional: float,
                    fixed_rate: float, maturity: float,
                    payer: bool, pay_freq: float) -> np.ndarray:
        pay = np.arange(t + pay_freq, maturity + 1e-8, pay_freq)
        if len(pay) == 0:
            return np.zeros_like(x)
        ann = np.zeros_like(x)
        for Tj in pay:
            ann += pay_freq * self.hw.bond_price(t, Tj, x)
        P_end = self.hw.bond_price(t, pay[-1], x)
        val = notional * ((1.0 - P_end) - fixed_rate * ann)
        return val if payer else -val

    def simulate_cva(self, notional: float, fixed_rate: float, maturity: float,
                     rho: float, payer: bool = True, pay_freq: float = 1.0,
                     n_paths: int = 8000, n_steps_per_year: int = 12,
                     seed: int = 42) -> Dict:
        """
        Simulate correlated (rate, intensity), default times, and CVA.

        Returns dict with CVA, EPE, exposure profile, default statistics.
        """
        T = maturity
        n_steps = max(2, int(round(T * n_steps_per_year)))
        tg = np.linspace(0, T, n_steps + 1)
        dt = np.diff(tg)
        rng = np.random.default_rng(seed)

        x = np.zeros((n_paths, n_steps + 1))         # HW factor
        lam = np.full((n_paths, n_steps + 1), self.lambda0)
        integ_lambda = np.zeros(n_paths)             # ∫λ ds
        f0 = np.array([self.curve.instantaneous_forward(max(t, 1e-6)) for t in tg])

        rate_int = np.zeros(n_paths)                 # ∫r ds for discounting
        threshold = rng.exponential(1.0, n_paths)    # unit-exponential trigger
        tau = np.full(n_paths, np.inf)               # default time
        # exposure accumulation at default
        cva_acc = np.zeros(n_paths)

        for i in range(n_steps):
            sdt = np.sqrt(dt[i])
            z1 = rng.standard_normal(n_paths)
            z2 = rho * z1 + np.sqrt(max(1 - rho ** 2, 0.0)) * rng.standard_normal(n_paths)

            # rate factor (exact OU)
            dec = np.exp(-self.hw.a * dt[i])
            std = self.hw.sigma * np.sqrt((1 - np.exp(-2 * self.hw.a * dt[i])) / (2 * self.hw.a))
            x[:, i + 1] = dec * x[:, i] + std * z1

            # CIR intensity (full-truncation Euler)
            lam_pos = np.maximum(lam[:, i], 0.0)
            lam[:, i + 1] = np.maximum(
                lam[:, i] + self.kappa * (self.theta - lam_pos) * dt[i]
                + self.xi * np.sqrt(lam_pos) * sdt * z2, 0.0)

            # accumulate integrals
            r_mid = 0.5 * (x[:, i] + f0[i] + x[:, i + 1] + f0[i + 1])
            rate_int += r_mid * dt[i]
            lam_mid = 0.5 * (lam[:, i] + lam[:, i + 1])
            prev_int = integ_lambda.copy()
            integ_lambda += lam_mid * dt[i]

            # detect default in this step: integ crosses threshold
            newly = (prev_int < threshold) & (integ_lambda >= threshold) & np.isinf(tau)
            if newly.any():
                t_def = tg[i + 1]
                tau[newly] = t_def
                ee_def = np.maximum(
                    self._swap_value(t_def, x[newly, i + 1], notional, fixed_rate,
                                     maturity, payer, pay_freq), 0.0)
                disc = np.exp(-rate_int[newly])
                cva_acc[newly] = self.lgd * ee_def * disc

        cva = float(cva_acc.mean())

        # exposure profile (for display) — EE/PFE of the live swap
        EE = np.zeros(n_steps + 1); PFE = np.zeros(n_steps + 1)
        for j, t in enumerate(tg):
            v = np.maximum(self._swap_value(t, x[:, j], notional, fixed_rate,
                                            maturity, payer, pay_freq), 0.0)
            EE[j] = v.mean(); PFE[j] = np.percentile(v, 95)
        dt_full = np.diff(tg, prepend=0.0)
        epe = float(np.dot(EE, dt_full) / max(T, 1e-8))

        return {
            'CVA': cva, 'EPE': epe, 'time_grid': tg, 'EE': EE, 'PFE': PFE,
            'default_prob': float(np.mean(np.isfinite(tau))),
            'mean_default_time': float(np.mean(tau[np.isfinite(tau)])) if np.isfinite(tau).any() else float('nan'),
            'rho': rho,
        }

    def wwr_multiplier(self, notional: float, fixed_rate: float, maturity: float,
                       rho: float, payer: bool = True, n_paths: int = 8000,
                       seed: int = 42) -> Dict:
        """
        Compute CVA with WWR (given ρ) vs independent (ρ=0) and the multiplier.
        Same random seed is used so the comparison is paired.
        """
        wwr = self.simulate_cva(notional, fixed_rate, maturity, rho=rho,
                                payer=payer, n_paths=n_paths, seed=seed)
        indep = self.simulate_cva(notional, fixed_rate, maturity, rho=0.0,
                                  payer=payer, n_paths=n_paths, seed=seed)
        mult = wwr['CVA'] / indep['CVA'] if indep['CVA'] > 1e-12 else float('nan')
        return {
            'CVA_wwr': wwr['CVA'], 'CVA_independent': indep['CVA'],
            'wwr_multiplier': mult, 'rho': rho,
            'time_grid': wwr['time_grid'], 'EE': wwr['EE'], 'PFE': wwr['PFE'],
            'default_prob': wwr['default_prob'],
        }
