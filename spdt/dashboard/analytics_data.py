"""Book-linked analytics payload for the Semi-Static Hedging workspace."""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from math import erf, exp, log, pi, sqrt
from typing import Any

from spdt.book.book import Trade
from spdt.decomposition import decompose
from spdt.decomposition.components import BarrierComponent
from spdt.greeks.bump import GreekSet, bump_greeks
from spdt.pricing.analytic.black_scholes import bs_vanilla
from spdt.pricing.models.bs import BlackScholes
from spdt.products.primitives import EuropeanOption
from spdt.replication.portfolio import ReplicationPortfolio
from spdt.replication.strategies.barrier_replication import BarrierReplicationStrategy
from spdt.semistatic.monitor import ReplicationMonitor
from spdt.semistatic.pre_unwind import PreUnwindOptimizer
from spdt.semistatic.probability import BarrierProbabilityEngine


def _barriers(trades: list[Trade]) -> list[tuple[Trade, BarrierComponent]]:
    out: list[tuple[Trade, BarrierComponent]] = []
    for trade in trades:
        try:
            decomposition = decompose(trade.product)
        except TypeError:
            continue
        for component in decomposition.components:
            if isinstance(component, BarrierComponent):
                signed = dataclasses.replace(
                    component, direction=component.direction * trade.direction
                )
                out.append((trade, signed))
    return out


def _vanilla_greeks(option: EuropeanOption, model: BlackScholes) -> GreekSet:
    """Closed-form vanilla Greeks in the same per-unit conventions as ``GreekSet``."""
    if option.expiry <= 0.0 or model.sigma <= 0.0:
        return GreekSet(0.0, 0.0, 0.0, 0.0)
    s, k, t, sigma = model.spot, option.strike, option.expiry, model.sigma
    d1 = (log(s / k) + (model.r - model.q + 0.5 * sigma * sigma) * t) / (sigma * sqrt(t))
    pdf = exp(-0.5 * d1 * d1) / sqrt(2.0 * pi)
    disc_q = exp(-model.q * t)
    delta_call = disc_q * 0.5 * (1.0 + erf(d1 / sqrt(2.0)))
    delta = delta_call if option.is_call else delta_call - disc_q
    gamma = disc_q * pdf / (s * sigma * sqrt(t))
    vega = s * disc_q * pdf * sqrt(t)
    h = 1e-5
    rho = (
        bs_vanilla(s, k, t, model.r + h, model.q, sigma, option.is_call)
        - bs_vanilla(s, k, t, model.r - h, model.q, sigma, option.is_call)
    ) / (2.0 * h)
    return GreekSet(delta, gamma, vega, rho)


def _portfolio_metrics(portfolio: ReplicationPortfolio, model: BlackScholes) -> tuple[float, GreekSet]:
    pv = delta = gamma = vega = rho = 0.0
    for item in portfolio.instruments:
        if not isinstance(item.instrument, EuropeanOption):
            continue
        option = item.instrument
        weight = item.weight
        pv += weight * bs_vanilla(
            model.spot, option.strike, option.expiry, model.r, model.q, model.sigma,
            option.is_call,
        )
        greeks = _vanilla_greeks(option, model)
        delta += weight * greeks.delta
        gamma += weight * greeks.gamma
        vega += weight * greeks.vega
        rho += weight * greeks.rho
    return pv, GreekSet(delta, gamma, vega, rho)


def _empty_payload(selected_trade_id: str | None, message: str) -> dict[str, Any]:
    return {
        "selected_trade_id": selected_trade_id,
        "pre_unwind": [],
        "portfolio": [],
        "risk_ladder": [],
        "tracking": [],
        "summary": {
            "total_static_notional": 0.0,
            "residual_delta": 0.0,
            "residual_gamma": 0.0,
            "residual_cash_delta_1pct": 0.0,
            "residual_cash_gamma_1pct": 0.0,
            "tracking_error": 0.0,
            "gross_limit": 0.0,
            "perspective": "signed booked position",
            "position_label": "NO BARRIER POSITION",
        },
        "methodology": {
            "model": "Black-Scholes discrete-monitoring projection",
            "probability": "risk-neutral contractual monitoring schedule",
            "strike_grid": "listed-style grid",
            "position_perspective": "Trade.direction from the booked position",
        },
        "message": message,
    }


