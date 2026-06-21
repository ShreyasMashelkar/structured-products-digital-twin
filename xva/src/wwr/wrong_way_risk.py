"""
Wrong-Way Risk (WWR) Module.

Models the correlation between counterparty credit quality and
derivative exposure. In WWR, the counterparty is most likely to
default precisely when the exposure is largest.

Uses a joint simulation of:
- Short rate r(t) — from Hull-White 1F
- Hazard rate h(t) — mean-reverting process correlated with r(t)

Correlation is introduced via Cholesky decomposition of the
Brownian motion increments.

Indian NBFC example: when RBI tightens (rates rise), NBFC funding
costs increase, credit spreads widen, and pay-fixed swaps become
in-the-money — classic wrong-way risk.
"""

import numpy as np
from typing import Dict, Optional, Tuple
from src.curves.ois_curve import OISCurve
from src.xva.cva import CreditCurve


class WrongWayRiskModel:
    """
    Wrong-Way Risk model using correlated rate-credit simulation.

    Attributes:
        ois_curve: Reference OIS discount curve.
        a_rate: Mean reversion speed for short rate.
        sigma_rate: Volatility of short rate.
        kappa_hazard: Mean reversion speed for hazard rate.
        sigma_hazard: Volatility of hazard rate.
        rho: Correlation between rate and credit (ρ > 0 = WWR).
    """

    def __init__(self, ois_curve: OISCurve,
                 a_rate: float = 0.10, sigma_rate: float = 0.01,
                 kappa_hazard: float = 0.30, sigma_hazard: float = 0.005,
                 rho: float = 0.50):
        """
        Initialise the WWR model.

        Args:
            ois_curve: Current OIS curve.
            a_rate: Mean reversion for short rate.
            sigma_rate: Short rate volatility.
            kappa_hazard: Mean reversion for hazard rate.
            sigma_hazard: Hazard rate volatility.
            rho: Rate-credit correlation (-1 to +1).
                 ρ > 0: Wrong-way risk
                 ρ < 0: Right-way risk
                 ρ = 0: Independent (standard CVA)
        """
        self.ois_curve = ois_curve
        self.a_rate = a_rate
        self.sigma_rate = sigma_rate
        self.kappa_hazard = kappa_hazard
        self.sigma_hazard = sigma_hazard
        self.rho = rho

    def simulate_joint(self, h0: float, n_paths: int = 10000,
                       n_steps: int = 60, horizon: float = 5.0,
                       seed: int = 42) -> Dict[str, np.ndarray]:
        """
        Jointly simulate rate paths and hazard rate paths.

        dr(t) = [θ(t) - a·r(t)]dt + σ_r·dW_r(t)
        dh(t) = κ[h̄ - h(t)]dt + σ_h·dW_h(t)

        with: dW_r · dW_h = ρ·dt

        Cholesky decomposition:
            ε_r = Z₁
            ε_h = ρ·Z₁ + √(1-ρ²)·Z₂

        Args:
            h0: Initial hazard rate (from CDS spread).
            n_paths: Number of Monte Carlo paths.
            n_steps: Number of time steps.
            horizon: Simulation horizon in years.
            seed: Random seed.

        Returns:
            Dictionary with time_grid, rate_paths, hazard_paths.
        """
        rng = np.random.default_rng(seed)

        dt = horizon / n_steps
        sqrt_dt = np.sqrt(dt)
        time_grid = np.linspace(0, horizon, n_steps + 1)

        # Initial values
        r0 = self.ois_curve.instantaneous_forward(1/365)

        rate_paths = np.zeros((n_paths, n_steps + 1))
        hazard_paths = np.zeros((n_paths, n_steps + 1))
        rate_paths[:, 0] = r0
        hazard_paths[:, 0] = h0

        # Generate correlated random numbers using Cholesky
        Z1 = rng.standard_normal((n_paths, n_steps))
        Z2 = rng.standard_normal((n_paths, n_steps))

        eps_r = Z1
        eps_h = self.rho * Z1 + np.sqrt(1 - self.rho**2) * Z2

        for i in range(n_steps):
            t = time_grid[i]

            # Rate process (simplified HW1F)
            f_t = self.ois_curve.instantaneous_forward(max(t, 1/365))
            theta = f_t * self.a_rate + self.sigma_rate**2 / (2*self.a_rate) * \
                    (1 - np.exp(-2*self.a_rate*t))

            dr = (theta - self.a_rate * rate_paths[:, i]) * dt + \
                 self.sigma_rate * sqrt_dt * eps_r[:, i]
            rate_paths[:, i+1] = np.maximum(rate_paths[:, i] + dr, 0.001)

            # Hazard rate process
            dh = self.kappa_hazard * (h0 - hazard_paths[:, i]) * dt + \
                 self.sigma_hazard * sqrt_dt * eps_h[:, i]
            hazard_paths[:, i+1] = np.maximum(hazard_paths[:, i] + dh, 1e-6)

        return {
            'time_grid': time_grid,
            'rate_paths': rate_paths,
            'hazard_paths': hazard_paths,
        }

    def compute_wwr_cva(self, mtm_paths: np.ndarray,
                        hazard_paths: np.ndarray,
                        time_grid: np.ndarray,
                        recovery_rate: float = 0.40) -> float:
        """
        Compute WWR-adjusted CVA.

        WWR-CVA = -LGD × Σᵢ [E[EE(tᵢ) × h(tᵢ)] × Δt × DF(tᵢ)]

        Under wrong-way risk, the conditional expectation
        E[EE|default] > E[EE] × P[default], producing higher CVA.

        Args:
            mtm_paths: Swap MTM paths (n_paths, n_steps+1).
            hazard_paths: Simulated hazard rate paths (n_paths, n_steps+1).
            time_grid: Time grid.
            recovery_rate: Recovery rate.

        Returns:
            WWR-adjusted CVA in ₹ Crores.
        """
        lgd = 1.0 - recovery_rate
        n_paths = mtm_paths.shape[0]

        # Compute survival probabilities path-wise
        dt_array = np.diff(time_grid)
        cum_hazard = np.zeros((n_paths, len(time_grid)))
        for i in range(1, len(time_grid)):
            cum_hazard[:, i] = cum_hazard[:, i-1] + \
                               hazard_paths[:, i-1] * dt_array[i-1]

        survival = np.exp(-cum_hazard)

        # Marginal default probabilities
        wwr_cva = 0.0
        for i in range(1, len(time_grid)):
            # Path-wise: EE × ΔPD
            positive_mtm = np.maximum(mtm_paths[:, i], 0.0)
            delta_pd = survival[:, i-1] - survival[:, i]

            # Key WWR effect: E[EE × ΔPD] ≠ E[EE] × E[ΔPD]
            # when they are correlated
            expected_loss = np.mean(positive_mtm * delta_pd)

            df = self.ois_curve.df(time_grid[i])
            wwr_cva += expected_loss * df

        return lgd * wwr_cva

    def compare_standard_vs_wwr(self, mtm_paths: np.ndarray,
                                 hazard_paths: np.ndarray,
                                 time_grid: np.ndarray,
                                 credit_curve: CreditCurve) -> Dict[str, float]:
        """
        Compare standard CVA (independent) vs WWR-CVA.

        Args:
            mtm_paths: MTM paths.
            hazard_paths: Simulated hazard paths.
            time_grid: Time grid.
            credit_curve: Counterparty credit curve.

        Returns:
            Dictionary with Standard_CVA, WWR_CVA, and multiplier.
        """
        from src.xva.cva import CVAEngine

        # Standard CVA (using unconditional EE × marginal PD)
        ee = np.mean(np.maximum(mtm_paths, 0.0), axis=0)
        cva_engine = CVAEngine(self.ois_curve)
        standard_cva = cva_engine.compute_cva(ee, time_grid, credit_curve)

        # WWR CVA (using conditional expectation)
        wwr_cva = self.compute_wwr_cva(
            mtm_paths, hazard_paths, time_grid,
            recovery_rate=credit_curve.recovery_rate
        )

        multiplier = wwr_cva / standard_cva if standard_cva > 1e-12 else 1.0

        return {
            'Standard_CVA': standard_cva,
            'WWR_CVA': wwr_cva,
            'Multiplier': multiplier,
        }


