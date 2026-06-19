"""Virtual trading book: positions, daily marks, and netted aggregate Greeks (L8).

A book holds the desk's booked notes. Marking it under a market reprices every trade (L4)
and computes its Greeks (L5), then **nets** across positions — the desk runs net delta/vega,
not gross. The defend point this surfaces directly: a book of autocallable notes is
structurally **short volatility** (aggregate vega negative — the holder of an autocallable has
sold optionality), and risk concentrates where one underlying carries most of the gamma.

``direction`` is the position sign: ``+1`` for a note held long (the default, giving the
short-vol book above), ``-1`` for a sold position. Marks are computed under common random
numbers (shared seed) for stability.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spdt.greeks.bump import GreekSet, bump_greeks
from spdt.pricing.engine import price_mc
from spdt.pricing.models import BlackScholes
from spdt.products.graph import Product


@dataclass(frozen=True)
class Trade:
    """A booked position: a product, a sign, and an underlying tag."""

    trade_id: str
    product: Product
    underlying: str = "NIFTY"
    direction: int = 1  # +1 = note held long (short-vol book); -1 = sold position


@dataclass(frozen=True)
class PositionMark:
    """One trade's mark and risk under a given market."""

    trade_id: str
    pv: float
    greeks: GreekSet


@dataclass(frozen=True)
class BookMark:
    """A whole-book snapshot: per-trade marks plus the netted totals."""

    positions: list[PositionMark]
    total_pv: float
    net_greeks: GreekSet

    def concentration_by_underlying(self) -> dict[str, float]:
        """(For reporting) net |gamma| share — populated by the marking helper."""
        return self._gamma_by_underlying

    _gamma_by_underlying: dict[str, float] = field(default_factory=dict)


def mark_book(
    trades: list[Trade], model: BlackScholes, *, n_paths: int = 100_000, seed: int = 0
) -> BookMark:
    """Mark every trade under ``model`` and net the results across the book."""
    positions: list[PositionMark] = []
    net = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "rho": 0.0}
    total_pv = 0.0
    gamma_by_underlying: dict[str, float] = {}

    for trade in trades:
        pv = trade.direction * price_mc(trade.product, model, n_paths=n_paths, seed=seed).price
        g = bump_greeks(trade.product, model, n_paths=n_paths, seed=seed)
        signed = GreekSet(
            delta=trade.direction * g.delta,
            gamma=trade.direction * g.gamma,
            vega=trade.direction * g.vega,
            rho=trade.direction * g.rho,
        )
        positions.append(PositionMark(trade.trade_id, pv, signed))
        total_pv += pv
        net["delta"] += signed.delta
        net["gamma"] += signed.gamma
        net["vega"] += signed.vega
        net["rho"] += signed.rho
        gamma_by_underlying[trade.underlying] = (
            gamma_by_underlying.get(trade.underlying, 0.0) + abs(signed.gamma)
        )

    return BookMark(
        positions=positions,
        total_pv=total_pv,
        net_greeks=GreekSet(**net),
        _gamma_by_underlying=gamma_by_underlying,
    )
