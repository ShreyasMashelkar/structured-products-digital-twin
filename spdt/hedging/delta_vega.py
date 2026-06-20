"""Hedging engine: simulate dynamic delta hedging and measure how well it works (L9).

The trader sells an option, banks the premium, and dynamically holds the Black-Scholes delta
in the underlying, rebalancing on a discrete grid. In the continuous-rebalancing limit this
replicates the payoff and the hedging P&L is zero; in practice it is a random variable whose
**standard deviation scales with √Δt** — the classic discrete-rebalancing replication error.
Transaction-cost slippage is a drag on the mean (you pay the spread every time you trade).

We hedge a European under Black-Scholes using the analytic delta (exact and cheap, so the
residual is purely the discretisation error, not a Greek approximation).

**Gap risk.** A continuous delta hedge replicates *diffusion* but cannot catch an overnight
*jump*: the hedge ratio is set before the gap and the spot has already moved through it by the
time the desk can re-hedge. We overlay a compound-Poisson jump (intensity ``jump_intensity``,
log-jump ``N(jump_mean, jump_std²)``) on the path; the option was priced *without* the jump, so
the realised P&L carries a fat left tail that **no amount of rebalancing removes** — the defining
risk of a short-gamma autocallable book near its knock-in. The 5th-percentile P&L isolates it.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, sqrt

import numpy as np
from numpy.typing import NDArray
from scipy.special import ndtr

from spdt.pricing.analytic import bs_vanilla
from spdt.pricing.mc.rng import standard_normals
from spdt.pricing.models import BlackScholes, HestonModel
from spdt.products.primitives import EuropeanOption

_INV_SQRT_2PI = 1.0 / sqrt(2.0 * np.pi)


def _bs_delta(
    spot: NDArray[np.float64], strike: float, tau: float, r: float, q: float,
    sigma: NDArray[np.float64] | float, is_call: bool,
) -> NDArray[np.float64]:
    d1 = (np.log(spot / strike) + (r - q + 0.5 * sigma * sigma) * tau) / (sigma * np.sqrt(tau))
    return np.exp(-q * tau) * (ndtr(d1) if is_call else ndtr(d1) - 1.0)


def _bs_vega(
    spot: NDArray[np.float64], strike: float, tau: float, r: float, q: float,
    sigma: NDArray[np.float64] | float,
) -> NDArray[np.float64]:
    d1 = (np.log(spot / strike) + (r - q + 0.5 * sigma * sigma) * tau) / (sigma * np.sqrt(tau))
    return spot * np.exp(-q * tau) * _INV_SQRT_2PI * np.exp(-0.5 * d1 * d1) * np.sqrt(tau)


@dataclass(frozen=True)
class HedgeResult:
    """Distribution of dynamic-hedging P&L for a sold option."""

    mean_pnl: float
    std_pnl: float
    mean_slippage_cost: float
    n_paths: int
    n_steps: int
    tail_5pct: float = 0.0  # 5th-percentile P&L — the gap-loss tail when jumps are on

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
    jump_intensity: float = 0.0,
    jump_mean: float = -0.10,
    jump_std: float = 0.03,
) -> HedgeResult:
    """Delta-hedge a *sold* European over ``n_steps`` rebalances; return the P&L distribution.

    With ``jump_intensity > 0`` an overnight compound-Poisson gap is overlaid on the path; the
    delta set before the gap cannot catch it, so the P&L picks up a fat left tail (``tail_5pct``)
    that rebalancing more frequently does *not* remove — the gap risk a desk reserves against.
    """
    k, t, is_call = option.strike, option.expiry, option.is_call
    r, q, sigma = model.r, model.q, model.sigma
    dt = t / n_steps
    grow = exp(r * dt)
    slip = slippage_bps * 1e-4

    times: NDArray[np.float64] = np.linspace(0.0, t, n_steps + 1)
    normals = standard_normals(n_paths, n_steps, seed=seed)
    spots = model.simulate(times, normals)  # (n_paths, n_steps + 1)

    if jump_intensity > 0.0:
        # Compound-Poisson jumps per step; a jump in (t_i, t_{i+1}] shifts the whole path from
        # i+1 onward (delta set at t_i is blind to it ⇒ the gap is un-hedged).
        jrng = np.random.default_rng(seed + 991)
        counts = jrng.poisson(jump_intensity * dt, (n_paths, n_steps))
        log_jump = jump_mean * counts + jump_std * np.sqrt(counts) * jrng.standard_normal((n_paths, n_steps))
        spots[:, 1:] *= np.exp(np.cumsum(log_jump, axis=1))

    premium = bs_vanilla(model.spot, k, t, r, q, sigma, is_call)
    cash = np.full(n_paths, premium)
    shares: NDArray[np.float64] = np.zeros(n_paths)
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
        tail_5pct=float(np.percentile(pnl, 5)),
    )


@dataclass(frozen=True)
class VegaHedgeResult:
    """Hedging-P&L dispersion under stochastic vol: delta-only vs delta + static vega."""

    delta_only_std: float
    delta_vega_std: float
    n_paths: int
    n_steps: int

    @property
    def vega_hedge_ratio(self) -> float:
        """How much of the vol risk the vega hedge removes (1 − std ratio)."""
        return 1.0 - self.delta_vega_std / self.delta_only_std if self.delta_only_std else 0.0


def simulate_delta_vega_hedge(
    heston: HestonModel,
    target: EuropeanOption,
    hedge: EuropeanOption,
    *,
    n_steps: int = 50,
    n_paths: int = 40_000,
    seed: int = 0,
) -> VegaHedgeResult:
    """Compare delta-only vs delta + static-vega hedging of a sold option under **Heston**.

    Under stochastic vol, delta-hedging at the instantaneous vol leaves the option's *vega*
    exposed — vol moves drive P&L variance. Buying ``vega_target / vega_hedge`` units of a
    second vanilla neutralises that first-order vol risk, leaving only vanna/volga and the
    drift of the ratio. So ``delta_vega_std < delta_only_std`` — the desk's reason to vega-hedge.
    """
    k, t, is_call = target.strike, target.expiry, target.is_call
    kh = hedge.strike
    r, q = heston.r, heston.q
    dt = t / n_steps
    grow = exp(r * dt)
    sqrt_dt = sqrt(dt)
    rho, kappa, theta, xi = heston.rho, heston.kappa, heston.theta, heston.xi

    rng = np.random.default_rng(seed)
    log_s = np.full(n_paths, np.log(heston.spot))
    var = np.full(n_paths, heston.v0)
    spots = np.empty((n_paths, n_steps + 1))
    vols = np.empty((n_paths, n_steps + 1))
    spots[:, 0] = heston.spot
    vols[:, 0] = sqrt(heston.v0)
    for i in range(n_steps):
        w1 = rng.standard_normal(n_paths)
        w2 = rho * w1 + sqrt(1.0 - rho * rho) * rng.standard_normal(n_paths)
        sv = np.sqrt(np.maximum(var, 0.0))
        log_s = log_s + (r - q - 0.5 * var) * dt + sv * sqrt_dt * w1
        var = np.maximum(var + kappa * (theta - var) * dt + xi * sv * sqrt_dt * w2, 0.0)
        spots[:, i + 1] = np.exp(log_s)
        vols[:, i + 1] = np.sqrt(np.maximum(var, 0.0)) + 1e-6

    prem_t = heston.vanilla(k, t, is_call)
    prem_h = heston.vanilla(kh, t, is_call)
    # Static vega-hedge ratio set at inception from BS vegas at the initial vol.
    v0 = sqrt(heston.v0)
    nratio = float(_bs_vega(np.array([heston.spot]), k, t, r, q, v0)[0]
                   / _bs_vega(np.array([heston.spot]), kh, t, r, q, v0)[0])

    def run(n_vega: float) -> float:
        cash = np.full(n_paths, prem_t - n_vega * prem_h)
        shares = np.zeros(n_paths)
        for i in range(n_steps):
            tau = t - i * dt
            net_delta = (_bs_delta(spots[:, i], k, tau, r, q, vols[:, i], is_call)
                         - n_vega * _bs_delta(spots[:, i], kh, tau, r, q, vols[:, i], is_call))
            cash -= (net_delta - shares) * spots[:, i]
            shares = net_delta
            cash *= grow
        s_t = spots[:, n_steps]
        pay_t = np.maximum(s_t - k, 0.0) if is_call else np.maximum(k - s_t, 0.0)
        pay_h = np.maximum(s_t - kh, 0.0) if is_call else np.maximum(kh - s_t, 0.0)
        pnl = cash + shares * s_t + n_vega * pay_h - pay_t
        return float(pnl.std(ddof=1))

    return VegaHedgeResult(
        delta_only_std=run(0.0), delta_vega_std=run(nratio),
        n_paths=n_paths, n_steps=n_steps,
    )
