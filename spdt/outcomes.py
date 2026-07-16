"""Outcome studies that turn the pricing stack into interview-ready evidence.

The functions in this module deliberately report distributions and hedge economics rather
than another model mark.  They are deterministic, use an out-of-sample path set for hedge
evaluation, and keep their assumptions in the returned payload so synthetic evidence is not
mistaken for observed exchange history.
"""

from __future__ import annotations

from math import exp, sqrt
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
from scipy.special import ndtr

from spdt.backtest import aggregate, generate_realized_series, roll_issuance
from spdt.decomposition.components import BarrierComponent
from spdt.pricing.analytic import bs_vanilla
from spdt.pricing.engine import PathModel, _simulation_grid
from spdt.pricing.mc.rng import standard_normals
from spdt.pricing.models import BlackScholes
from spdt.products import Autocallable, EuropeanOption
from spdt.products.graph import Leg, PathSet, Product
from spdt.replication.strategies.barrier_replication import BarrierReplicationStrategy


def outcome_profile(
    product: Product, model: PathModel, *, n_paths: int = 20_000, seed: int = 0
) -> dict[str, Any]:
    """Client-facing outcome distribution for *any* DSL product under forward MC.

    Generic over the payoff DSL: per-path cashflow totals give the return distribution,
    the last payment time gives each path's life, and life short of maturity means early
    redemption (autocall). Risk-neutral paths — outcome *probabilities* are model-implied,
    stated as such in the explorer's disclaimer.
    """
    monitoring = product.monitoring_times()
    grid = _simulation_grid(monitoring, None)
    normals = standard_normals(n_paths, grid.size - 1, antithetic=True, seed=seed)
    paths = PathSet(times=grid, spots=model.simulate(grid, normals))

    notional = float(getattr(product, "notional", 100.0))
    maturity = float(max(monitoring))
    total = np.zeros(n_paths)
    last_pay = np.zeros(n_paths)
    for cf in product.cashflows(paths):
        total += cf.amount
        paid = cf.amount > 1e-9
        last_pay[paid] = np.maximum(last_pay[paid], cf.time)
    last_pay[last_pay <= 0.0] = maturity  # paid nothing → held to maturity

    tol = 1e-9
    autocalled = last_pay < maturity - tol
    life = np.where(autocalled, last_pay, maturity)
    returns = total / notional - 1.0
    annualised = np.power(np.maximum(1.0 + returns, 1e-9), 1.0 / life) - 1.0

    def pct(mask: np.ndarray) -> float:
        return round(float(mask.mean() * 100.0), 4)

    return {
        "n_paths": n_paths,
        "prob_autocall_pct": pct(autocalled),
        "prob_loss_pct": pct(total < notional - tol),
        "mean_return_pa_pct": round(float(annualised.mean() * 100.0), 2),
        "median_return_pct": round(float(np.median(returns) * 100.0), 2),
        "p5_return_pct": round(float(np.percentile(returns, 5) * 100.0), 2),
        "p95_return_pct": round(float(np.percentile(returns, 95) * 100.0), 2),
        "median_life_years": round(float(np.median(life)), 4),
        "autocall_by_period": [
            {"time": float(t), "prob_pct": pct(autocalled & (np.abs(last_pay - t) <= tol))}
            for t in sorted(set(monitoring))
        ],
    }


@dataclass(frozen=True)
class OutcomeTerms:
    """The single contract carried through issuance, hedging and the case study."""

    maturity: float
    observations_per_year: int
    coupon_rate: float  # per observation
    knock_in: float
    coupon_barrier: float = 0.70
    autocall_level: float = 1.0
    notional: float = 100.0

    @property
    def observation_times(self) -> tuple[float, ...]:
        n = round(self.maturity * self.observations_per_year)
        return tuple((i + 1) / self.observations_per_year for i in range(n))


