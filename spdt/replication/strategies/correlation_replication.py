"""Dispersion trade tracking for Correlation components.

Correlation risk (e.g., from a Worst-of basket) cannot be replicated with single-name
options. It requires a dispersion trade (e.g., short index variance vs long single-name
variance, or correlation swaps).

This strategy is descriptive: it outputs a placeholder instrument flagging the required
dispersion exposure, which the portfolio netting engine (Phase 5) will aggregate.
"""

from __future__ import annotations

from typing import Any

from spdt.decomposition.components import CorrelationComponent, RiskComponent
from spdt.products.graph import Cashflow, PathSet, Product
from spdt.replication.portfolio import HedgeInstrument
from spdt.replication.strategies.base import AbstractReplicationStrategy


class SyntheticCorrelationSwap(Product):
    """A synthetic placeholder product representing correlation exposure."""

    def __init__(self, underlyings: tuple[str, ...], maturity: float):
        self.underlyings = underlyings
        self.maturity = maturity

    def monitoring_times(self) -> tuple[float, ...]:
        return (self.maturity,)

    def cashflows(self, paths: PathSet) -> list[Cashflow]:
        return []


class CorrelationReplicationStrategy(AbstractReplicationStrategy):
    """Flags correlation risk for the dispersion desk."""

    def replicate(
        self, component: RiskComponent, model: Any, surface: Any = None
    ) -> tuple[HedgeInstrument, ...]:
        if not isinstance(component, CorrelationComponent):
            raise TypeError("Expected CorrelationComponent")

        # Create a synthetic placeholder product to track the exposure
        swap = SyntheticCorrelationSwap(
            underlyings=component.underlyings,
            maturity=component.expiry,
        )

        return (
            HedgeInstrument(
                instrument=swap,
                weight=component.notional * component.direction,
                instrument_type="correlation_swap",
                purpose="dispersion_hedge",
            ),
        )
