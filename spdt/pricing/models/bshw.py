"""Black-Scholes equity under Hull-White stochastic rates — for the *note*, not just its XVA (L4).

The review that shaped this project's validation said the rate curve was built once and held
fixed through the simulation. That was fixed for the exposure engine (HW2F in the hybrid XVA),
but the note itself was still priced under a constant ``r`` — so a three-year autocallable's
coupon carried no rate-vol premium and its rho was a bump of a flat number. This model closes
that half:

    rate factor  x : dx = −a·x dt + σ_r dW_r          (Hull-White 1F, exact OU steps)
    short rate   r : r(t) = x(t) + f(0, t)            (fitted to the initial curve)
    equity       S : dS = (r(t) − q)·S dt + σ·S dW_S   (lognormal, stochastic drift)
    corr(dW_r, dW_S) = ρ

Under stochastic rates the risk-neutral deflator is pathwise — ``D(t) = exp(−∫r ds)`` along
*this* path — so a deterministic discount curve cannot price the product; the deflator must be
carried per path and applied to each cashflow on the path that generated it. That is why this
module exposes :func:`price_mc_hw` rather than plugging into the engine's ``PathModel``
protocol, whose ``discount(t)`` is a scalar by design.

One factor, not two, deliberately: the note's payoff depends on the *level* of rates over its
life (through the drift and the deflator), not on the curve's shape — no cashflow here pays a
tenor spread. HW2F earns its keep in the exposure engine, where curve-shape risk reaches EE;
here it would double the state for no additional priced risk.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp

import numpy as np
from numpy.typing import NDArray

from spdt.products.graph import PriceResult, Product, PathSet


@dataclass(frozen=True)
class BlackScholesHW:
    """Joint equity + short-rate dynamics with a flat initial curve ``f(0,t) = r0``.

    ``sigma_r = 0`` collapses exactly to Black-Scholes under ``r0`` — the regression anchor
    every test of this model leans on.
    """

    spot: float
    r0: float
    q: float
    sigma: float
    a: float = 0.10  # rate mean reversion
    sigma_r: float = 0.010  # rate vol (absolute, e.g. 0.010 = 100bp)
    rho: float = -0.15  # equity-rate correlation; equities-up/rates-down is the usual sign
    # Optional initial zero curve as ((tenor_years, cc_zero_rate), ...) — a tuple of pairs so
    # the dataclass stays frozen/hashable. When set, f(0,t) is read off this curve instead of
    # the flat r0, so the funding leg of a multi-year note discounts on the curve's actual
    # slope (~60bp between 1y and 5y on the current Treasury curve) rather than one level.
    zero_curve: tuple[tuple[float, float], ...] | None = None

    def _zero(self, t: float) -> float:
        """Continuously-compounded zero rate at ``t`` — flat r0 when no curve is supplied."""
        if not self.zero_curve:
            return self.r0
        xs = [p[0] for p in self.zero_curve]
        ys = [p[1] for p in self.zero_curve]
        return float(np.interp(t, xs, ys))

    def _forward(self, times: NDArray[np.float64]) -> NDArray[np.float64]:
        """Instantaneous forward f(0,t) on the grid: d/dt[z(t)·t], piecewise on the pillars.

        With linear interpolation in the zero rate, z(t)·t is piecewise quadratic and its
        derivative piecewise linear — smooth enough that the trapezoidal r-integration in
        ``simulate_joint`` reprices the curve's bonds to a few 1e-4, which the bond test pins.
        """
        if not self.zero_curve:
            return np.full(times.shape, self.r0)
        # Floor t BEFORE building both sides of the difference: flooring only the lower side
        # makes the two coincide at t = 0, which silently returns f(0) = 0 and shorts the
        # r-integral by f(0)·dt/2 — a ~25bp df error the bond-repricing test caught.
        eps = 1e-5
        t_eff = np.maximum(np.asarray(times, dtype=float), eps)
        zt = np.array([self._zero(t) * t for t in t_eff])
        zt_up = np.array([self._zero(t + eps) * (t + eps) for t in t_eff])
        return (zt_up - zt) / eps

    def simulate_joint(
        self, times: NDArray[np.float64], normals: NDArray[np.float64], *, seed: int = 0
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Spots and pathwise deflators on ``times`` (``times[0] == 0``).

        ``normals`` drives the *equity* (so common-random-number bumps against the plain BS
        model stay comparable); the rate factor draws its own stream from ``seed``, correlated
        to the equity draw with ``rho``. Returns ``(spots, deflators)``, both
        ``(n_paths, len(times))``, with ``deflators[:, 0] = 1``.

        The convexity term that refits the initial curve under HW — ``φ(t) = f(0,t) +
        σ_r²·B(t)²/2`` with ``B(t) = (1−e^{−at})/a`` — is included, so a zero-coupon bond
        priced off these deflators reproduces ``exp(−r0·t)`` in expectation; without it the
        model would misprice the funding leg by the rate-vol convexity.
        """
        n_paths, n_steps = normals.shape
        dt = np.diff(times)

        rng = np.random.default_rng(seed + 7_919)  # offset: never the equity stream itself
        z_ind = rng.standard_normal((n_paths, n_steps))
        z_r = self.rho * normals + np.sqrt(max(1.0 - self.rho**2, 0.0)) * z_ind

        x = np.zeros((n_paths, n_steps + 1))
        for i, h in enumerate(dt):
            decay = exp(-self.a * h)
            std = self.sigma_r * np.sqrt((1.0 - exp(-2.0 * self.a * h)) / (2.0 * self.a))
            x[:, i + 1] = decay * x[:, i] + std * z_r[:, i]

        b = (1.0 - np.exp(-self.a * times)) / self.a
        phi = self._forward(times) + 0.5 * self.sigma_r**2 * b * b
        r = x + phi[np.newaxis, :]

        # Equity: log-Euler with the *pathwise* short rate in the drift. Unlike plain GBM there
        # is no exact step once r is stochastic, but the rate varies slowly (mean-reverting,
        # ~100bp vol) so trapezoidal integration over the observation grid is adequate — the
        # sigma_r -> 0 regression test would catch a drift bias.
        log_s = np.full(n_paths, np.log(self.spot))
        spots = np.empty((n_paths, n_steps + 1))
        spots[:, 0] = self.spot
        integ = np.zeros(n_paths)
        for i, h in enumerate(dt):
            r_mid = 0.5 * (r[:, i] + r[:, i + 1])
            log_s += (r_mid - self.q - 0.5 * self.sigma**2) * h + self.sigma * np.sqrt(h) * normals[:, i]
            spots[:, i + 1] = np.exp(log_s)
            integ += r_mid * h
            if i == 0:
                deflators = np.empty((n_paths, n_steps + 1))
                deflators[:, 0] = 1.0
            deflators[:, i + 1] = np.exp(-integ)
        return spots, deflators


