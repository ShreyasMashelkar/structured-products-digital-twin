"""Replication Engine: builds a hedge portfolio for a decomposed product.

The ReplicationEngine takes a :class:`~spdt.decomposition.decomposer.Decomposition`
(a list of RiskComponents) and dispatches each component to the appropriate
ReplicationStrategy. It returns a single :class:`ReplicationPortfolio` containing all the
hedge instruments required to replicate the structured product.
"""

from __future__ import annotations

from typing import Any

from spdt.decomposition.components import RiskComponent
from spdt.decomposition.decomposer import Decomposition
from spdt.replication.portfolio import HedgeInstrument, ReplicationPortfolio
from spdt.replication.strategies.base import AbstractReplicationStrategy


class ReplicationEngine:
    """Registry-based dispatcher: RiskComponent → Strategy → HedgeInstruments."""

    def __init__(self) -> None:
        self._registry: dict[str, AbstractReplicationStrategy] = {}

    def register(self, hedge_strategy: str, strategy: AbstractReplicationStrategy) -> None:
        """Register a replication strategy for a specific hedge_strategy hint."""
        self._registry[hedge_strategy] = strategy

    def replicate_component(
        self, component: RiskComponent, model: Any, surface: Any = None
    ) -> tuple[HedgeInstrument, ...]:
        """Replicate a single RiskComponent."""
        strategy = self._registry.get(component.hedge_strategy)
        if strategy is None:
            raise ValueError(
                f"No replication strategy registered for hint: '{component.hedge_strategy}'"
            )
        return strategy.replicate(component, model, surface)

    def replicate(
        self, decomposition: Decomposition, model: Any, surface: Any = None
    ) -> ReplicationPortfolio:
        """Replicate a full Decomposition into a single HedgePortfolio."""
        all_instruments: list[HedgeInstrument] = []
        for component in decomposition.components:
            # Funding components might return empty if they are conditional
            # and handled elsewhere. We just aggregate whatever comes back.
            instruments = self.replicate_component(component, model, surface)
            all_instruments.extend(instruments)

        return ReplicationPortfolio(
            instruments=tuple(all_instruments),
            # In a full implementation, we would sum the residual Greeks here
            # by calling strategy.residual_greeks() for each component.
        )


def _default_engine() -> ReplicationEngine:
    """Build the default engine with all catalog strategies registered."""
    from spdt.replication.strategies.autocall_replication import AutocallReplicationStrategy
    from spdt.replication.strategies.barrier_replication import BarrierReplicationStrategy
    from spdt.replication.strategies.correlation_replication import CorrelationReplicationStrategy
    from spdt.replication.strategies.digital_replication import DigitalReplicationStrategy
    from spdt.replication.strategies.funding_replication import FundingReplicationStrategy
    from spdt.replication.strategies.vanilla_replication import VanillaReplicationStrategy

    engine = ReplicationEngine()
    engine.register("semi_static_replication", BarrierReplicationStrategy())
    engine.register("digital_replication", DigitalReplicationStrategy(relative_spread_width=0.01))
    engine.register("delta_hedge", VanillaReplicationStrategy())
    engine.register("curve_hedge", FundingReplicationStrategy())
    engine.register("digital_strip_replication", AutocallReplicationStrategy(relative_spread_width=0.01))
    engine.register("dispersion_trade", CorrelationReplicationStrategy())
    return engine


_ENGINE: ReplicationEngine | None = None


def get_engine() -> ReplicationEngine:
    """Return the singleton default replication engine (lazily initialised)."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = _default_engine()
    return _ENGINE


def replicate(decomposition: Decomposition, model: Any, surface: Any = None) -> ReplicationPortfolio:
    """Convenience: replicate a decomposed product using the default engine."""
    return get_engine().replicate(decomposition, model, surface)
