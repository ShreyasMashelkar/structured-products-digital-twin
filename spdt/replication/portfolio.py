"""Replication portfolio and hedge instruments (Phase 2).

A replication portfolio is a collection of liquid hedge instruments designed to mimic the
value and risks of a target RiskComponent (or full structured product).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spdt.products.graph import Product

if TYPE_CHECKING:
    from spdt.greeks.bump import GreekSet


@dataclass(frozen=True)
class HedgeInstrument:
    """A single hedging instrument in a replication portfolio.

    The ``instrument`` is a primitive (like a VanillaOption) that can be priced natively.
    The ``weight`` is the notional amount of the instrument to hold (can be negative).
    """

    instrument: Product
    weight: float
    instrument_type: str  # e.g., "vanilla_put", "digital_call", "future"
    purpose: str  # e.g., "barrier_static_strip", "call_spread_long_wing"


@dataclass(frozen=True)
class ReplicationPortfolio:
    """A collection of hedge instruments designed to replicate a component."""

    instruments: tuple[HedgeInstrument, ...]
    residual_greeks: GreekSet | None = None
    expected_error: float | None = None
    liquidity_requirement: float | None = None

    @property
    def total_weight_absolute(self) -> float:
        """Sum of absolute weights (proxy for transaction costs/liquidity requirement)."""
        return sum(abs(i.weight) for i in self.instruments)
