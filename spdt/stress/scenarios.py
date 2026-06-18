"""Stress testing: apply coherent macro scenarios and reprice the book (L12).

The central discipline here is **coherence**: a real equity crash is not a lone −30% spot
bump — it arrives with a volatility spike and (for multi-asset books) correlations rushing
toward 1. Shocking one factor at a time understates the loss and misreads the risk, so each
named scenario bundles the moves that historically travel together. The engine transforms the
pricing model, reprices every trade by full revaluation, and decomposes the hit by product.

Correlation-breakdown scenarios are defined but only bite once worst-of/multi-asset pricing
exists; for the single-underlying book they are no-ops on the (one-name) correlation.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from spdt.book.book import Trade
from spdt.pricing.engine import price_mc
from spdt.pricing.models import BlackScholes


@dataclass(frozen=True)
class Scenario:
    """A coherent multi-factor market shock (all moves applied together)."""

    name: str
    spot_shock: float = 0.0  # relative, e.g. −0.30 for a 30% crash
    vol_shock: float = 0.0  # additive vol points, e.g. +0.10
    rate_shock: float = 0.0  # additive, e.g. +0.01
    div_shock: float = 0.0  # additive to the dividend yield
    corr_shock: float | None = None  # target average correlation (multi-asset; see module doc)

    def apply(self, model: BlackScholes) -> BlackScholes:
        """Return the model with this scenario's shocks applied coherently."""
        return dataclasses.replace(
            model,
            spot=model.spot * (1.0 + self.spot_shock),
            sigma=max(model.sigma + self.vol_shock, 1e-6),
            r=model.r + self.rate_shock,
            q=model.q + self.div_shock,
        )


# Coherent named scenarios — the moves that travel together (the defend point).
EQUITY_CRASH = Scenario("equity_crash", spot_shock=-0.30, vol_shock=0.10, rate_shock=-0.005)
MILD_SELLOFF = Scenario("mild_selloff", spot_shock=-0.10, vol_shock=0.03)
VOL_SPIKE = Scenario("vol_spike", vol_shock=0.10)
RATE_SHOCK_UP = Scenario("rate_shock_up", rate_shock=0.01)
CORR_BREAKDOWN = Scenario("corr_breakdown", spot_shock=-0.15, vol_shock=0.05, corr_shock=0.9)

STANDARD_SCENARIOS = (EQUITY_CRASH, MILD_SELLOFF, VOL_SPIKE, RATE_SHOCK_UP)


@dataclass(frozen=True)
class StressResult:
    """Book-level stress impact with a per-trade decomposition."""

    scenario: str
    base_pv: float
    stressed_pv: float
    per_trade_pnl: dict[str, float]

    @property
    def pnl(self) -> float:
        return self.stressed_pv - self.base_pv


def stress_book(
    trades: list[Trade],
    model: BlackScholes,
    scenario: Scenario,
    *,
    n_paths: int = 100_000,
    seed: int = 0,
) -> StressResult:
    """Reprice ``trades`` under ``scenario`` (full reval, CRN) and decompose the P&L."""
    shocked = scenario.apply(model)
    base_pv = 0.0
    stressed_pv = 0.0
    per_trade: dict[str, float] = {}
    for trade in trades:
        base = trade.direction * price_mc(trade.product, model, n_paths=n_paths, seed=seed).price
        new = trade.direction * price_mc(trade.product, shocked, n_paths=n_paths, seed=seed).price
        base_pv += base
        stressed_pv += new
        per_trade[trade.trade_id] = new - base
    return StressResult(scenario.name, base_pv, stressed_pv, per_trade)
