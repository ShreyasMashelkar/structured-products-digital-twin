"""
Longstaff-Schwartz (LSM) American/Bermudan exposure engine.

Callable trades (Bermudan swaptions, cancellable swaps) dominate real XVA
books, and their exposure cannot be obtained from a European/forward-swap
profile — the early-exercise boundary reshapes it. The market-standard method
is Least-Squares Monte Carlo (Longstaff & Schwartz, 2001): regress the
continuation value on basis functions of the state variable, compare to the
immediate exercise value, and propagate the optimal stopping rule.

This module:
  1. Simulates the Hull-White 1F short rate with analytic ZCB pricing.
  2. Prices a co-terminal Bermudan payer/receiver swaption via LSM.
  3. Produces the CCR exposure profile (EE / PFE / ENE) of the callable,
     accounting for path-wise early exercise.

Pure NumPy — no external dependencies.

Reference: Longstaff & Schwartz (2001), "Valuing American Options by
Simulation: A Simple Least-Squares Approach", RFS.
"""

import numpy as np
from typing import Dict, List, Optional
from src.curves.ois_curve import OISCurve


class HullWhite1FBonds:
    """Minimal HW1F short-rate model with analytic zero-coupon bond prices."""

    def __init__(self, curve: OISCurve, a: float = 0.10, sigma: float = 0.01):
        self.curve = curve
        self.a = a
        self.sigma = sigma

    def _B(self, t: float, T: float) -> float:
        return (1.0 - np.exp(-self.a * (T - t))) / self.a

    def _A(self, t: float, T: float) -> float:
        # Andersen-Piterbarg "y-process" reconstitution: at x(t)=0 the bond
        # equals the forward bond P(0,T)/P(0,t) times a small convexity term,
        # guaranteeing arbitrage-free, correctly-levelled bond prices.
        P0t = self.curve.df(t) if t > 1e-9 else 1.0
        P0T = self.curve.df(T)
        B = self._B(t, T)
        y = (self.sigma ** 2) / (2 * self.a) * (1 - np.exp(-2 * self.a * t))  # Var[x(t)]
        return (P0T / P0t) * np.exp(-0.5 * (B ** 2) * y)

    def bond_price(self, t: float, T: float, x: np.ndarray) -> np.ndarray:
        """P(t,T) given the OU factor x(t) (array over paths)."""
        return self._A(t, T) * np.exp(-self._B(t, T) * x)

    def simulate_factor(self, time_grid: np.ndarray, n_paths: int,
                        normals: Optional[np.ndarray] = None,
                        seed: int = 42) -> np.ndarray:
        """Exact OU simulation of x(t); returns (n_paths, n_steps+1)."""
        n_steps = len(time_grid) - 1
        if normals is None:
            rng = np.random.default_rng(seed)
            normals = rng.standard_normal((n_paths, n_steps))
        x = np.zeros((n_paths, n_steps + 1))
        for i in range(n_steps):
            dt = time_grid[i + 1] - time_grid[i]
            decay = np.exp(-self.a * dt)
            std = self.sigma * np.sqrt((1 - np.exp(-2 * self.a * dt)) / (2 * self.a))
            x[:, i + 1] = decay * x[:, i] + std * normals[:, i]
        return x


