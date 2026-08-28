"""Calibration fit quality: how well the fitted surface reproduces the quotes it was fit to (L2).

:mod:`spdt.vol.arbitrage` answers "is the fitted surface *admissible*" — no negative density,
no crossing slices. It does **not** answer "is the fitted surface *right*": a perfectly
arbitrage-free SVI slice can miss every quote by three vol points and still report clean.
Those are independent failure modes and a model-validation pack needs both.

Errors are reported in **implied-vol basis points**, not in total variance, for two reasons:
the fit itself minimises total-variance residuals (so quoting that back is marking your own
homework in the units you optimised), and a desk's tolerance is naturally expressed in vol
points. The conversion is exact rather than linearised::

    σ_fit = √(w_fit / τ)      error_bps = 1e4 · (σ_fit − σ_mkt)

Errors are also broken out **by moneyness bucket**, because that is where the honest weakness
of a settlement-price surface lives: ATM strikes trade and fit well, wings are stale prints
that the aggregate RMSE hides by averaging them against a dense, well-behaved core.
"""

from __future__ import annotations

from collections.abc import Mapping

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

import numpy as np

from spdt.vol.svi import SVIParams

if TYPE_CHECKING:
    from spdt.data.curate.bs_inversion import IVPoint

# Log-moneyness bucket edges. The wings start at |k| = 0.10 because that is roughly where
# NIFTY monthly option open interest thins out; beyond 0.25 settlement prints are frequently
# stale and are the main source of surface noise.
_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("deep_put_wing", -np.inf, -0.25),
    ("put_wing", -0.25, -0.10),
    ("atm", -0.10, 0.10),
    ("call_wing", 0.10, 0.25),
    ("deep_call_wing", 0.25, np.inf),
)


@dataclass(frozen=True)
class BucketError:
    """Fit error over one log-moneyness bucket, in implied-vol basis points."""

    bucket: str
    n_points: int
    rmse_bps: float
    max_abs_bps: float
    mean_bias_bps: float  # signed: positive ⇒ the fit sits above the market


@dataclass(frozen=True)
class SliceFit:
    """Fit quality for a single expiry slice."""

    expiry: date
    tau: float
    n_points: int
    rmse_bps: float
    max_abs_bps: float
    mean_bias_bps: float
    r_squared: float  # in total variance, the space actually fitted


@dataclass(frozen=True)
class FitReport:
    """Surface-level calibration quality — the companion to ``ArbReport``.

    ``ArbReport`` says the surface is admissible; this says it is faithful. Both are needed
    before a price computed on the surface means anything.
    """

    n_points: int
    rmse_bps: float
    max_abs_bps: float
    slices: tuple[SliceFit, ...]
    buckets: tuple[BucketError, ...]

    def is_within(self, tolerance_bps: float) -> bool:
        """Whether the whole-surface RMSE clears a desk tolerance (e.g. 50bps of vol)."""
        return self.rmse_bps <= tolerance_bps

    @property
    def worst_slice(self) -> SliceFit | None:
        """The expiry fitting worst by RMSE — usually the shortest or the least liquid."""
        return max(self.slices, key=lambda s: s.rmse_bps, default=None)

    def unreliable_slices(self, tolerance_bps: float = 200.0) -> tuple[SliceFit, ...]:
        """Expiries whose fit is too poor to price against.

        Real EOD surfaces are **not** uniformly good: on NIFTY the liquid monthlies fit inside
        ~100bps while a handful of illiquid expiries blow out past 1000bps on a few stale
        prints. A single whole-surface RMSE averages those together and reads as mediocre
        everywhere, which is the wrong conclusion — the surface is trustworthy in most tenors
        and untrustworthy in specific, identifiable ones. Callers pricing a note whose
        observation dates land on a flagged expiry should treat the price as unsupported by
        the data rather than merely imprecise.
        """
        return tuple(s for s in self.slices if not (s.rmse_bps <= tolerance_bps))

    def reliable_fraction(self, tolerance_bps: float = 200.0) -> float:
        """Share of calibrated expiries fitting inside ``tolerance_bps`` — the headline number."""
        if not self.slices:
            return float("nan")
        return 1.0 - len(self.unreliable_slices(tolerance_bps)) / len(self.slices)


