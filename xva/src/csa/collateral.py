"""
CSA (Credit Support Annex) Collateral Engine.

Models the impact of collateral agreements on counterparty exposure.
Supports multiple CSA configurations:
- Uncollateralised
- Partially collateralised (with threshold and MTA)
- Fully collateralised (ISDA standard)
- CCP-cleared (with initial margin)

Key parameter: MPOR (Margin Period of Risk) — the closeout period
during which exposure persists even with perfect collateralisation.
"""

import warnings
import numpy as np
from typing import Dict, Optional


class CSAEngine:
    """
    CSA Collateral Engine for exposure modelling.

    Applies collateral rules to simulated MTM paths to produce
    collateralised exposure profiles.

    Attributes:
        threshold: Exposure above which collateral must be posted (₹ Cr).
        mta: Minimum Transfer Amount (₹ Cr).
        mpor_days: Margin Period of Risk in business days.
        margin_frequency: 'daily', 'weekly', or 'none'.
        independent_amount: Upfront collateral regardless of MTM (₹ Cr).
    """

    def __init__(self, threshold: float = 0.0, mta: float = 0.0,
                 mpor_days: int = 10, margin_frequency: str = 'daily',
                 independent_amount: float = 0.0):
        """
        Initialise the CSA engine.

        Args:
            threshold: Exposure threshold in ₹ Crores.
            mta: Minimum Transfer Amount in ₹ Crores.
            mpor_days: Margin Period of Risk in business days.
            margin_frequency: 'daily', 'weekly', or 'none'.
            independent_amount: Independent Amount (IA) in ₹ Crores.
        """
        self.threshold = threshold
        self.mta = mta
        self.mpor_days = mpor_days
        self.margin_frequency = margin_frequency
        self.independent_amount = independent_amount

    def _lagged_mtm(self, mtm_paths: np.ndarray,
                    time_grid: np.ndarray) -> np.ndarray:
        """
        Reconstruct the last-margined MTM seen at each date — i.e. the MTM as
        of ``t - MPoR`` — resolution-independently.

        The collateral held at the close-out of a defaulting counterparty
        reflects the *last successful margin call*, which under the Margin
        Period of Risk (MPoR) δ happened δ ≈ ``mpor_days`` business days ago.
        The exposure that matters is therefore the gap ``MTM(t) - MTM(t-δ)``
        accumulated over that δ window.

        Two failure modes of the naive "lag by N grid steps" approach are
        fixed here:

        1. **Quantisation / clamp.** ``round(δ/dt)`` collapses to 0 and is
           clamped to a 1-step minimum whenever the grid is coarser than δ
           (the usual case: monthly grid vs a 10-business-day MPoR). The
           close-out window then equals the *plotting resolution*, not the
           CSA. Here δ is honoured exactly by interpolating MTM at ``t-δ``.

        2. **Lost diffusion.** Linear interpolation between coarse nodes
           under-samples the variance of the δ-gap by √(δ/dt_local), which
           *understates* collateralised exposure (the dangerous direction).
           When the grid cannot resolve δ, the interpolated gap is rescaled
           by √(dt_local/δ) so its dispersion matches a genuine δ-horizon
           move. The correction is 1 (a no-op) as soon as the grid resolves
           δ — e.g. when paths are simulated on an MPoR-aware grid — so the
           exact-grid result is recovered.

        Returns the per-path MTM-as-of-(t-δ), shape (n_paths, n_steps+1).
        """
        n_paths, n_time = mtm_paths.shape
        mpor_years = max(self.mpor_days, 0) / 252.0

        if mpor_years <= 0.0 or n_time < 2:
            # No close-out lag: collateral can track MTM instantaneously.
            return mtm_paths.copy()

        query = time_grid - mpor_years            # the t-δ lookback times
        # Bracketing nodes for each query time (vectorised over the grid).
        hi = np.searchsorted(time_grid, query, side='right')
        hi = np.clip(hi, 1, n_time - 1)
        lo = hi - 1
        span = time_grid[hi] - time_grid[lo]
        span = np.where(span > 1e-12, span, 1e-12)
        frac = np.clip((query - time_grid[lo]) / span, 0.0, 1.0)

        # Linear (bridge-mean) interpolation of MTM at t-δ.
        lagged = mtm_paths[:, lo] + frac * (mtm_paths[:, hi] - mtm_paths[:, lo])

        # Diffusion correction: inflate the interpolated δ-gap so its variance
        # matches a true δ-horizon move when the local grid is coarser than δ.
        local_dt = time_grid[hi] - time_grid[lo]
        scale = np.sqrt(np.maximum(local_dt / mpor_years, 1.0))   # ≥ 1
        # Lookback within the bracketing step (the typical coarse-grid case)
        # gets the correction; multi-step lookbacks already carry real
        # diffusion, so leave them untouched.
        within_step = lo == (np.arange(n_time) - 1)
        scale = np.where(within_step, scale, 1.0)

        gap = mtm_paths - lagged                  # MTM(t) - MTM(t-δ), per path
        lagged_corr = mtm_paths - gap * scale     # = lagged when scale == 1

        # Before the first close-out window there is no prior margin call.
        lagged_corr[:, query <= time_grid[0]] = mtm_paths[:, query <= time_grid[0]]

        if np.any(scale > 1.0 + 1e-9):
            warnings.warn(
                f"CSA grid (Δt≈{float(np.median(np.diff(time_grid))):.4f}y) is "
                f"coarser than the {self.mpor_days}-day MPoR "
                f"(δ≈{mpor_years:.4f}y); the close-out gap is variance-corrected "
                f"but simulate on an MPoR-aware grid for an exact close-out.",
                stacklevel=2,
            )
        return lagged_corr

    def compute_collateral(self, mtm_paths: np.ndarray,
                           time_grid: np.ndarray) -> np.ndarray:
        """
        Compute the collateral held at each time step.

        Variation margin tracks the MTM as of the last successful margin call
        (``t - MPoR``, see :meth:`_lagged_mtm`), subject to the posting
        threshold and minimum transfer amount; the independent amount is held
        on top throughout.

        Collateral(t) = max(MTM(t-δ) - Threshold, 0)   (+ MTA stickiness, + IA)

        Args:
            mtm_paths: MTM paths of shape (n_paths, n_steps+1).
            time_grid: Time grid of shape (n_steps+1,).

        Returns:
            Collateral paths of shape (n_paths, n_steps+1).
        """
        n_paths, n_steps_plus_1 = mtm_paths.shape

        if self.margin_frequency == 'none' or np.isinf(self.threshold):
            return np.zeros_like(mtm_paths)

        dt = time_grid[1] - time_grid[0] if len(time_grid) > 1 else 1 / 12

        # MTM as of the last margin call (t - MPoR), resolution-independent.
        mtm_for_call = self._lagged_mtm(mtm_paths, time_grid)

        # Variation margin only (independent amount added at the end so it is
        # not re-accumulated each step).
        vm = np.zeros_like(mtm_paths)

        # Margin frequency in steps
        if self.margin_frequency == 'daily':
            margin_every = 1
        elif self.margin_frequency == 'weekly':
            margin_every = max(1, int(round((5 / 252) / dt)))
        else:
            margin_every = n_steps_plus_1  # Never call

        for i in range(1, n_steps_plus_1):
            if i % margin_every == 0:
                # Desired VM against the last-margined MTM.
                desired = np.maximum(mtm_for_call[:, i] - self.threshold, 0.0)

                # Apply MTA: only transfer if the change exceeds the MTA.
                change = desired - vm[:, i - 1]
                transfer = np.where(np.abs(change) >= self.mta, change, 0.0)
                vm[:, i] = vm[:, i - 1] + transfer
            else:
                vm[:, i] = vm[:, i - 1]

        return vm + self.independent_amount

    def compute_collateralised_exposure(self, mtm_paths: np.ndarray,
                                         time_grid: np.ndarray) -> np.ndarray:
        """
        Compute residual (collateralised) exposure.

        Residual Exposure = max(MTM(t) - Collateral(t), 0)

        For uncollateralised counterparties:
        Exposure = max(MTM(t), 0)

        Args:
            mtm_paths: MTM paths of shape (n_paths, n_steps+1).
            time_grid: Time grid of shape (n_steps+1,).

        Returns:
            Collateralised exposure paths of shape (n_paths, n_steps+1).
        """
        if self.margin_frequency == 'none' or np.isinf(self.threshold):
            # Uncollateralised: exposure = max(MTM, 0)
            return np.maximum(mtm_paths, 0.0)

        collateral = self.compute_collateral(mtm_paths, time_grid)
        residual = mtm_paths - collateral
        return np.maximum(residual, 0.0)

    def compute_exposure_metrics(self, mtm_paths: np.ndarray,
                                  time_grid: np.ndarray,
                                  percentile: float = 95.0) -> Dict[str, np.ndarray]:
        """
        Compute exposure metrics under this CSA's collateral rules.

        EPE: Time-weighted average of EE over the first year (Basel III 1-year cap).

        Args:
            mtm_paths: Raw MTM paths.
            time_grid: Time grid.
            percentile: PFE percentile.

        Returns:
            Dictionary with EE, PFE, collateral_held.
        """
        coll_exposure = self.compute_collateralised_exposure(
            mtm_paths, time_grid
        )

        ee = np.mean(coll_exposure, axis=0)
        pfe = np.percentile(coll_exposure, percentile, axis=0)
        collateral = self.compute_collateral(mtm_paths, time_grid)
        avg_collateral = np.mean(collateral, axis=0)

        # EPE — Basel III: time-weighted average of EE over first year only
        dt_array = np.diff(time_grid)
        reg_horizon = min(time_grid[-1], 1.0)
        mask = time_grid[1:] <= reg_horizon + 1e-9
        if mask.any() and reg_horizon > 0:
            epe = np.sum(ee[1:][mask] * dt_array[mask]) / reg_horizon
        else:
            epe = float(ee[1]) if len(ee) > 1 else 0.0

        # EEPE: Effective EPE — time-weighted average of running-max EE over the first year
        effective_ee = np.maximum.accumulate(ee)
        if mask.any() and reg_horizon > 0:
            eepe = np.sum(effective_ee[1:][mask] * dt_array[mask]) / reg_horizon
        else:
            eepe = float(effective_ee[1]) if len(effective_ee) > 1 else 0.0

        return {
            'time_grid': time_grid,
            'EE': ee,
            'PFE': pfe,
            'EPE': epe,
            'EEPE': eepe,
            'avg_collateral': avg_collateral,
        }