class BermudanSwaptionLSM:
    """
    Bermudan swaption pricing and exposure via Longstaff-Schwartz.

    A co-terminal Bermudan payer (or receiver) swaption: at each exercise
    date the holder may enter the swap running from that date to the common
    final maturity.
    """

    def __init__(self, curve: OISCurve, notional: float, strike: float,
                 exercise_dates: List[float], final_maturity: float,
                 payer: bool = True, pay_freq: float = 1.0,
                 a: float = 0.10, sigma: float = 0.01):
        self.curve = curve
        self.notional = notional
        self.strike = strike
        self.exercise_dates = sorted(exercise_dates)
        self.final_maturity = final_maturity
        self.payer = payer
        self.pay_freq = pay_freq
        self.hw = HullWhite1FBonds(curve, a, sigma)

    def _swap_value(self, t: float, x: np.ndarray) -> np.ndarray:
        """Underlying swap PV at time t (entered now, ending at final maturity)."""
        pay_dates = np.arange(t + self.pay_freq, self.final_maturity + 1e-8, self.pay_freq)
        if len(pay_dates) == 0:
            return np.zeros_like(x)
        annuity = np.zeros_like(x)
        for Tj in pay_dates:
            annuity += self.pay_freq * self.hw.bond_price(t, Tj, x)
        P_end = self.hw.bond_price(t, pay_dates[-1], x)
        float_leg = 1.0 - P_end                  # P(t,t)=1 minus P(t,T_N)
        fixed_leg = self.strike * annuity
        val = self.notional * (float_leg - fixed_leg)
        return val if self.payer else -val

    def price_and_exposure(self, n_paths: int = 5000, n_steps_per_year: int = 4,
                           normals: Optional[np.ndarray] = None,
                           seed: int = 42) -> Dict:
        """
        Price the Bermudan and build its exposure profile.

        Returns dict with:
            price        : Bermudan swaption PV (₹ Cr)
            european_ref : value if only the last exercise date were available
            time_grid, EE, ENE, PFE : exposure profile of the callable
        """
        T = self.final_maturity
        n_steps = max(2, int(round(T * n_steps_per_year)))
        time_grid = np.linspace(0, T, n_steps + 1)
        x = self.hw.simulate_factor(time_grid, n_paths, normals=normals, seed=seed)

        # short rate r(t) ≈ x(t) + f(0,t); discount via path integral of r
        f0 = np.array([self.curve.instantaneous_forward(max(t, 1e-6)) for t in time_grid])
        r = x + f0[np.newaxis, :]
        dt = np.diff(time_grid)
        # stochastic discount factor to each node
        integ = np.cumsum(0.5 * (r[:, :-1] + r[:, 1:]) * dt[np.newaxis, :], axis=1)
        disc = np.hstack([np.ones((n_paths, 1)), np.exp(-integ)])   # (n_paths, n_steps+1)

        # map exercise dates to nearest grid index
        ex_idx = [int(np.argmin(np.abs(time_grid - ed))) for ed in self.exercise_dates]
        ex_idx = sorted(set(i for i in ex_idx if 0 < i < len(time_grid)))

        # ---- LSM backward induction for the optimal cashflow (discounted to 0) ----
        cashflow0 = np.zeros(n_paths)            # PV at t=0 of exercising on each path
        exercised_at = np.full(n_paths, len(time_grid))  # step index of exercise (or none)

        for k in reversed(range(len(ex_idx))):
            idx = ex_idx[k]
            t = time_grid[idx]
            xt = x[:, idx]
            immediate = np.maximum(self._swap_value(t, xt), 0.0)
            itm = immediate > 1e-12
            if k == len(ex_idx) - 1:
                # last date: exercise iff ITM
                ex_now = itm
            else:
                # regress discounted future value on basis of state
                future_pv0 = cashflow0.copy()
                disc_t = disc[:, idx]
                cont_pv_t = np.where(disc_t > 0, future_pv0 / np.maximum(disc_t, 1e-12), 0.0)
                if itm.sum() >= 6:
                    xs = xt[itm]
                    A = np.column_stack([np.ones_like(xs), xs, xs ** 2, xs ** 3])
                    coef, *_ = np.linalg.lstsq(A, cont_pv_t[itm], rcond=None)
                    cont_est = A @ coef
                    ex_now = np.zeros(n_paths, dtype=bool)
                    ex_now[itm] = immediate[itm] > cont_est
                else:
                    ex_now = itm & (immediate > cont_pv_t)
            # update cashflow for paths exercising now
            cashflow0 = np.where(ex_now, immediate * disc[:, idx], cashflow0)
            exercised_at = np.where(ex_now, idx, exercised_at)

        price = float(cashflow0.mean())

        # European reference: only last exercise date
        last = ex_idx[-1]
        eur_imm = np.maximum(self._swap_value(time_grid[last], x[:, last]), 0.0)
        european_ref = float((eur_imm * disc[:, last]).mean())

        # ---- exposure profile ----
        # value at each node: option continuation value pre-exercise; swap MTM
        # after exercise. Approximate option value path-wise by the discounted
        # realised exercise payoff (perfect-foresight upper bound is avoided by
        # using the LSM stopping rule already computed).
        EE = np.zeros(len(time_grid)); ENE = np.zeros(len(time_grid)); PFE = np.zeros(len(time_grid))
        for j, t in enumerate(time_grid):
            val = np.zeros(n_paths)
            # exercised on/before this node → underlying swap MTM
            done = exercised_at <= j
            if done.any():
                val[done] = self._swap_value(t, x[done, j])
            # not yet exercised → option value ≈ E[discounted future payoff | state]
            alive = ~done & (exercised_at < len(time_grid))
            if alive.any():
                fv0 = cashflow0[alive]
                dt_j = disc[alive, j]
                val[alive] = np.maximum(np.where(dt_j > 0, fv0 / np.maximum(dt_j, 1e-12), 0.0), 0.0)
            EE[j] = np.mean(np.maximum(val, 0.0))
            ENE[j] = np.mean(np.minimum(val, 0.0))
            PFE[j] = np.percentile(np.maximum(val, 0.0), 95)

        return {
            'price': price,
            'european_ref': european_ref,
            'time_grid': time_grid,
            'EE': EE, 'ENE': ENE, 'PFE': PFE,
            'exercise_fraction': float(np.mean(exercised_at < len(time_grid))),
        }
