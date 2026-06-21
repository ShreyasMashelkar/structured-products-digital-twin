"""
Hull-White One-Factor Monte Carlo Simulation Engine.

Simulates future INR OIS rate paths using the Hull-White 1-Factor (HW1F)
short-rate model. Computes exposure metrics for counterparty credit risk:
EE, EPE, PFE, ENE, EEPE.

Model SDE:
    dr(t) = [θ(t) - a·r(t)]dt + σ·dW(t)

where:
    r(t)  = short rate at time t
    θ(t)  = time-dependent drift (calibrated to fit current OIS curve)
    a     = mean reversion speed
    σ     = short rate volatility
    dW(t) = Wiener process increment

The θ(t) function is back-solved from the current OIS zero curve so that
the model exactly reproduces today's term structure (key HW1F property).
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple
from src.curves.ois_curve import OISCurve


class HullWhite1F:
    """
    Hull-White One-Factor Short-Rate Model.

    Provides calibration to the current OIS curve and Monte Carlo
    simulation of future rate paths and swap exposures.

    Attributes:
        a: Mean reversion speed.
        sigma: Short rate volatility.
        curve: Reference OIS discount curve.
    """

    def __init__(self, curve: OISCurve, a: float = 0.10,
                 sigma: float = 0.01):
        """
        Initialise the HW1F model.

        Args:
            curve: Current OIS curve (used for θ(t) calibration).
            a: Mean reversion speed (typical INR: 0.05–0.20).
            sigma: Short rate volatility (typical INR: 0.005–0.015).
        """
        self.curve = curve
        self.a = a
        self.sigma = sigma

    def _theta(self, t: float, dt: float = 1/365) -> float:
        """
        Compute the time-dependent drift θ(t) from the current OIS curve.

        θ(t) = ∂f(0,t)/∂t + a·f(0,t) + (σ²/2a)(1 - e^{-2at})

        where f(0,t) is the instantaneous forward rate from the OIS curve.

        Args:
            t: Time in years.
            dt: Small increment for numerical differentiation.

        Returns:
            θ(t) value.
        """
        # Instantaneous forward rate at t
        f_t = self.curve.instantaneous_forward(max(t, dt), dt)

        # Numerical derivative of forward rate
        f_t_plus = self.curve.instantaneous_forward(max(t + dt, dt), dt)
        f_t_minus = self.curve.instantaneous_forward(max(t - dt, dt), dt)
        df_dt = (f_t_plus - f_t_minus) / (2 * dt)

        # HW1F theta
        theta = df_dt + self.a * f_t + \
                (self.sigma ** 2 / (2 * self.a)) * (1 - np.exp(-2 * self.a * t))

        return theta

    def simulate_rates(self, n_paths: int = 1000,
                       n_steps: int = 60, horizon: float = 5.0,
                       seed: int = 42,
                       antithetic: bool = True) -> Tuple[np.ndarray, np.ndarray]:
        """
        Simulate short rate paths using exact transition density.
        Uses antithetic variates by default for variance reduction.

        Args:
            n_paths: Number of Monte Carlo paths.
            n_steps: Number of time steps.
            horizon: Simulation horizon in years.
            seed: Random seed for reproducibility.
            antithetic: Boolean flag for antithetic variates.

        Returns:
            Tuple of (time_grid, rate_paths).
        """
        rng = np.random.default_rng(seed)

        dt = horizon / n_steps
        time_grid = np.linspace(0, horizon, n_steps + 1)

        # Simulate exact mean-reverting process x(t)
        # dx(t) = -a * x(t) dt + sigma * dW(t)
        x = np.zeros((n_paths, n_steps + 1))
        
        if self.a > 1e-8:
            variance_dt = (self.sigma ** 2) * (1 - np.exp(-2 * self.a * dt)) / (2 * self.a)
            decay = np.exp(-self.a * dt)
        else:
            variance_dt = (self.sigma ** 2) * dt
            decay = 1.0
            
        std_dt = np.sqrt(variance_dt)
        # Generate standard normal increments
        if antithetic:
            n_half = (n_paths + 1) // 2
            Z_half = rng.standard_normal((n_half, n_steps))
            Z = np.concatenate([Z_half, -Z_half], axis=0)[:n_paths]
        else:
            Z = rng.standard_normal((n_paths, n_steps))
        
        for i in range(n_steps):
            x[:, i + 1] = x[:, i] * decay + std_dt * Z[:, i]

        rates = np.zeros_like(x)
        for i, t in enumerate(time_grid):
            # Compute deterministic shift alpha(t)
            if t == 0:
                f_t = self.curve.instantaneous_forward(0.001)
            else:
                f_t = self.curve.instantaneous_forward(t)
                
            if self.a > 1e-8:
                convexity = (self.sigma ** 2 / (2 * self.a ** 2)) * (1 - np.exp(-self.a * t)) ** 2
            else:
                convexity = 0.5 * self.sigma ** 2 * t ** 2
                
            alpha_t = f_t + convexity
            rates[:, i] = x[:, i] + alpha_t
            
            # Floor rates at a small positive value
            rates[:, i] = np.maximum(rates[:, i], 0.001)

        self._x_paths = x  # Store x(t) for exact bond pricing
        self._alpha_t = np.array([rates[0, i] - x[0, i] for i in range(n_steps + 1)])

        return time_grid, rates

    def simulate_discount_factors(self, time_grid: np.ndarray,
                                  rate_paths: np.ndarray) -> np.ndarray:
        """
        Compute path-wise discount factors from simulated rate paths.
        """
        n_paths, n_steps_plus_1 = rate_paths.shape
        dt_array = np.diff(time_grid)

        cum_rates = np.zeros((n_paths, n_steps_plus_1))
        for i in range(1, n_steps_plus_1):
            cum_rates[:, i] = cum_rates[:, i-1] + rate_paths[:, i-1] * dt_array[i-1]

        return np.exp(-cum_rates)

    def _B(self, t: float, T: float) -> float:
        """HW1F B(t,T) function: (1 - e^{-a(T-t)}) / a"""
        if self.a < 1e-10:
            return T - t
        return (1 - np.exp(-self.a * (T - t))) / self.a

    def compute_swap_mtm_paths(self, time_grid: np.ndarray,
                               rate_paths: np.ndarray,
                               notional: float,
                               fixed_rate: float,
                               maturity: float,
                               direction: str = 'Receive Fixed',
                               projection_curve: Optional[OISCurve] = None) -> np.ndarray:
        """
        Compute swap MTM on each path at each time step using exact HW1F bond pricing.
        """
        n_paths = rate_paths.shape[0]
        n_steps = len(time_grid) - 1

        mtm_paths = np.zeros((n_paths, n_steps + 1))

        for i, t in enumerate(time_grid):
            remaining = maturity - t
            if remaining <= 0.01:
                mtm_paths[:, i] = 0.0
                continue

            # Generate payment dates for remaining life
            payment_times = np.arange(1.0, remaining + 0.5, 1.0)
            if len(payment_times) == 0:
                payment_times = np.array([remaining])
            else:
                payment_times[-1] = min(payment_times[-1], remaining)
                if payment_times[-1] < remaining - 0.01:
                    payment_times = np.append(payment_times, remaining)

            dates_with_start = np.concatenate([[0.0], payment_times])
            deltas = np.diff(dates_with_start)
            
            x_t = self._x_paths[:, i]
            
            # Exact HW1F Zero-Coupon Bond Pricing: P(t, T)
            def P(t, T):
                B_t_T = self._B(t, T)
                A_t_T_part1 = self.curve.df(T) / self.curve.df(t)
                A_t_T_part2 = np.exp(0.5 * B_t_T**2 * (self.sigma**2 / (2*self.a)) * (1 - np.exp(-2*self.a*t)))
                A_t_T = A_t_T_part1 * A_t_T_part2
                return A_t_T * np.exp(-B_t_T * x_t)

            fixed_pv = np.zeros(n_paths)
            for j, T_pay in enumerate(payment_times):
                T = t + T_pay
                df_j = P(t, T)
                fixed_pv += fixed_rate * notional * deltas[j] * df_j

            if projection_curve is None:
                # Single-curve shortcut
                df_start = np.ones(n_paths)
                df_end = P(t, t + remaining)
                float_pv = notional * (df_start - df_end)
            else:
                # Multi-curve explicit projection
                float_pv = np.zeros(n_paths)
                for j, T_pay in enumerate(payment_times):
                    T1 = t + dates_with_start[j]
                    T2 = t + T_pay
                    # Forward rate implied from the PROJECTION curve
                    fwd = projection_curve.forward_rate(T1, T2)
                    df_j = P(t, T2)
                    float_pv += notional * fwd * deltas[j] * df_j

            if direction == 'Receive Fixed':
                mtm_paths[:, i] = fixed_pv - float_pv
            else:
                mtm_paths[:, i] = float_pv - fixed_pv

        return mtm_paths

    def compute_exposure_metrics(self, mtm_paths: np.ndarray,
                                 time_grid: np.ndarray,
                                 percentile: float = 95.0) -> Dict[str, np.ndarray]:
        """
        Compute CCR exposure metrics from MTM paths.

        Args:
            mtm_paths: MTM paths of shape (n_paths, n_steps+1).
            time_grid: Time grid of shape (n_steps+1,).
            percentile: Percentile for PFE (default 95%).

        Returns:
            Dictionary with:
                'time_grid': time points
                'EE': Expected Exposure at each time
                'PFE': Potential Future Exposure at percentile
                'ENE': Expected Negative Exposure at each time
                'EPE': Expected Positive Exposure (scalar, time-weighted average)
                'EEPE': Effective EPE (scalar)
        """
        positive_exposure = np.maximum(mtm_paths, 0.0)
        negative_exposure = np.minimum(mtm_paths, 0.0)

        # EE(t) = mean of max(MTM, 0) across paths
        ee = np.mean(positive_exposure, axis=0)

        # PFE(t) = percentile of positive exposure distribution
        pfe = np.percentile(positive_exposure, percentile, axis=0)

        # ENE(t) = mean of min(MTM, 0) across paths
        ene = np.mean(negative_exposure, axis=0)

        # EPE = time-weighted average of EE
        dt_array = np.diff(time_grid)
        if len(dt_array) > 0 and time_grid[-1] > 0:
            epe = np.sum(ee[1:] * dt_array) / time_grid[-1]
        else:
            epe = 0.0

        # EEPE: Effective EPE — time-weighted average of running-max EE
        # over the first year (Basel III definition, capped at 1Y)
        effective_ee = np.maximum.accumulate(ee)
        reg_horizon = min(time_grid[-1], 1.0)   # Basel III 1-year cap
        mask = time_grid[1:] <= reg_horizon + 1e-9   # include steps up to 1Y
        if mask.any() and reg_horizon > 0:
            eepe = np.sum(effective_ee[1:][mask] * dt_array[mask]) / reg_horizon
        else:
            eepe = effective_ee[1] if len(effective_ee) > 1 else 0.0

        return {
            'time_grid': time_grid,
            'EE': ee,
            'PFE': pfe,
            'ENE': ene,
            'EPE': epe,
            'EEPE': eepe,
        }


def run_exposure_simulation(curve: OISCurve,
                            notional: float = 500.0,
                            fixed_rate: float = 0.07,
                            maturity: float = 5.0,
                            direction: str = 'Receive Fixed',
                            n_paths: int = 10000,
                            n_steps: int = 60,
                            a: float = 0.10,
                            sigma: float = 0.01,
                            seed: int = 42) -> Dict:
    """
    Convenience function: run a full exposure simulation for a single swap.

    Args:
        curve: OIS discount curve.
        notional: Notional in ₹ Crores.
        fixed_rate: Fixed leg rate.
        maturity: Maturity in years.
        direction: Trade direction.
        n_paths: Number of MC paths.
        n_steps: Number of time steps.
        a: HW1F mean reversion speed.
        sigma: HW1F short rate volatility.
        seed: Random seed.

    Returns:
        Dictionary with exposure metrics and paths.
    """
    model = HullWhite1F(curve, a=a, sigma=sigma)

    time_grid, rate_paths = model.simulate_rates(
        n_paths=n_paths, n_steps=n_steps,
        horizon=maturity, seed=seed
    )

    mtm_paths = model.compute_swap_mtm_paths(
        time_grid, rate_paths,
        notional=notional, fixed_rate=fixed_rate,
        maturity=maturity, direction=direction
    )

    metrics = model.compute_exposure_metrics(mtm_paths, time_grid)

    return {
        'time_grid': time_grid,
        'rate_paths': rate_paths,
        'mtm_paths': mtm_paths,
        'metrics': metrics,
        'model': model,
    }

def calibrate_hw1f(mibor_series: 'pd.Series',
                   dt: float = 1 / 252) -> dict:
    """
    Calibrate Hull-White 1-Factor parameters from a historical MIBOR
    time series using Ordinary Least Squares.

    The SDE dr = a(theta - r)dt + sigma*dW is discretised as:
        dr = alpha + beta*r + noise
    where:
        alpha = a * theta * dt
        beta  = -a * dt

    OLS on this regression yields estimates of a and the long-run mean.
    Residual standard deviation gives sigma.

    Args:
        mibor_series: Series of daily overnight MIBOR rates (e.g. from
                      get_historical_mibor()). Values as decimals (0.065).
        dt: Time step in years (default 1/252 for business day).

    Returns:
        Dictionary with keys:
            'a'           : mean reversion speed
            'sigma'       : annualised short-rate volatility
            'theta_longrun': long-run mean rate
            'r_squared'   : OLS fit quality
    """
    import numpy as np
    import pandas as pd

    rates = np.array(mibor_series, dtype=float)
    # Filter out any zeros or NaNs
    valid = np.isfinite(rates) & (rates > 0)
    rates = rates[valid]

    if len(rates) < 30:
        # Not enough data — return market convention defaults
        return {'a': 0.10, 'sigma': 0.010, 'theta_longrun': rates.mean() if len(rates) > 0 else 0.065, 'r_squared': 0.0}

    dr = np.diff(rates)
    r_lag = rates[:-1]

    # OLS: dr = alpha + beta * r_lag
    X = np.column_stack([np.ones(len(r_lag)), r_lag])
    # Normal equations: (X'X)^{-1} X'y
    XtX = X.T @ X
    Xty = X.T @ dr

    try:
        coeffs = np.linalg.solve(XtX, Xty)
    except np.linalg.LinAlgError:
        return {'a': 0.10, 'sigma': 0.010, 'theta_longrun': rates.mean(), 'r_squared': 0.0}

    alpha_hat, beta_hat = coeffs

    # Recover model parameters
    a_hat = -beta_hat / dt
    theta_hat = alpha_hat / (a_hat * dt) if abs(a_hat) > 1e-8 else rates.mean()

    # Sigma from residual std dev
    dr_fitted = alpha_hat + beta_hat * r_lag
    residuals = dr - dr_fitted
    sigma_hat = float(np.std(residuals, ddof=2)) / np.sqrt(dt)

    # R-squared
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((dr - np.mean(dr)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-15 else 0.0

    # Sanity-clip to realistic INR market ranges
    a_hat = float(np.clip(a_hat, 0.01, 0.50))
    sigma_hat = float(np.clip(sigma_hat, 0.001, 0.05))
    theta_hat = float(np.clip(theta_hat, 0.02, 0.20))

    return {
        'a': a_hat,
        'sigma': sigma_hat,
        'theta_longrun': theta_hat,
        'r_squared': float(r2),
    }