def price_mc_hw(
    product: Product,
    model: BlackScholesHW,
    *,
    n_paths: int = 100_000,
    antithetic: bool = True,
    seed: int = 0,
    method: str = "pseudo",
) -> PriceResult:
    """Monte-Carlo price of ``product`` under stochastic rates, with pathwise deflation.

    Mirrors :func:`spdt.pricing.engine.price_mc` — same grid construction, same RNG — but each
    cashflow is discounted by *its own path's* realised deflator at the cashflow time, which is
    the risk-neutral valuation once rates are stochastic. A deterministic curve applied to
    stochastic-rate paths would drop the rate-equity covariance term entirely, which is most of
    what this model exists to price.
    """
    from spdt.pricing.engine import _simulation_grid
    from spdt.pricing.mc.rng import standard_normals

    grid = _simulation_grid(product.monitoring_times(), None)
    normals = standard_normals(
        n_paths, grid.size - 1, antithetic=antithetic, seed=seed, method=method
    )
    spots, deflators = model.simulate_joint(grid, normals, seed=seed)
    paths = PathSet(times=grid, spots=spots)
    time_col = {float(t): i for i, t in enumerate(grid)}

    per_path = np.zeros(n_paths)
    for cf in product.cashflows(paths):
        per_path += deflators[:, time_col[float(cf.time)]] * cf.amount
    price = float(per_path.mean())
    std_error = float(per_path.std(ddof=1) / np.sqrt(n_paths)) if n_paths > 1 else 0.0
    return PriceResult(price=price, std_error=std_error, n_paths=n_paths)
