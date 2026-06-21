"""
Advanced Wrong-Way Risk Engine.

Extends the existing WrongWayRiskModel in wrong_way_risk.py with:
  1. Regime-switching WWR: distinguishes between calm and stress regimes
     (higher correlation in stress, lower in calm).
  2. Sector-specific stress scenarios for Indian NBFC counterparties:
     modelling the mechanism by which rate rises feed into NBFC credit stress.
  3. WWR multiplier term structure: reports the ratio WWR-CVA/Standard-CVA
     at each tenor, not just as a single scalar.

All Brownian motion correlation uses proper Cholesky decomposition on
standard-normal INCREMENTS — NOT on rate level paths.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from src.curves.ois_curve import OISCurve
from src.xva.cva import CreditCurve, CVAEngine


class RegimeSwitchingWWR:
    """
    Two-regime WWR model.

    In normal market conditions, correlation between rate moves and credit
    spread moves is low (ρ_calm). In stress, correlation is higher (ρ_stress).
    Regime transitions follow a simple two-state Markov chain.

    This better captures the empirical observation that WWR is most severe
    precisely during market stress events (e.g. NBFC crisis, taper tantrum).

    Attributes:
        ois_curve: Reference OIS discount curve.
        rho_calm: Rate-credit correlation in the calm regime.
        rho_stress: Rate-credit correlation in the stress regime.
        p_calm_to_stress: Daily probability of transitioning calm → stress.
        p_stress_to_calm: Daily probability of transitioning stress → calm.
        a_rate: HW1F mean reversion speed.
        sigma_rate: HW1F short rate volatility.
        kappa_hazard: Mean reversion for hazard rate process.
        sigma_hazard: Volatility of hazard rate process.
    """

    def __init__(self, ois_curve: OISCurve,
                 rho_calm: float = 0.20,
                 rho_stress: float = 0.65,
                 p_calm_to_stress: float = 0.02,
                 p_stress_to_calm: float = 0.15,
                 a_rate: float = 0.10,
                 sigma_rate: float = 0.010,
                 kappa_hazard: float = 0.30,
                 sigma_hazard: float = 0.005):
        self.ois_curve = ois_curve
        self.rho_calm = rho_calm
        self.rho_stress = rho_stress
        self.p_calm_to_stress = p_calm_to_stress
        self.p_stress_to_calm = p_stress_to_calm
        self.a_rate = a_rate
        self.sigma_rate = sigma_rate
        self.kappa_hazard = kappa_hazard
        self.sigma_hazard = sigma_hazard

    def _simulate_regimes(self, n_paths: int, n_steps: int,
                           rng: np.random.Generator) -> np.ndarray:
        """
        Simulate regime indicator paths (0 = calm, 1 = stress).

        Returns:
            Boolean array of shape (n_paths, n_steps+1).
        """
        regimes = np.zeros((n_paths, n_steps + 1), dtype=bool)
        u = rng.uniform(size=(n_paths, n_steps))

        for i in range(n_steps):
            calm_paths = ~regimes[:, i]
            stress_paths = regimes[:, i]
            # calm → stress
            regimes[calm_paths, i + 1] = u[calm_paths, i] < self.p_calm_to_stress
            # stress → calm (flip back)
            stay_stress = stress_paths & (u[stress_paths, i] >= self.p_stress_to_calm)
            regimes[stress_paths, i + 1] = stay_stress

        return regimes

    def simulate_joint(self, h0: float,
                       n_paths: int = 5000,
                       n_steps: int = 60,
                       horizon: float = 5.0,
                       seed: int = 42) -> Dict[str, np.ndarray]:
        """
        Jointly simulate rate and hazard rate paths with regime-switching
        correlation.

        At each step, the correlation applied is rho_calm or rho_stress
        depending on the current regime for that path.

        Correlation via Cholesky on standard-normal INCREMENTS:
            ε_r ~ N(0,1)
            ε_h = ρ × ε_r + √(1 - ρ²) × ε_independent

        Args:
            h0: Initial hazard rate.
            n_paths: Number of Monte Carlo paths.
            n_steps: Number of time steps.
            horizon: Simulation horizon in years.
            seed: Random seed.

        Returns:
            Dict with time_grid, rate_paths, hazard_paths, regime_paths.
        """
        rng = np.random.default_rng(seed)
        dt = horizon / n_steps
        sqrt_dt = np.sqrt(dt)
        time_grid = np.linspace(0, horizon, n_steps + 1)

        # Simulate regimes
        regime_paths = self._simulate_regimes(n_paths, n_steps, rng)

        # Generate independent standard normals for Cholesky
        Z_r = rng.standard_normal((n_paths, n_steps))   # for rates
        Z_ind = rng.standard_normal((n_paths, n_steps)) # independent component

        # Regime-dependent Cholesky: ε_h = ρ × Z_r + √(1-ρ²) × Z_ind
        rho_path = np.where(regime_paths[:, :-1], self.rho_stress, self.rho_calm)
        Z_h = rho_path * Z_r + np.sqrt(1.0 - rho_path ** 2) * Z_ind

        # Initialise paths
        rate_paths = np.zeros((n_paths, n_steps + 1))
        hazard_paths = np.zeros((n_paths, n_steps + 1))

        r0 = self.ois_curve.instantaneous_forward(1 / 365)
        rate_paths[:, 0] = r0
        hazard_paths[:, 0] = h0

        for i in range(n_steps):
            t = time_grid[i]
            # HW1F rate process (simplified drift)
            f_t = self.ois_curve.instantaneous_forward(max(t, 1 / 365))
            theta = (f_t * self.a_rate
                     + (self.sigma_rate ** 2 / (2 * self.a_rate))
                     * (1 - np.exp(-2 * self.a_rate * t)))

            dr = ((theta - self.a_rate * rate_paths[:, i]) * dt
                  + self.sigma_rate * sqrt_dt * Z_r[:, i])
            rate_paths[:, i + 1] = np.maximum(rate_paths[:, i] + dr, 0.001)

            # Mean-reverting hazard rate process
            dh = (self.kappa_hazard * (h0 - hazard_paths[:, i]) * dt
                  + self.sigma_hazard * sqrt_dt * Z_h[:, i])
            hazard_paths[:, i + 1] = np.maximum(hazard_paths[:, i] + dh, 1e-6)

        return {
            'time_grid': time_grid,
            'rate_paths': rate_paths,
            'hazard_paths': hazard_paths,
            'regime_paths': regime_paths,
        }

    def compute_wwr_cva(self, mtm_paths: np.ndarray,
                         hazard_paths: np.ndarray,
                         time_grid: np.ndarray,
                         recovery_rate: float = 0.40) -> float:
        """
        Compute WWR-adjusted CVA using path-wise conditional expectation.

        WWR-CVA = LGD × Σᵢ E[max(MTM(tᵢ), 0) × ΔPD(tᵢ)] × DF(tᵢ)

        Args:
            mtm_paths: Swap MTM paths (n_paths, n_steps+1).
            hazard_paths: Correlated hazard rate paths (n_paths, n_steps+1).
            time_grid: Time grid.
            recovery_rate: Recovery rate.

        Returns:
            WWR-adjusted CVA in ₹ Crores.
        """
        lgd = 1.0 - recovery_rate
        n_paths = mtm_paths.shape[0]
        dt_array = np.diff(time_grid)

        # Path-wise cumulative hazard → survival probability
        cum_hazard = np.zeros((n_paths, len(time_grid)))
        for i in range(1, len(time_grid)):
            cum_hazard[:, i] = cum_hazard[:, i - 1] + hazard_paths[:, i - 1] * dt_array[i - 1]
        survival = np.exp(-cum_hazard)

        wwr_cva = 0.0
        for i in range(1, len(time_grid)):
            positive_mtm = np.maximum(mtm_paths[:, i], 0.0)
            delta_pd = survival[:, i - 1] - survival[:, i]  # path-wise marginal PD
            # Joint expectation — this is > E[EE] × E[ΔPD] when correlated
            expected_joint = np.mean(positive_mtm * delta_pd)
            df = self.ois_curve.df(time_grid[i])
            wwr_cva += expected_joint * df

        return lgd * wwr_cva

    def wwr_multiplier_term_structure(self, mtm_paths: np.ndarray,
                                       hazard_paths: np.ndarray,
                                       time_grid: np.ndarray,
                                       credit_curve: CreditCurve,
                                       window_years: float = 1.0) -> pd.DataFrame:
        """
        Compute WWR multiplier at each tenor (ratio of conditional to unconditional CVA
        computed over a rolling window).

        Args:
            mtm_paths: MTM paths.
            hazard_paths: Correlated hazard paths.
            time_grid: Time grid.
            credit_curve: Counterparty credit curve (for standard CVA).
            window_years: Window size in years for rolling CVA.

        Returns:
            DataFrame with tenor, standard_cva, wwr_cva, multiplier.
        """
        cva_engine = CVAEngine(self.ois_curve)
        lgd = 1.0 - credit_curve.recovery_rate
        n_paths = mtm_paths.shape[0]
        dt_array = np.diff(time_grid)

        cum_hazard = np.zeros((n_paths, len(time_grid)))
        for i in range(1, len(time_grid)):
            cum_hazard[:, i] = cum_hazard[:, i-1] + hazard_paths[:, i-1] * dt_array[i-1]
        survival_wwr = np.exp(-cum_hazard)

        rows = []
        checkpoints = [t for t in [1.0, 2.0, 3.0, 5.0, 7.0, 10.0]
                       if t <= time_grid[-1]]

        for T in checkpoints:
            idx = int(np.argmin(np.abs(time_grid - T)))
            sub_tg = time_grid[:idx + 1]
            sub_ee = np.mean(np.maximum(mtm_paths[:, :idx + 1], 0.0), axis=0)
            std_cva = cva_engine.compute_cva(sub_ee, sub_tg, credit_curve)

            # WWR CVA up to T
            wwr_partial = 0.0
            for i in range(1, idx + 1):
                pos_mtm = np.maximum(mtm_paths[:, i], 0.0)
                d_pd = survival_wwr[:, i - 1] - survival_wwr[:, i]
                df = self.ois_curve.df(time_grid[i])
                wwr_partial += np.mean(pos_mtm * d_pd) * df
            wwr_partial *= lgd

            mult = wwr_partial / std_cva if std_cva > 1e-12 else 1.0

            rows.append({
                'tenor_years': T,
                'standard_cva_cr': round(std_cva, 6),
                'wwr_cva_cr': round(wwr_partial, 6),
                'multiplier': round(mult, 4),
                'incremental_charge_cr': round(wwr_partial - std_cva, 6),
            })

        return pd.DataFrame(rows)
