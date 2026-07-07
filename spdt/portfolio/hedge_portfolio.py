"""Portfolio Hedge Engine: computes the optimal portfolio hedge."""

from __future__ import annotations

from typing import Sequence

from spdt.greeks.bump import GreekSet
from spdt.optimization.constraints import HedgeConstraints
from spdt.optimization.engine import HedgeOptimizationEngine, OptimalHedge
from spdt.replication.portfolio import HedgeInstrument


class PortfolioHedgeEngine:
    """Produces the optimal hedge for a net portfolio risk."""

    def __init__(self, optimizer: HedgeOptimizationEngine | None = None):
        self.optimizer = optimizer or HedgeOptimizationEngine()

    def generate_portfolio_hedge(
        self,
        net_portfolio_risk: GreekSet,
        available_instruments: Sequence[HedgeInstrument],
        instrument_greeks: Sequence[GreekSet],
        constraints: HedgeConstraints | None = None,
    ) -> OptimalHedge:
        """Find the optimal hedge portfolio to neutralize the net portfolio risk."""

        c = constraints or HedgeConstraints()

        return self.optimizer.optimize(
            target_greeks=net_portfolio_risk,
            available_instruments=available_instruments,
            instrument_greeks=instrument_greeks,
            constraints=c,
        )