def compare_csa_scenarios(mtm_paths: np.ndarray,
                          time_grid: np.ndarray,
                          scenarios: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Compare exposure profiles across multiple CSA configurations.

    Args:
        mtm_paths: Raw MTM paths from Monte Carlo.
        time_grid: Time grid.
        scenarios: Dictionary of scenario_name → CSA parameter dict.

    Returns:
        Dictionary mapping scenario names to exposure metrics.
    """
    results = {}

    for name, params in scenarios.items():
        threshold = params.get('threshold_cr', float('inf'))
        mta = params.get('mta_cr', 0.0)
        mpor = params.get('mpor_days', 10)
        freq = params.get('margin_frequency', 'daily')
        ia = params.get('independent_amount_cr', 0.0)

        engine = CSAEngine(
            threshold=threshold, mta=mta,
            mpor_days=mpor, margin_frequency=freq,
            independent_amount=ia
        )

        metrics = engine.compute_exposure_metrics(mtm_paths, time_grid)
        results[name] = metrics

    return results

def is_ccp_cleared(csa_type: str) -> bool:
    """Returns True if the CSA type represents a CCP-cleared trade."""
    return str(csa_type).strip().upper() in ('CCP-CLEARED', 'CCP_CLEARED', 'CCP')

def get_ccp_mpor() -> int:
    """Standard MPOR for CCP-cleared trades: 5 business days (Basel III)."""
    return 5