def _error_stats(errors_bps: np.ndarray) -> tuple[float, float, float]:
    """``(rmse, max_abs, mean_bias)`` in bps for a vector of signed errors."""
    if errors_bps.size == 0:
        return (float("nan"),) * 3
    return (
        float(np.sqrt(np.mean(errors_bps**2))),
        float(np.max(np.abs(errors_bps))),
        float(np.mean(errors_bps)),
    )


def slice_errors_bps(
    params: SVIParams, k: np.ndarray, iv_market: np.ndarray, tau: float
) -> np.ndarray:
    """Signed fitted-minus-market implied-vol errors in bps for one slice.

    Total variance is floored at zero before the square root: an unconstrained SVI fit can go
    slightly negative in a sparse wing, and that is itself a fit failure we want to surface as
    a large error rather than crash on.
    """
    w_fit = np.asarray(params.total_variance(k), dtype=float)
    iv_fit = np.sqrt(np.maximum(w_fit, 0.0) / tau)
    return 1e4 * (iv_fit - np.asarray(iv_market, dtype=float))


def assess_fit(
    iv_points: list[IVPoint],
    slices: Mapping[date, SVIParams],
    taus: Mapping[date, float],
) -> FitReport:
    """Measure how closely the calibrated ``slices`` reproduce the ``iv_points`` fitted to them.

    Points whose expiry did not calibrate (e.g. dropped by SSVI for non-positive ATM variance)
    are excluded — they were never claimed to be fit, so scoring them would be misleading.
    """
    by_expiry: dict[date, list[IVPoint]] = {}
    for p in iv_points:
        if p.expiry in slices:
            by_expiry.setdefault(p.expiry, []).append(p)

    slice_fits: list[SliceFit] = []
    all_errors: list[np.ndarray] = []
    all_k: list[np.ndarray] = []

    for expiry in sorted(by_expiry, key=lambda e: taus[e]):
        pts = by_expiry[expiry]
        tau = taus[expiry]
        k = np.array([p.log_moneyness for p in pts], dtype=float)
        iv = np.array([p.implied_vol for p in pts], dtype=float)
        errors = slice_errors_bps(slices[expiry], k, iv, tau)
        rmse, max_abs, bias = _error_stats(errors)

        # R² in total variance — the space least_squares actually minimised in.
        w_mkt = iv * iv * tau
        w_fit = np.asarray(slices[expiry].total_variance(k), dtype=float)
        ss_res = float(np.sum((w_mkt - w_fit) ** 2))
        ss_tot = float(np.sum((w_mkt - np.mean(w_mkt)) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-18 else float("nan")

        slice_fits.append(
            SliceFit(expiry, tau, len(pts), rmse, max_abs, bias, r2)
        )
        all_errors.append(errors)
        all_k.append(k)

    if not all_errors:
        return FitReport(0, float("nan"), float("nan"), (), ())

    errors = np.concatenate(all_errors)
    ks = np.concatenate(all_k)
    rmse, max_abs, _ = _error_stats(errors)

    buckets: list[BucketError] = []
    for name, lo, hi in _BUCKETS:
        mask = (ks >= lo) & (ks < hi)
        if not mask.any():
            continue
        b_rmse, b_max, b_bias = _error_stats(errors[mask])
        buckets.append(BucketError(name, int(mask.sum()), b_rmse, b_max, b_bias))

    return FitReport(
        n_points=int(errors.size),
        rmse_bps=rmse,
        max_abs_bps=max_abs,
        slices=tuple(slice_fits),
        buckets=tuple(buckets),
    )
