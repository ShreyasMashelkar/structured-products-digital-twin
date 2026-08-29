"""Anchoring the long end of a variance term structure on realised history.

NIFTY quotes a usable options surface to roughly four months. Notes are sold at one to three
years. Between the two there is no market to calibrate against — measured on the live chain,
eight two-sided contracts at 305 days, one at 669, none past 1033 — so anything the desk says
about those tenors is extrapolation. The question is only whether it is disciplined.

Flat extrapolation is not. Holding total variance flat implies ``σ ∝ 1/√τ``, vol *decaying*
with maturity; holding ``σ`` flat says the market's view of a three-year horizon is exactly its
view of a four-month one. Neither is a statement anyone would defend out loud.

What a desk does instead is anchor. Expected variance mean-reverts: whatever the front is
doing, over a long horizon the average variance should approach a level that history can
speak to. This module fits the standard mean-reverting (Heston/Ornstein-Uhlenbeck) expected
variance curve

    v(u) = v∞ + (v₀ − v∞)·e^(−κu)
    w(τ) = ∫₀^τ v(u)du = v∞·τ + (v₀ − v∞)·(1 − e^(−κτ))/κ

with ``v∞`` **fixed** from realised history rather than fitted. That split is the whole point:
the liquid front determines ``v₀`` and ``κ``, and the long end is pinned by eighteen years of
what the index actually did, not by extrapolating a four-month slope.

Two properties come free and both matter. ``w(0) = 0``, and ``w'(τ) = v∞ + (v₀−v∞)e^(−κτ) > 0``
for any positive ``v₀, v∞`` — so the curve is calendar-arbitrage-free by construction, at every
tenor, with no projection step. Asymptotically ``σ(τ) → √v∞``, which is the anchor doing its job.

**On the variance risk premium.** Index implied vol sits systematically above subsequent
realised — sellers of variance earn a premium — so anchoring at realised variance biases the
long end low. That is deliberate here: ``premium`` defaults to 1.0 (pure realised). For a desk
*quoting a coupon*, understating vol understates the coupon it promises, which is the safe
direction to be wrong in. Raise it only with evidence, and never silently.

**What this is not.** It is a model mark, not a quote. Nothing here observes a price at two
years, and no amount of curve-fitting changes that. It should be labelled as a model mark
wherever it reaches a client.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import exp, isfinite, sqrt

import numpy as np
from scipy.optimize import least_squares

_TRADING_DAYS = 252.0


@dataclass(frozen=True)
class AnchoredVarianceCurve:
    """Mean-reverting expected-variance curve: front fitted, long end anchored on history."""

    v0: float  # instantaneous variance (τ → 0)
    kappa: float  # mean-reversion speed, per year
    v_inf: float  # long-run variance (τ → ∞) — the anchor, not fitted

    def __post_init__(self) -> None:
        for name, value in (("v0", self.v0), ("v_inf", self.v_inf)):
            if not (isfinite(value) and value > 0.0):
                raise ValueError(f"{name} must be a positive, finite variance")
        if not (isfinite(self.kappa) and self.kappa > 0.0):
            raise ValueError("kappa must be a positive, finite mean-reversion speed")

    def total_variance(self, tau: float) -> float:
        """``w(τ)``. Zero at the origin and strictly increasing, so calendar-arbitrage-free."""
        if tau <= 0.0:
            return 0.0
        decay = (1.0 - exp(-self.kappa * tau)) / self.kappa
        return self.v_inf * tau + (self.v0 - self.v_inf) * decay

    def atm_vol(self, tau: float) -> float:
        if tau <= 0.0:
            raise ValueError("volatility undefined at tau <= 0")
        return sqrt(self.total_variance(tau) / tau)

    def pillars(self, taus: Sequence[float]) -> tuple[tuple[float, float], ...]:
        """``((tau, atm_vol), ...)`` — the shape :class:`BlackScholesTermVol` consumes."""
        return tuple((float(t), self.atm_vol(float(t))) for t in sorted(taus) if t > 0.0)


def realised_variance(
    closes: Sequence[float], *, periods_per_year: float = _TRADING_DAYS
) -> float:
    """Annualised variance of log returns on a close series.

    Deliberately takes a bare sequence rather than fetching anything: the anchor is the one
    number in this module that must come from the *same index the notes reference*, and
    leaving sourcing to the caller keeps that an explicit decision rather than a default
    buried three layers down.
    """
    prices = np.asarray(closes, dtype=float)
    if prices.size < 3:
        raise ValueError("realised variance needs at least three closes")
    if not np.all(prices > 0.0):
        raise ValueError("close series must be strictly positive")
    returns = np.diff(np.log(prices))
    return float(np.var(returns, ddof=1) * periods_per_year)


def fit_anchored_curve(
    observed: Sequence[tuple[float, float]],
    v_inf: float,
    *,
    premium: float = 1.0,
    kappa_bounds: tuple[float, float] = (0.5, 6.0),
) -> AnchoredVarianceCurve:
    """Fit ``v₀`` and ``κ`` to the observed ``(tau, atm_vol)`` pillars, holding ``v∞`` fixed.

    ``kappa_bounds`` exists because a four-month front cannot identify a mean-reversion speed:
    over that window every plausible ``κ`` fits about equally well, and an unbounded solver
    will happily return one that makes the long end say whatever the last noisy pillar implied.
    Bounding it to a plausible range is an admission that the data does not determine it, which
    is more honest than a number carrying three significant figures of false precision.

    Residuals are in **vol**, not variance, matching the surface calibration: a least-squares
    fit in variance weights the long pillars far more heavily than a desk would.
    """
    pillars = sorted((float(t), float(v)) for t, v in observed if t > 0.0 and v > 0.0)
    if not pillars:
        raise ValueError("anchoring needs at least one observed pillar")
    if not (isfinite(v_inf) and v_inf > 0.0):
        raise ValueError("v_inf must be a positive, finite variance")
    if premium <= 0.0:
        raise ValueError("premium must be positive")
    anchor = v_inf * premium

    taus = np.array([t for t, _ in pillars])
    vols = np.array([v for _, v in pillars])

    def residual(params: np.ndarray) -> np.ndarray:
        curve = AnchoredVarianceCurve(v0=float(params[0]), kappa=float(params[1]),
                                      v_inf=anchor)
        fitted = np.array([curve.atm_vol(float(t)) for t in taus])
        return fitted - vols

    v0_guess = float(vols[0] ** 2)
    kappa_guess = float(np.clip(1.5, *kappa_bounds))
    solution = least_squares(
        residual,
        x0=np.array([v0_guess, kappa_guess]),
        bounds=(np.array([1e-8, kappa_bounds[0]]), np.array([4.0, kappa_bounds[1]])),
        max_nfev=2000,
    )
    return AnchoredVarianceCurve(
        v0=float(solution.x[0]), kappa=float(solution.x[1]), v_inf=anchor
    )


def extend_pillars(
    observed: Sequence[tuple[float, float]],
    curve: AnchoredVarianceCurve,
    horizons: Sequence[float],
) -> tuple[tuple[float, float], ...]:
    """Observed pillars, verbatim, plus anchored pillars strictly beyond the last of them.

    The observed points are never overwritten by the fit. Where the market has spoken it wins,
    even if the curve would smooth it — the anchor exists for the tenors that have no quote,
    and letting it revise the ones that do would be trading real information for tidiness.
    """
    kept = sorted((float(t), float(v)) for t, v in observed if t > 0.0 and v > 0.0)
    if not kept:
        raise ValueError("extending needs at least one observed pillar")
    last_tau = kept[-1][0]
    extra = [
        (float(t), curve.atm_vol(float(t)))
        for t in sorted(horizons)
        if t > last_tau * (1.0 + 1e-9)
    ]
    return tuple(kept + extra)
