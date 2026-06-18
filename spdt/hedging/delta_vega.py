"""Hedging engine: simulate dynamic delta hedging and measure how well it works (L9).

The trader sells an option, banks the premium, and dynamically holds the Black-Scholes delta
in the underlying, rebalancing on a discrete grid. In the continuous-rebalancing limit this
replicates the payoff and the hedging P&L is zero; in practice it is a random variable whose
**standard deviation scales with √Δt** — the classic discrete-rebalancing replication error.
Transaction-cost slippage is a drag on the mean (you pay the spread every time you trade).

We hedge a European under Black-Scholes using the analytic delta (exact and cheap, so the
residual is purely the discretisation error, not a Greek approximation). Vega hedging and the
gap-risk tail for the autocallable build on this same loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, sqrt

import numpy as np
from numpy.typing import NDArray
from scipy.special import ndtr

from spdt.pricing.analytic import bs_vanilla
from spdt.pricing.mc.rng import standard_normals
from spdt.pricing.models import BlackScholes
from spdt.products.primitives import EuropeanOption


def _bs_delta(
    spot: NDArray[np.float64], strike: float, tau: float, r: float, q: float, sigma: float,
    is_call: bool,
) -> NDArray[np.float64]:
    d1 = (np.log(spot / strike) + (r - q + 0.5 * sigma * sigma) * tau) / (sigma * sqrt(tau))
    return np.exp(-q * tau) * (ndtr(d1) if is_call else ndtr(d1) - 1.0)


@dataclass(frozen=True)
class HedgeResult:
    """Distribution of dynamic-hedging P&L for a sold option."""

    mean_pnl: float
    std_pnl: float
    mean_slippage_cost: float
    n_paths: int
    n_steps: int

    @property
    def std_error(self) -> float:
        return self.std_pnl / sqrt(self.n_paths)


def simulate_delta_hedge(
    model: BlackScholes,
    option: EuropeanOption,
    *,
    n_steps: int = 50,
    n_paths: int = 50_000,
    seed: int = 0,
    slippage_bps: float = 0.0,
) -> HedgeResult:
    """Delta-hedge a *sold* European over ``n_steps`` rebalances; return the P&L distribution."""
    k, t, is_call = option.strike, option.expiry, option.is_call
    r, q, sigma = model.r, model.q, model.sigma
    dt = t / n_steps
    grow = exp(r * dt)
    slip = slippage_bps * 1e-4

    times = np.linspace(0.0, t, n_steps + 1)
    normals = standard_normals(n_paths, n_steps, seed=seed)
    spots = model.simulate(times, normals)  # (n_paths, n_steps + 1)

    premium = bs_vanilla(model.spot, k, t, r, q, sigma, is_call)
    cash = np.full(n_paths, premium)
    shares = np.zeros(n_paths)
    slippage_cost = np.zeros(n_paths)

    for i in range(n_steps):
        delta = _bs_delta(spots[:, i], k, t - times[i], r, q, sigma, is_call)
        trade = delta - shares
        cost = slip * np.abs(trade) * spots[:, i]
        cash -= trade * spots[:, i] + cost
        slippage_cost += cost
        shares = delta
        cash *= grow

    s_final = spots[:, n_steps]
    close_cost = slip * np.abs(shares) * s_final
    cash += shares * s_final - close_cost
    slippage_cost += close_cost
    payoff = np.maximum(s_final - k, 0.0) if is_call else np.maximum(k - s_final, 0.0)
    pnl = cash - payoff

    return HedgeResult(
        mean_pnl=float(pnl.mean()),
        std_pnl=float(pnl.std(ddof=1)),
        mean_slippage_cost=float(slippage_cost.mean()),
        n_paths=n_paths,
        n_steps=n_steps,
    )