def build_semistatic_payload(
    trades: list[Trade], model: BlackScholes, *, selected_trade_id: str | None = None,
    lifecycle_states: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build deterministic semi-static analytics from the same trades shown in the blotter."""
    barrier_rows = _barriers(trades)
    if not barrier_rows:
        return _empty_payload(selected_trade_id, "No barrier-bearing trades in the current book.")

    strategy = BarrierReplicationStrategy(n_paths=18_000, n_strikes=15)
    lifecycle_states = lifecycle_states or {}
    pre_unwind: list[dict[str, Any]] = []
    constructed: list[tuple[Trade, BarrierComponent, ReplicationPortfolio]] = []
    for trade, component in barrier_rows:
        fixing = component.fixing(model.spot)
        barrier = component.barrier * fixing
        state = lifecycle_states.get(trade.trade_id, {})
        elapsed = max(float(state.get("elapsed_years", 0.0)), 0.0)
        remaining_monitoring = tuple(
            max(t - elapsed, 0.0) for t in component.monitoring if t > elapsed
        )
        p_hit = BarrierProbabilityEngine.p_hit_discrete(
            model.spot, barrier, model.sigma,
            remaining_monitoring or (max(component.expiry - elapsed, 0.0),),
            model.r, model.q, is_down=not component.is_call,
        )
        observed_breached = state.get("barrier_breached")
        current_unwound = float(state.get("unwound_fraction", 0.0))
        target_unwind = 0.0 if component.knock_in else PreUnwindOptimizer.get_unwind_fraction(p_hit)
        incremental_unwind = max(target_unwind - current_unwound, 0.0)
        if component.knock_in:
            if observed_breached is True:
                status, lifecycle_action, target_action_pct = "KNOCKED_IN", "Transition to vanilla", 100.0
            elif observed_breached is None:
                status, lifecycle_action, target_action_pct = "STATE_UNKNOWN", "Load observations", None
            else:
                status = "WATCH" if p_hit >= 0.5 else "SAFE"
                lifecycle_action, target_action_pct = "Maintain static strip", None
        else:
            if observed_breached is True:
                status, lifecycle_action, target_action_pct = "KNOCKED_OUT", "Close replication", 100.0
            elif observed_breached is None:
                status, lifecycle_action, target_action_pct = "STATE_UNKNOWN", "Load observations", None
            else:
                status = "ACTION_REQD" if incremental_unwind > 0.0 else "SAFE"
                lifecycle_action = "Pre-unwind" if incremental_unwind > 0.0 else "Maintain hedge"
                target_action_pct = 100.0 * target_unwind if target_unwind > 0.0 else None
        pre_unwind.append({
            "trade_id": trade.trade_id,
            "underlying": trade.underlying,
            "barrier_type": "KI" if component.knock_in else "KO",
            "barrier": barrier,
            "spot": model.spot,
            "distance_pct": 100.0 * (model.spot - barrier) / model.spot,
            "p_hit": 100.0 * p_hit,
            "lifecycle_action": lifecycle_action,
            "target_action_pct": target_action_pct,
            "executed_action_pct": 100.0 * current_unwound,
            "incremental_action_pct": 100.0 * incremental_unwind,
            "monitoring": "terminal" if len(component.monitoring) == 1 else f"{len(component.monitoring)} dates",
            "status": status,
        })
        constructed.append((trade, component, ReplicationPortfolio(strategy.replicate(component, model))))

    selected = next(
        (row for row in constructed if row[0].trade_id == selected_trade_id), constructed[0]
    )
    selected_trade, selected_component, selected_portfolio = selected

    portfolio_rows: list[dict[str, Any]] = []
    for item in selected_portfolio.instruments:
        if not isinstance(item.instrument, EuropeanOption):
            continue
        option = item.instrument
        greeks = _vanilla_greeks(option, model)
        portfolio_rows.append({
            "instrument": f"{'Call' if option.is_call else 'Put'} {option.strike:.2f}",
            "maturity": f"{option.expiry:.2f}Y",
            "strike": option.strike,
            "weight": item.weight,
            "notional": item.weight * model.spot,
            "delta": item.weight * greeks.delta,
            "gamma": item.weight * greeks.gamma,
            "vega": item.weight * greeks.vega,
            "purpose": item.purpose,
        })

    buckets: dict[str, dict[str, float]] = defaultdict(
        lambda: {"delta_target": 0.0, "delta_hedge": 0.0,
                 "gamma_target": 0.0, "gamma_hedge": 0.0}
    )
    for _trade, component, portfolio in constructed:
        key = f"{round(component.barrier * 20.0) * 5:.0f}%"
        target_product = component.as_product(model.spot)
        if target_product is None:  # defensive: barrier puts currently always provide a primitive
            continue
        target = bump_greeks(target_product, model, n_paths=7_000, seed=41)
        _, hedge = _portfolio_metrics(portfolio, model)
        buckets[key]["delta_target"] += target.delta
        buckets[key]["delta_hedge"] += hedge.delta
        buckets[key]["gamma_target"] += target.gamma
        buckets[key]["gamma_hedge"] += hedge.gamma
    one_pct_move = model.spot * 0.01
    risk_ladder = [
        {
            "bucket": key,
            **values,
            "cash_delta_target_1pct": values["delta_target"] * one_pct_move,
            "cash_delta_hedge_1pct": values["delta_hedge"] * one_pct_move,
            # Second-order P&L contribution ½Γ(ΔS)² for a 1% absolute spot move.
            "cash_gamma_target_1pct": 0.5 * values["gamma_target"] * one_pct_move**2,
            "cash_gamma_hedge_1pct": 0.5 * values["gamma_hedge"] * one_pct_move**2,
        }
        for key, values in sorted(buckets.items())
    ]

    tracking: list[dict[str, Any]] = []
    monitor = ReplicationMonitor(error_threshold=max(0.01 * selected_component.notional, 0.01))
    for factor in (0.75, 0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15):
        scenario_model = dataclasses.replace(model, spot=model.spot * factor)
        snapshot = monitor.evaluate(
            selected_component, selected_portfolio, scenario_model, n_paths=8_000, seed=73
        )
        tracking.append({
            "scenario": f"{factor:.0%}",
            "spot": scenario_model.spot,
            "target_pv": snapshot.component_pv,
            "hedge_pv": snapshot.replication_pv,
            "error": snapshot.tracking_error,
        })

    current = next(row for row in tracking if row["scenario"] == "100%")
    residual_delta = sum(
        values["delta_target"] - values["delta_hedge"] for values in buckets.values()
    )
    residual_gamma = sum(
        values["gamma_target"] - values["gamma_hedge"] for values in buckets.values()
    )
    return {
        "selected_trade_id": selected_trade.trade_id,
        "pre_unwind": pre_unwind,
        "portfolio": portfolio_rows,
        "risk_ladder": risk_ladder,
        "tracking": tracking,
        "summary": {
            "total_static_notional": sum(abs(x["notional"]) for x in portfolio_rows),
            "residual_delta": residual_delta,
            "residual_gamma": residual_gamma,
            "residual_cash_delta_1pct": residual_delta * one_pct_move,
            "residual_cash_gamma_1pct": 0.5 * residual_gamma * one_pct_move**2,
            "tracking_error": current["error"],
            "gross_limit": strategy.max_gross_multiple * selected_component.notional,
            "perspective": "signed booked position",
            "position_label": "LONG NOTE / HOLDER" if selected_trade.direction > 0 else "ISSUED NOTE / DEALER LIABILITY",
        },
        "methodology": {
            "model": "Black-Scholes discrete-monitoring projection",
            "probability": "risk-neutral contractual monitoring schedule",
            "strike_grid": "listed-style 50-point grid at NIFTY levels",
            "position_perspective": "Trade.direction from the booked position",
        },
        "message": None if selected_trade.trade_id == selected_trade_id or selected_trade_id is None
                   else "Selected trade has no supported barrier component; showing the first barrier trade.",
    }
