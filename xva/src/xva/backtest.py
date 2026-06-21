"""
XVA Backtesting Engine.
Compares realized pathwise MTM against predicted PFE bounds.
Implements Kupiec (1995) Proportion of Failures (POF) test.
"""
import numpy as np
from scipy.stats import chi2


class XVABacktester:
    """
    Backtests PFE model by counting how often realized MTM exceeds predicted PFE.
    Uses Kupiec (1995) POF test to determine if the exception rate is statistically
    consistent with the model's stated confidence level.

    Kupiec POF test:
        H0: p_hat = p_expected  (model is correctly calibrated)
        LR = -2 * ln[ p_exp^x * (1-p_exp)^(n-x) / p_hat^x * (1-p_hat)^(n-x) ]
        LR ~ chi2(df=1) under H0
    """

    def __init__(self, confidence_interval: float = 0.95):
        self.ci = confidence_interval
        self.expected_exception_rate = 1.0 - confidence_interval

    def backtest_exceptions(self,
                            realized_mtm_paths: np.ndarray,
                            predicted_pfe: np.ndarray) -> dict:
        """
        Count PFE exceptions and run Kupiec POF test.

        Args:
            realized_mtm_paths: Shape (n_paths, n_steps) — out-of-sample MTM paths
            predicted_pfe:      Shape (n_steps,) — in-sample PFE at CI level

        Returns:
            Dict with exception counts, Kupiec LR statistic, and p-value.
        """
        n_paths, n_steps = realized_mtm_paths.shape

        # Count exceptions: times realized MTM > predicted PFE bound
        # predicted_pfe is 1D (n_steps,) — broadcast against (n_paths, n_steps)
        exceptions_per_step = np.sum(realized_mtm_paths > predicted_pfe[None, :], axis=0)
        exception_rate_per_step = exceptions_per_step / n_paths

        # Aggregate across all path-steps for overall Kupiec test
        total_observations = n_paths * n_steps
        total_exceptions   = int(np.sum(exceptions_per_step))
        p_hat = total_exceptions / total_observations if total_observations > 0 else 0.0
        p_exp = self.expected_exception_rate

        # Kupiec (1995) POF likelihood ratio statistic
        # Guard against p_hat = 0 or 1 to avoid log(0)
        eps = 1e-10
        p_hat_safe = np.clip(p_hat, eps, 1 - eps)
        p_exp_safe = np.clip(p_exp, eps, 1 - eps)

        n  = total_observations
        x  = total_exceptions
        lr = -2.0 * (
            x * np.log(p_exp_safe / p_hat_safe)
            + (n - x) * np.log((1 - p_exp_safe) / (1 - p_hat_safe))
        )

        # p-value: probability of observing LR this extreme if model is correct
        kupiec_pvalue = float(1.0 - chi2.cdf(lr, df=1))

        # Breach flag: reject H0 at 95% (p < 0.05 means model is mis-calibrated)
        # A zero-exception result must never be a breach (model is conservative).
        is_breach = (kupiec_pvalue < 0.05) and (total_exceptions > 0)

        return {
            'total_observations':      total_observations,
            'total_exceptions':        total_exceptions,
            'observed_exception_rate': round(p_hat, 4),
            'expected_exception_rate': round(p_exp, 4),
            'max_exception_rate':      round(float(np.max(exception_rate_per_step)), 4),
            'kupiec_lr_statistic':     round(float(lr), 4),
            'kupiec_pvalue':           round(kupiec_pvalue, 4),
            'is_breach':               is_breach,
            'verdict': ('FAIL — model over-conservative' if p_hat < p_exp * 0.5
                        else 'FAIL — model under-estimates risk' if is_breach
                        else 'PASS'),
        }
