"""
IMM-style exposure backtesting (regulatory model validation).

To keep IMM (Internal Model Method) approval for counterparty credit risk, a
bank must backtest its simulated exposure distribution against realised
outcomes: how often does the realised portfolio value exceed the model's
predicted quantile (e.g. PFE 95%)? Too many breaches ⇒ the model under-states
risk ⇒ the regulator moves it to the amber/red traffic-light zone and applies
a capital multiplier.

This module implements:
  - quantile-breach counting over a backtest window
  - the Kupiec proportion-of-failures (POF) likelihood-ratio test
  - the Basel traffic-light zoning (green / amber / red)
  - a portfolio-level backtest harness that compares a model's predicted
    exposure quantile path against realised mark-to-market outcomes.

Pure NumPy/SciPy. Reference: Basel Committee, "Sound practices for
backtesting counterparty credit risk models" (2010, free).
"""

import numpy as np
from scipy.stats import chi2, binom
from typing import Dict, Optional


def kupiec_pof(n_obs: int, n_breaches: int, q: float) -> Dict:
    """
    Kupiec Proportion-of-Failures test.

    H0: the true breach probability equals (1 - q). Returns the LR statistic,
    p-value (χ²₁), and whether H0 is rejected at 95%.
    """
    p = 1.0 - q                     # expected breach probability
    x = n_breaches
    n = n_obs
    if n == 0:
        return {'LR': 0.0, 'p_value': 1.0, 'reject_H0': False,
                'expected_breaches': 0.0, 'observed_breaches': 0}
    pi_hat = x / n
    # likelihood ratio (guard log(0))
    eps = 1e-12
    ll_null = (n - x) * np.log(1 - p + eps) + x * np.log(p + eps)
    ll_alt = (n - x) * np.log(1 - pi_hat + eps) + x * np.log(pi_hat + eps)
    lr = -2.0 * (ll_null - ll_alt)
    p_value = 1.0 - chi2.cdf(lr, df=1)
    return {'LR': float(lr), 'p_value': float(p_value),
            'reject_H0': bool(p_value < 0.05),
            'expected_breaches': float(n * p), 'observed_breaches': int(x)}


def traffic_light(n_obs: int, n_breaches: int, q: float) -> Dict:
    """
    Basel traffic-light zoning from the cumulative binomial of the breach count.

    Green : cumulative prob < 95%
    Amber : 95% ≤ cumulative prob < 99.99%
    Red   : cumulative prob ≥ 99.99%
    """
    p = 1.0 - q
    cum = binom.cdf(n_breaches - 1, n_obs, p) if n_breaches > 0 else 0.0
    if cum < 0.95:
        zone, mult = 'GREEN', 1.00
    elif cum < 0.9999:
        zone, mult = 'AMBER', 1.0 + 0.10 * (n_breaches - max(1, int(round(n_obs * p))))
        mult = float(np.clip(mult, 1.0, 1.33))
    else:
        zone, mult = 'RED', 1.33
    return {'zone': zone, 'capital_multiplier': float(mult),
            'cumulative_prob': float(cum), 'n_breaches': int(n_breaches),
            'n_obs': int(n_obs)}


class ExposureBacktester:
    """Backtests a simulated exposure quantile path against realised outcomes."""

    def __init__(self, quantile: float = 0.95):
        self.q = quantile

    def backtest(self, predicted_quantile: np.ndarray,
                 realised: np.ndarray) -> Dict:
        """
        Backtest a predicted exposure-quantile path against realised values.

        Args:
            predicted_quantile: (n_obs,) model PFE_q at each observation date.
            realised:           (n_obs,) realised positive exposure / MtM.

        Returns:
            Dict with breach count, breach rate, Kupiec test, traffic light.
        """
        predicted_quantile = np.asarray(predicted_quantile, float)
        realised = np.asarray(realised, float)
        n = len(realised)
        breaches = realised > predicted_quantile
        n_breaches = int(breaches.sum())

        kup = kupiec_pof(n, n_breaches, self.q)
        tl = traffic_light(n, n_breaches, self.q)
        return {
            'quantile': self.q,
            'n_observations': n,
            'n_breaches': n_breaches,
            'breach_rate': n_breaches / n if n else 0.0,
            'expected_breach_rate': 1 - self.q,
            'breach_dates': np.where(breaches)[0],
            'kupiec': kup,
            'traffic_light': tl,
        }

    def backtest_from_simulation(self, mtm_paths: np.ndarray,
                                 time_grid: np.ndarray,
                                 realised_factor: float = 1.0,
                                 seed: int = 7) -> Dict:
        """
        Self-contained demo: treat one simulated path family as the model's
        predicted exposure quantile, draw an independent 'realised' path
        family (optionally stressed by `realised_factor`), and backtest.

        Args:
            mtm_paths:       (n_paths, n_steps+1) model MtM paths.
            time_grid:       time grid.
            realised_factor: scale on realised volatility (>1 stresses the
                             realised world so the model under-predicts).
            seed:            RNG seed for the realised draws.

        Returns:
            Backtest dict from `backtest`, plus the predicted PFE path.
        """
        pos = np.maximum(mtm_paths, 0.0)
        pfe_q = np.percentile(pos, self.q * 100, axis=0)

        # realised: resample exposures with optional stress
        rng = np.random.default_rng(seed)
        n_paths = mtm_paths.shape[0]
        idx = rng.integers(0, n_paths, size=len(time_grid))
        realised = np.array([max(mtm_paths[idx[j], j] * realised_factor, 0.0)
                             for j in range(len(time_grid))])
        res = self.backtest(pfe_q, realised)
        res['predicted_pfe'] = pfe_q
        res['realised'] = realised
        res['time_grid'] = time_grid
        return res
