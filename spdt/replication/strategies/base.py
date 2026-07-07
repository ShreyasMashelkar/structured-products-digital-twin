"""Base interface for component replication strategies.

Each strategy takes a specific subclass of ``RiskComponent`` and produces a list of
``HedgeInstrument`` objects that, in aggregate, replicate its payoff and risks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from spdt.decomposition.components import RiskComponent
from spdt.greeks.bump import GreekSet
from spdt.replication.portfolio import HedgeInstrument


class AbstractReplicationStrategy(ABC):
    """Interface for translating a RiskComponent into a portfolio of hedge instruments."""

    @abstractmethod
    def replicate(
        self, component: RiskComponent, model: Any, surface: Any = None
    ) -> tuple[HedgeInstrument, ...]:
        """Generate the replication portfolio for the given component.

        Args:
            component: The RiskComponent to replicate.
            model: The current market model (e.g., BlackScholes) for computing strikes/weights.
            surface: (Optional) Volatility surface for more complex calibrations.

        Returns:
            A tuple of HedgeInstrument objects.
        """
        pass

    def residual_greeks(
        self,
        component: RiskComponent,
        hedge_instruments: tuple[HedgeInstrument, ...],
        model: Any,
    ) -> GreekSet:
        """Compute the Greeks of the unhedged residual: PV(component) - PV(hedge).

        By default, returns an empty (zero) GreekSet, assuming perfect replication.
        Concrete strategies should override this if they leave residual risks (e.g.,
        call-spread replication leaving local gamma).
        """
        return GreekSet(delta=0.0, gamma=0.0, vega=0.0, rho=0.0)
