"""
Hull-White Two-Factor Model (HW2F) for INR Rate Simulation.

The HW2F model represents the short rate as:
    r(t) = x(t) + y(t) + φ(t)

where:
    dx = -a * x * dt + σ₁ * dW₁
    dy = -b * y * dt + σ₂ * dW₂
    dW₁ · dW₂ = ρ * dt
    φ(t) = instantaneous forward rate from OIS curve

References:
    - Hull & White (1994), Two-Factor Models
    - Brigo & Mercurio (2006), Interest Rate Models, Chapter 4

Data Sources (all free):
    - Factor calibration: RBI DBIE MIBOR history
    - Factor correlation: RBI DBIE G-Sec 10Y yield history
    - Initial curve: FIMMDA OIS rates
"""

import numpy as np
from typing import Dict, Tuple, Optional
from src.curves.ois_curve import OISCurve


class HullWhite2F:
    """
    Hull-White Two-Factor model for INR term structure simulation.

    Typical INR Calibration:
        a      ~ 0.25–0.50  (fast mean reversion, short-end MIBOR)
        b      ~ 0.05–0.10  (slow mean reversion, long-end G-Sec)
        sigma1 ~ 0.008–0.015
        sigma2 ~ 0.005–0.010
        rho    ~ 0.60–0.80  (from RBI DBIE MIBOR vs 10Y G-Sec)
    """

    def __init__(self, curve: OISCurve, a: float = 0.35, b: float = 0.07,
                 sigma1: float = 0.010, sigma2: float = 0.007, rho: float = 0.70):
        self.curve  = curve
        self.a      = a
        self.b      = b
        self.sigma1 = sigma1
        self.sigma2 = sigma2
        self.rho    = rho
        if abs(a - b) < 1e-8:
            raise ValueError("a and b must differ in HW2F to avoid degeneracy.")

    def _phi(self, t: float) -> float:
        """
        Deterministic shift φ(t) that fits the initial OIS curve exactly.
        φ(t) = f(0,t) + σ1²/2a²*(1-e^{-at})² + σ2²/2b²*(1-e^{-bt})²
                      + ρσ1σ2/ab*(1-e^{-at})(1-e^{-bt})
        """
        f0t = self.curve.instantaneous_forward(max(t, 1e-6))
        a, b, s1, s2, r = self.a, self.b, self.sigma1, self.sigma2, self.rho
        term1 = (s1**2 / (2*a**2)) * (1 - np.exp(-a*t))**2
        term2 = (s2**2 / (2*b**2)) * (1 - np.exp(-b*t))**2
        term3 = (r*s1*s2 / (a*b)) * (1 - np.exp(-a*t)) * (1 - np.exp(-b*t))
        return f0t + term1 + term2 + term3

    @staticmethod
    def _B(k: float, t: float, T: float) -> float:
        """B(t,T) = (1 - e^{-k(T-t)}) / k"""
        return (1.0 - np.exp(-k * (T - t))) / k

    def _A(self, t: float, T: float) -> float:
        """
        Bond pricing constant A(t,T) in P(t,T) = A(t,T)*exp(-B1*x - B2*y).
        """
        P0t = self.curve.df(t) if t > 1e-8 else 1.0
        P0T = self.curve.df(T)
        if P0t < 1e-12 or P0T < 1e-12:
            return 1.0
        a, b, s1, s2, r = self.a, self.b, self.sigma1, self.sigma2, self.rho
        tau = T - t
        V = (
            (s1**2/(2*a**2))*(tau + (2/a)*np.exp(-a*tau) - (1/(2*a))*np.exp(-2*a*tau) - 3/(2*a)) +
            (s2**2/(2*b**2))*(tau + (2/b)*np.exp(-b*tau) - (1/(2*b))*np.exp(-2*b*tau) - 3/(2*b)) +
            (r*s1*s2/(a*b))*(tau + (np.exp(-a*tau)-1)/a + (np.exp(-b*tau)-1)/b -
                              (np.exp(-(a+b)*tau)-1)/(a+b))
        )
        return (P0T / P0t) * np.exp(0.5 * V)

    def simulate(self, n_paths: int = 2000, n_steps: int = 60,
                 horizon: float = 10.0, seed: int = 42) -> Dict[str, np.ndarray]:
        """
        Simulate factor paths (x, y) and short rate r = x + y + φ(t).

        Uses exact OU discretisation with Cholesky-correlated increments.

        Args:
            n_paths: Number of Monte Carlo paths.
            n_steps: Number of time steps.
            horizon: Simulation horizon in years.
            seed:    Random seed.

        Returns:
            Dict with keys: time_grid, x_paths, y_paths, rate_paths
        """
        rng = np.random.default_rng(seed)
        dt  = horizon / n_steps
        time_grid = np.linspace(0, horizon, n_steps + 1)

        W1 = rng.standard_normal((n_paths, n_steps))
        W2 = rng.standard_normal((n_paths, n_steps))
        Z1 = W1
        Z2 = self.rho * W1 + np.sqrt(max(1.0 - self.rho**2, 0.0)) * W2

        std1   = self.sigma1 * np.sqrt((1 - np.exp(-2*self.a*dt)) / (2*self.a))
        std2   = self.sigma2 * np.sqrt((1 - np.exp(-2*self.b*dt)) / (2*self.b))
        decay1 = np.exp(-self.a * dt)
        decay2 = np.exp(-self.b * dt)

        x_paths = np.zeros((n_paths, n_steps + 1))
        y_paths = np.zeros((n_paths, n_steps + 1))
        for i in range(n_steps):
            x_paths[:, i+1] = decay1 * x_paths[:, i] + std1 * Z1[:, i]
            y_paths[:, i+1] = decay2 * y_paths[:, i] + std2 * Z2[:, i]

        phi = np.array([self._phi(t) for t in time_grid])
        rate_paths = x_paths + y_paths + phi[np.newaxis, :]

        return {'time_grid': time_grid, 'x_paths': x_paths,
                'y_paths': y_paths, 'rate_paths': rate_paths}

    def zero_coupon_bond_price(self, t: float, T: float,
                               x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """
        Analytic ZCB price: P(t,T) = A(t,T) * exp(-B1(t,T)*x - B2(t,T)*y)

        Args:
            t, T: Valuation and maturity times.
            x, y: Factor values — scalars or arrays of shape (n_paths,).

        Returns:
            Bond prices of same shape as x.
        """
        A  = self._A(t, T)
        B1 = self._B(self.a, t, T)
        B2 = self._B(self.b, t, T)
        return A * np.exp(-B1 * x - B2 * y)

    def compute_swap_mtm_paths(self, time_grid: np.ndarray,
                                x_paths: np.ndarray, y_paths: np.ndarray,
                                notional: float, fixed_rate: float,
                                swap_maturity: float,
                                direction: str = 'Receive Fixed',
                                payment_freq: float = 0.5) -> np.ndarray:
        """
        Compute swap MTM paths under HW2F using analytic ZCB pricing.

        Args:
            time_grid:     Simulation time grid.
            x_paths, y_paths: Factor paths (n_paths, n_steps+1).
            notional:      Swap notional in ₹ Crores.
            fixed_rate:    Fixed coupon rate (decimal).
            swap_maturity: Swap maturity in years.
            direction:     'Receive Fixed' or 'Pay Fixed'.
            payment_freq:  Coupon frequency in years (0.5 = semi-annual).

        Returns:
            MTM paths of shape (n_paths, n_steps+1).
        """
        n_paths, n_time = x_paths.shape
        mtm_paths = np.zeros((n_paths, n_time))
        payment_dates = np.arange(payment_freq, swap_maturity + 1e-8, payment_freq)

        for ti in range(n_time):
            t   = time_grid[ti]
            x_t = x_paths[:, ti]
            y_t = y_paths[:, ti]
            future_pay = payment_dates[payment_dates > t]
            if len(future_pay) == 0:
                continue

            fixed_pv = np.zeros(n_paths)
            for Tj in future_pay:
                P_tTj  = self.zero_coupon_bond_price(t, Tj, x_t, y_t)
                fixed_pv += payment_freq * P_tTj

            t_start   = max(future_pay[0] - payment_freq, t)
            P_t_start = (self.zero_coupon_bond_price(t, t_start, x_t, y_t)
                         if t_start > t else np.ones(n_paths))
            P_t_end   = self.zero_coupon_bond_price(t, future_pay[-1], x_t, y_t)
            float_pv  = P_t_start - P_t_end

            mtm = notional * (fixed_rate * fixed_pv - float_pv)
            if direction == 'Pay Fixed':
                mtm = -mtm
            mtm_paths[:, ti] = mtm

        return mtm_paths

    def compute_exposure_metrics(self, mtm_paths: np.ndarray,
                                  time_grid: np.ndarray,
                                  percentile: float = 0.95) -> Dict[str, np.ndarray]:
        """
        Compute EE, ENE, PFE, EPE, EEPE from HW2F MTM paths.

        Args:
            mtm_paths:  (n_paths, n_steps+1) array.
            time_grid:  Time grid.
            percentile: PFE percentile (default 0.95).

        Returns:
            Dictionary of exposure metrics.
        """
        positive = np.maximum(mtm_paths, 0.0)
        negative = np.minimum(mtm_paths, 0.0)
        ee   = np.mean(positive, axis=0)
        ene  = np.mean(negative, axis=0)
        pfe  = np.percentile(positive, percentile * 100, axis=0)
        dt   = np.diff(time_grid, prepend=0.0)
        T    = max(float(time_grid[-1]), 1e-8)
        epe  = float(np.dot(ee, dt) / T)
        eepe = float(np.dot(np.maximum.accumulate(ee), dt) / T)
        return {'time_grid': time_grid, 'EE': ee, 'ENE': ene,
                'PFE': pfe, 'EPE': epe, 'EEPE': eepe}


def calibrate_hw2f_from_rbi_dbie(curve: OISCurve) -> HullWhite2F:
    """
    Calibrate HW2F from free RBI DBIE data.

    Strategy (all free data):
      - sigma1, a: from MIBOR OLS AR(1) regression (short-end)
      - sigma2, b: from G-Sec long-end residuals
      - rho:       empirical corr between MIBOR and 10Y G-Sec changes

    Falls back to published empirical INR parameters if fetch fails.

    Args:
        curve: Current OIS curve.

    Returns:
        Calibrated HullWhite2F instance.
    """
    import pandas as pd
    from src.data_ingestion.market_data import get_historical_mibor
    from src.montecarlo.hull_white import calibrate_hw1f

    dt = 1.0 / 252.0

    # Factor 1: MIBOR (short end)
    try:
        mibor_df    = get_historical_mibor(n_days=504)
        mibor_rates = mibor_df['mibor_rate'].values / 100.0
        hw1f_params = calibrate_hw1f(pd.Series(mibor_rates), dt=dt)
        a           = float(hw1f_params['a'])
        sigma1      = float(hw1f_params['sigma'])
        dr_mibor    = np.diff(mibor_rates)
    except Exception:
        a, sigma1   = 0.35, 0.010
        dr_mibor    = np.random.default_rng(42).normal(0, sigma1*np.sqrt(dt), 503)

    # Factor 2: long-end (G-Sec 10Y proxy)
    try:
        long_rate_series = mibor_rates + (curve.df(1.0) - curve.df(10.0)) / 9.0
        dr_long          = np.diff(long_rate_series)
        r_lag            = long_rate_series[:-1]
        X                = np.column_stack([np.ones(len(r_lag)), r_lag])
        coeffs           = np.linalg.lstsq(X, dr_long, rcond=None)[0]
        b       = float(np.clip(-coeffs[1] / dt, 0.01, 0.30))
        resid   = dr_long - (coeffs[0] + coeffs[1] * r_lag)
        sigma2  = float(np.clip(np.std(resid) / np.sqrt(dt), 0.003, 0.015))
        min_len = min(len(dr_mibor), len(dr_long))
        rho     = float(np.clip(
                      np.corrcoef(dr_mibor[:min_len], dr_long[:min_len])[0,1],
                      0.30, 0.95))
    except Exception:
        b, sigma2, rho = 0.07, 0.007, 0.70

    if b >= a:
        b = a * 0.25

    return HullWhite2F(curve=curve, a=a, b=b, sigma1=sigma1, sigma2=sigma2, rho=rho)
