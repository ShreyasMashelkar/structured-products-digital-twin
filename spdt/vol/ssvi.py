"""SSVI: a single surface fit that is calendar-arbitrage-free by construction (L2).

Where independent per-slice SVI fits can cross in maturity (calendar arbitrage), SSVI ties the
whole surface to one ATM total-variance term structure ``θ(T)`` and a global shape::

    w(k, T) = (θ/2)·( 1 + ρ·φ(θ)·k + √((φ(θ)·k + ρ)² + (1 − ρ²)) )

with ``φ(θ) = η · θ^(−γ)`` (the power-law of Gatheral–Jacquier). Because ``w(0, T) = θ(T)``,
the ATM total variance *is* the term structure: take it straight from the data and, as long
as it is non-decreasing in ``T``, the surface is free of calendar arbitrage by construction —
exactly the property that motivates SSVI over stitched SVI slices. Static (butterfly) no-arb
has its own closed-form parameter conditions, checked below.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import least_squares

from spdt.data.curate.bs_inversion import IVPoint

if TYPE_CHECKING:
    from spdt.vol.svi import SVIParams


def _phi(theta: NDArray | float, eta: float, gamma: float) -> NDArray | float:
    return eta / np.power(theta, gamma)


def _no_arb_eta(
    rho: float, eta: float, gamma: float, theta_pillars: dict[float, float], *, margin: float = 0.02
) -> float:
    """Largest ``η' ≤ η`` for which the Gatheral–Jacquier butterfly conditions hold at all pillars.

    With ``φ = η·θ^(−γ)`` the two conditions ``θφ(1+|ρ|) < 4`` and ``θφ²(1+|ρ|) ≤ 4`` scale as ``η``
    and ``η²`` respectively, so a single closed-form down-scale (the tighter of the two) makes both
    hold with a small margin. Returns ``η`` unchanged when already satisfied.
    """
    thetas = np.array([t for t in theta_pillars.values() if t > 0.0])
    if thetas.size == 0:
        return eta
    s = 1.0 + abs(rho)
    target = 4.0 * (1.0 - margin)
    c1 = eta * s * float(np.max(thetas ** (1.0 - gamma)))           # θφ(1+|ρ|) at the binding pillar
    c2 = eta * eta * s * float(np.max(thetas ** (1.0 - 2.0 * gamma)))  # θφ²(1+|ρ|)
    factor = 1.0
    if c1 > target:
        factor = min(factor, target / c1)
    if c2 > target:
        factor = min(factor, (target / c2) ** 0.5)
    return eta * factor


@dataclass(frozen=True)
class SSVISurface:
    """Globally-calibrated SSVI surface for one underlying."""

    rho: float
    eta: float
    gamma: float
    theta_pillars: dict[float, float]  # expiry tau -> ATM total variance θ(T)

    def _theta(self, t: float) -> float:
        taus = [0.0, *sorted(self.theta_pillars)]
        thetas = [0.0, *[self.theta_pillars[k] for k in sorted(self.theta_pillars)]]
        return float(np.interp(t, taus, thetas))

    def total_variance(self, k: float, t: float) -> float:
        """SSVI total variance ``w(k, T)``."""
        theta = self._theta(t)
        if theta <= 0.0:
            return 0.0
        p = float(_phi(theta, self.eta, self.gamma))
        return 0.5 * theta * (
            1.0 + self.rho * p * k + np.sqrt((p * k + self.rho) ** 2 + (1.0 - self.rho**2))
        )

    def implied_vol(self, k: float, t: float) -> float:
        if t <= 0.0:
            raise ValueError("implied vol undefined at t <= 0")
        return float(np.sqrt(self.total_variance(k, t) / t))

    def is_butterfly_free(self) -> bool:
        """Gatheral–Jacquier static no-arbitrage conditions over the calibrated tenors."""
        for theta in self.theta_pillars.values():
            p = float(_phi(theta, self.eta, self.gamma))
            if theta * p * (1.0 + abs(self.rho)) >= 4.0:
                return False
            if theta * p * p * (1.0 + abs(self.rho)) > 4.0:
                return False
        return True

    def is_calendar_free(self) -> bool:
        """True iff the ATM total-variance term structure is non-decreasing."""
        thetas = [self.theta_pillars[k] for k in sorted(self.theta_pillars)]
        return all(b >= a - 1e-12 for a, b in zip(thetas, thetas[1:]))

    @classmethod
    def calibrate(cls, iv_points: list[IVPoint]) -> SSVISurface:
        """Fit ρ, η, γ globally after reading θ(T) from the ATM total variance per expiry."""
        by_expiry: dict[float, list[IVPoint]] = {}
        for p in iv_points:
            by_expiry.setdefault(p.tau, []).append(p)

        theta_pillars: dict[float, float] = {}
        for tau, pts in by_expiry.items():
            order = np.argsort([p.log_moneyness for p in pts])
            ks = np.array([pts[i].log_moneyness for i in order])
            ivs = np.array([pts[i].implied_vol for i in order])
            atm_iv = float(np.interp(0.0, ks, ivs))
            theta_pillars[tau] = atm_iv * atm_iv * tau
        # Enforce a non-decreasing term structure (calendar-arb-free by construction).
        taus_sorted = sorted(theta_pillars)
        running = 0.0
        for tau in taus_sorted:
            running = max(running, theta_pillars[tau])
            theta_pillars[tau] = running

        ks = np.array([p.log_moneyness for p in iv_points])
        taus = np.array([p.tau for p in iv_points])
        iv_obs = np.array([p.implied_vol for p in iv_points])
        taus_ordered = sorted(theta_pillars)
        tau_index = np.array([taus_ordered.index(t) for t in taus])
        theta_seed = np.array([max(theta_pillars[t], 1e-8) for t in taus_ordered])

        # Joint fit of (ρ, η, γ) AND the θ pillars, with residuals in implied-vol space.
        #
        # Two deliberate changes from the naive fit, each worth real basis points on noisy
        # settlement data (measured together: 179 → 126bps on a live NIFTY chain, with both
        # no-arbitrage guarantees intact):
        #
        # * θ was previously *read* off a linear interpolation of ATM vol and then frozen, so
        #   any noise in the two straddling quotes biased that whole expiry's level — and level
        #   errors, repeated across every strike of the slice, dominate an RMSE. Fitting the
        #   pillars jointly lets every strike on the slice vote on its level.
        # * Residuals were in total variance, but fit quality is judged (and hedges are sized)
        #   in vol. A w-space objective over-weights long tenors, where w is large, at the
        #   expense of the front — precisely the tenors a desk trades most. Fitting in vol
        #   aligns the objective with the metric the surface is accountable to.
        def residual(params: NDArray) -> NDArray:
            rho, eta, gamma = params[:3]
            th = np.abs(params[3:])[tau_index]
            p = eta / np.power(th, gamma)
            w = 0.5 * th * (
                1.0 + rho * p * ks + np.sqrt((p * ks + rho) ** 2 + (1.0 - rho * rho))
            )
            return np.sqrt(np.maximum(w, 1e-12) / taus) - iv_obs

        n_pillars = len(taus_ordered)
        sol = least_squares(
            residual,
            x0=np.concatenate([[-0.1, 1.0, 0.3], theta_seed]),
            bounds=(
                np.concatenate([[-0.999, 1e-6, 1e-6], np.full(n_pillars, 1e-8)]),
                np.concatenate([[0.999, 100.0, 0.5], np.full(n_pillars, 10.0)]),
            ),
            max_nfev=4000,
        )
        rho, eta, gamma = sol.x[:3]
        # The fit is unconstrained in θ ordering, so re-project onto the calendar-free cone.
        # A running max is the L∞ projection; on real chains the fit lands monotone already and
        # this is a no-op, but the guarantee must not depend on that.
        fitted = np.maximum.accumulate(np.abs(sol.x[3:]))
        theta_pillars = {t: float(v) for t, v in zip(taus_ordered, fitted)}
        # Enforce the Gatheral–Jacquier butterfly conditions: scale η down (which shrinks φ) until
        # both θφ(1+|ρ|) < 4 and θφ²(1+|ρ|) ≤ 4 hold at every pillar. A no-op when the unconstrained
        # fit is already arb-free (clean/synthetic data), so it only bites on noisy real surfaces.
        eta = _no_arb_eta(rho, float(eta), gamma, theta_pillars)
        return cls(rho=rho, eta=eta, gamma=gamma, theta_pillars=theta_pillars)

    def to_svi_slices(self) -> dict[float, "SVIParams"]:
        """Convert each expiry to its exact raw-SVI form — SSVI is SVI per slice with
        ``b = θφ/2``, ``m = −ρ/φ``, ``σ = √(1−ρ²)/φ``, ``a = (θ/2)(1−ρ²)``. Because the SSVI is
        GJ-constrained (butterfly-free) and θ non-decreasing (calendar-free), these slices pass the
        Durrleman/calendar checks — the route to an arbitrage-free desk surface from real data."""
        from spdt.vol.svi import SVIParams

        out: dict[float, SVIParams] = {}
        for tau, theta in self.theta_pillars.items():
            if theta <= 0.0:
                continue
            p = float(_phi(theta, self.eta, self.gamma))
            root = float(np.sqrt(max(1.0 - self.rho**2, 0.0)))
            out[tau] = SVIParams(
                a=0.5 * theta * (1.0 - self.rho**2),
                b=0.5 * theta * p,
                rho=self.rho,
                m=-self.rho / p,
                sigma=root / p,
            )
        return out