def _realised_regime_series(spot: float, sigma: float, seed: int) -> np.ndarray:
    # Three regimes stop a single constant drift from flattering the result: expansion, sell-off,
    # then recovery.  A real close series can replace this seam without changing the note engine.
    segments = ((5, 0.10, sigma), (3, -0.08, sigma * 1.35), (7, 0.07, sigma * 0.9))
    pieces: list[np.ndarray] = []
    level = spot
    for i, (years, mu, vol) in enumerate(segments):
        path = generate_realized_series(252 * years, s0=level, mu=mu, sigma=vol, seed=seed + i)
        pieces.append(path if i == 0 else path[1:])
        level = float(path[-1])
    return np.concatenate(pieces)


def issuance_study(
    spot: float, sigma: float, terms: OutcomeTerms, *, seeds: tuple[int, ...] = (3, 7, 11, 19, 23)
) -> dict[str, Any]:
    """Roll one contract across a five-path deterministic regime ensemble."""
    note = Autocallable(
        notional=terms.notional,
        observation_times=terms.observation_times,
        coupon_rate=terms.coupon_rate,
        autocall_level=terms.autocall_level,
        coupon_barrier=terms.coupon_barrier,
        knock_in=terms.knock_in,
        memory=True,
        initial_fixing=spot,
    )
    paths = [_realised_regime_series(spot, sigma, seed) for seed in seeds]
    outcome_sets = [roll_issuance(series, note, issuance_step_days=21) for series in paths]
    outcomes = [outcome for cohort in outcome_sets for outcome in cohort]
    stats = aggregate(outcomes, terms.notional)
    lives = np.array([
        ((cast(int, o.autocall_period) + 1) / terms.observations_per_year)
        if o.autocalled else terms.maturity
        for o in outcomes
    ])
    total_returns = np.array([o.total_payoff / terms.notional - 1.0 for o in outcomes])
    annualised = np.power(np.maximum(1.0 + total_returns, 1e-9), 1.0 / lives) - 1.0
    display_outcomes = outcome_sets[len(outcome_sets) // 2]
    monthly = paths[len(paths) // 2][::21]
    cohorts = []
    for i, outcome in enumerate(display_outcomes):
        life = ((cast(int, outcome.autocall_period) + 1) / terms.observations_per_year) if outcome.autocalled else terms.maturity
        ret = outcome.total_payoff / terms.notional - 1.0
        cohorts.append({
            "cohort": i + 1,
            "year": round(i / 12.0, 2),
            "return_pct": round(float(ret * 100.0), 3),
            "life_years": round(float(life), 2),
            "outcome": "Autocalled" if outcome.autocalled else ("Capital loss" if outcome.capital_loss else "Matured"),
        })
    per_seed = [aggregate(x, terms.notional) for x in outcome_sets]
    return {
        "source": f"Synthetic 15y regime ensemble · {len(seeds)} independent paths",
        "source_note": "Robustness ensemble, not observed NIFTY history. Production mode must load point-in-time closes and corporate-action-clean index levels.",
        "terms": f"{terms.maturity:.0f}Y NIFTY Phoenix · quarterly · {terms.coupon_rate * terms.observations_per_year * 100:.2f}% p.a. coupon · {terms.knock_in:.0%} KI · monthly issuance",
        "n_issuances": stats.n_issuances,
        "autocall_rate_pct": round(stats.autocall_rate * 100.0, 2),
        "loss_rate_pct": round(stats.loss_rate * 100.0, 2),
        "mean_return_pa_pct": round(float(annualised.mean() * 100.0), 2),
        "median_life_years": round(float(np.median(lives)), 2),
        "tail_return_pct": round((stats.worst_5pct_return - 1.0) * 100.0, 2),
        "worst_return_pct": round(float(total_returns.min() * 100.0), 2),
        "robustness": {
            "autocall_rate_range_pct": [round(min(x.autocall_rate for x in per_seed) * 100, 2), round(max(x.autocall_rate for x in per_seed) * 100, 2)],
            "loss_rate_range_pct": [round(min(x.loss_rate for x in per_seed) * 100, 2), round(max(x.loss_rate for x in per_seed) * 100, 2)],
            "n_paths": len(seeds),
        },
        "cohorts": cohorts,
        "index_path": [{"month": i, "level": round(float(v), 2)} for i, v in enumerate(monthly)],
    }


def _put_delta(spot: np.ndarray, strike: float, tau: float, model: BlackScholes) -> np.ndarray:
    tau = max(tau, 1e-8)
    d1 = (np.log(spot / strike) + (model.r - model.q + 0.5 * model.sigma**2) * tau) / (model.sigma * sqrt(tau))
    return np.exp(-model.q * tau) * (ndtr(d1) - 1.0)


def _strategy_row(name: str, pnl: np.ndarray, turnover: np.ndarray, costs: np.ndarray) -> dict[str, Any]:
    # Average exactly the worst 5% rather than every observation <= the percentile.  Discrete
    # barrier payoffs have a large atom at the no-hit P&L; threshold inclusion can otherwise pull
    # most paths into the tail and incorrectly report ES near zero.
    tail_count = max(1, int(np.ceil(0.05 * pnl.size)))
    worst = np.partition(pnl, tail_count - 1)[:tail_count]
    return {
        "strategy": name,
        "pnl_std": round(float(pnl.std(ddof=1)), 4),
        "expected_shortfall_95": round(float(-worst.mean()), 4),
        "mean_pnl": round(float(pnl.mean()), 4),
        "turnover": round(float(turnover.mean()), 4),
        "transaction_cost": round(float(costs.mean()), 4),
    }


def _terminal_ki_delta(
    spot: np.ndarray, strike: float, barrier: float, tau: float, model: BlackScholes
) -> np.ndarray:
    """Exact BS delta of ``(K-S_T)+ 1{S_T<=B}`` for B < K."""
    tau = max(tau, 1e-8)
    root = model.sigma * sqrt(tau)
    d1 = (np.log(spot / barrier) + (model.r - model.q + 0.5 * model.sigma**2) * tau) / root
    d2 = d1 - root
    pdf1 = np.exp(-0.5 * d1 * d1) / sqrt(2.0 * np.pi)
    pdf2 = np.exp(-0.5 * d2 * d2) / sqrt(2.0 * np.pi)
    return (
        -strike * np.exp(-model.r * tau) * pdf2 / (spot * root)
        - np.exp(-model.q * tau) * ndtr(-d1)
        + np.exp(-model.q * tau) * pdf1 / root
    )


def hedge_comparison(
    spot: float, sigma: float, r: float, q: float, terms: OutcomeTerms, *, seed: int = 23
) -> dict[str, Any]:
    """Compare constrained hedges for the contract's terminal knock-in put."""
    model = BlackScholes(spot=spot, sigma=sigma, r=r, q=q)
    expiry, steps, n_paths = terms.maturity, round(52 * terms.maturity), 16_000
    times = np.linspace(0.0, expiry, steps + 1, dtype=np.float64)
    normals = np.random.default_rng(seed).standard_normal((n_paths, steps))
    paths = model.simulate(times, normals)
    barrier, strike, quantity = terms.knock_in * spot, spot, terms.notional / spot
    target_payoff = quantity * np.maximum(strike - paths[:, -1], 0.0) * (paths[:, -1] <= barrier)
    premium = exp(-r * expiry) * float(target_payoff.mean())

    component = BarrierComponent(
        notional=terms.notional, expiry=expiry, underlying="NIFTY", direction=1, leg=Leg.OPTION,
        strike=1.0, barrier=terms.knock_in, monitoring=(expiry,), initial_fixing=spot,
    )
    strip = BarrierReplicationStrategy(n_paths=24_000, n_strikes=19, seed=seed + 100).replicate(component, model)
    strip_strikes = np.array(
        [cast(EuropeanOption, h.instrument).strike for h in strip], dtype=np.float64
    )
    strip_weights = np.array([h.weight for h in strip], dtype=np.float64)
    strip_cost = float(np.dot(strip_weights, [
        bs_vanilla(spot, k, expiry, r, q, sigma, False) for k in strip_strikes
    ]))
    strip_payoff = np.maximum(strip_strikes[None, :] - paths[:, -1, None], 0.0) @ strip_weights
    slip = 4e-4

    static_gross = float(np.abs(strip_weights).sum() * spot)
    static_execution_cost = slip * static_gross

    def dynamic(*, static_scale: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        inception_cost = static_scale * static_execution_cost
        cash = np.full(n_paths, premium - static_scale * strip_cost - inception_cost)
        shares = np.zeros(n_paths)
        turnover = np.full(n_paths, static_scale * static_gross)
        costs = np.full(n_paths, inception_cost)
        for i in range(steps):
            s = paths[:, i]
            tau = expiry - times[i]
            target_delta = quantity * _terminal_ki_delta(s, strike, barrier, tau, model)
            strip_delta = static_scale * np.sum(
                np.stack([w * _put_delta(s, k, tau, model) for k, w in zip(strip_strikes, strip_weights)]),
                axis=0,
            )
            desired = target_delta - strip_delta
            trade = desired - shares
            tc = slip * np.abs(trade) * s
            cash -= trade * s + tc
            turnover += np.abs(trade) * s
            costs += tc
            shares = desired
            cash *= exp(r * expiry / steps)
        close = slip * np.abs(shares) * paths[:, -1]
        costs += close
        turnover += np.abs(shares) * paths[:, -1]
        pnl = cash + shares * paths[:, -1] - close + static_scale * strip_payoff - target_payoff
        return pnl, turnover, costs

    delta_pnl, delta_turnover, delta_cost = dynamic(static_scale=0.0)
    # The hybrid consumes at most half the desk's 5x gross inventory budget; the residual is
    # delta hedged. The scale is policy-derived rather than an unexplained hard-coded allocation.
    hybrid_scale = min(1.0, (2.5 * terms.notional) / max(static_gross, 1e-12))
    hybrid_pnl, hybrid_turnover, hybrid_cost = dynamic(static_scale=hybrid_scale)
    static_pnl = (
        (premium - strip_cost - static_execution_cost) * exp(r * expiry)
        + strip_payoff - target_payoff
    )
    zero = np.zeros(n_paths)
    unhedged_pnl = premium * exp(r * expiry) - target_payoff
    rows = [
        _strategy_row("Unhedged", unhedged_pnl, zero, zero),
        _strategy_row("Delta-only", delta_pnl, delta_turnover, delta_cost),
        _strategy_row(
            "Semi-static", static_pnl, np.full(n_paths, static_gross),
            np.full(n_paths, static_execution_cost),
        ),
        _strategy_row("Hybrid", hybrid_pnl, hybrid_turnover, hybrid_cost),
    ]
    base_std = rows[0]["pnl_std"]
    for row in rows:
        row["risk_reduction_pct"] = round(100.0 * (1.0 - row["pnl_std"] / base_std), 2)
        row["eligible"] = row["turnover"] <= 5.0 * terms.notional and row["transaction_cost"] <= 0.02 * terms.notional
        row["selection_score"] = round(row["expected_shortfall_95"] + 0.01 * row["turnover"], 4)
    eligible = [row for row in rows[1:] if row["eligible"]]
    best = min(eligible, key=lambda x: x["selection_score"])
    return {
        "target": f"Dealer hedge of the {terms.maturity:.0f}Y {terms.knock_in:.0%} terminal KI put embedded in the client termsheet",
        "method": "16,000 out-of-sample weekly paths · exact BS terminal-KI delta · 4bp execution · listed-grid strip capped at 5x face",
        "strategies": rows,
        "best_strategy": best["strategy"],
        "best_risk_reduction_pct": best["risk_reduction_pct"],
        "selection_rule": "Minimise ES95 + 1% of turnover, subject to 5x gross and 2% cost limits",
        "hybrid_static_scale_pct": round(100.0 * hybrid_scale, 2),
        "static_instruments": len(strip),
    }