def run_wwr_stress_scenarios(ois_curve: OISCurve,
                              cds_spread_bps: float = 150.0,
                              recovery: float = 0.40,
                              correlations: list = None) -> pd.DataFrame:
    """
    Run WWR analysis across different correlation assumptions.

    Args:
        ois_curve: OIS curve.
        cds_spread_bps: Counterparty CDS spread.
        recovery: Recovery rate.
        correlations: List of correlations to test.

    Returns:
        DataFrame comparing CVA under different correlations.
    """
    if correlations is None:
        correlations = [-0.30, 0.0, 0.30, 0.50, 0.70]

    credit_curve = CreditCurve(cds_spread_bps, recovery)
    h0 = credit_curve.hazard_rate

    results = []
    for rho in correlations:
        model = WrongWayRiskModel(ois_curve, rho=rho)
        sim = model.simulate_joint(h0, n_paths=5000, n_steps=60,
                                    horizon=5.0, seed=42)

        # Simple MTM approximation for comparison
        # Use rate paths to generate approximate swap MTM
        from src.montecarlo.hull_white import HullWhite1F
        hw = HullWhite1F(ois_curve)
        mtm_paths = hw.compute_swap_mtm_paths(
            sim['time_grid'], sim['rate_paths'],
            notional=500.0, fixed_rate=0.07, maturity=5.0,
            direction='Receive Fixed'
        )

        comparison = model.compare_standard_vs_wwr(
            mtm_paths, sim['hazard_paths'],
            sim['time_grid'], credit_curve
        )

        results.append({
            'correlation': rho,
            'risk_type': 'Right-Way' if rho < 0 else ('Independent' if rho == 0 else 'Wrong-Way'),
            'Standard_CVA_cr': comparison['Standard_CVA'],
            'WWR_CVA_cr': comparison['WWR_CVA'],
            'Multiplier': comparison['Multiplier'],
        })

    return pd.DataFrame(results)
