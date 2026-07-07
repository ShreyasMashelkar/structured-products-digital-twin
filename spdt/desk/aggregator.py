"""Desk Risk Aggregation Engine (Phase 6).

Sweeps a full trading book, decomposing every exotic trade into risk components,
replicating them into static hedge portfolios, and computing the final net Greek
reallocations to the Delta 1 and Exotics desks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from spdt.book.book import Trade
from spdt.decomposition import decompose
from spdt.greeks.bump import GreekSet
from spdt.greeks.reallocation import ReallocatedGreeks
from spdt.greeks.residual import ResidualGreekCalculator
from spdt.greeks.routing import DeskRouter, DeskRoutingSlip
from spdt.replication.engine import ReplicationEngine, get_engine
from spdt.replication.portfolio import ReplicationPortfolio


@dataclass(frozen=True)
class EndOfDayRiskReport:
    """The consolidated EOD risk report for the Head of Desk."""

    total_trades_processed: int
    net_desk_routing: DeskRoutingSlip
    # In a full system, this would also include trade-level breakdowns,
    # P(KO) heatmaps from the BarrierBookManager, etc.


class DeskRiskAggregator:
    """Aggregates and routes risks across a full book of trades."""

    def __init__(
        self,
        replication_engine: ReplicationEngine | None = None,
        residual_calculator: ResidualGreekCalculator | None = None,
    ):
        self.replication_engine = replication_engine or get_engine()
        self.residual_calculator = residual_calculator or ResidualGreekCalculator(rel_spot_bump=1e-2)

    def _add_greek_sets(self, g1: GreekSet, g2: GreekSet) -> GreekSet:
        """Utility to add two GreekSets."""
        return GreekSet(
            delta=g1.delta + g2.delta,
            gamma=g1.gamma + g2.gamma,
            vega=g1.vega + g2.vega,
            rho=g1.rho + g2.rho,
        )

    def _add_routing_slips(self, s1: DeskRoutingSlip, s2: DeskRoutingSlip) -> DeskRoutingSlip:
        """Utility to add two DeskRoutingSlips."""
        return DeskRoutingSlip(
            delta_1_desk=self._add_greek_sets(s1.delta_1_desk, s2.delta_1_desk),
            vanilla_options_desk=self._add_greek_sets(s1.vanilla_options_desk, s2.vanilla_options_desk),
            exotics_desk=self._add_greek_sets(s1.exotics_desk, s2.exotics_desk),
            funding_desk=self._add_greek_sets(s1.funding_desk, s2.funding_desk),
        )

    def generate_eod_report(
        self, trades: list[Trade], model: Any, n_paths: int = 10_000, seed: int = 0
    ) -> EndOfDayRiskReport:
        """Process the book and generate the net routing slip."""

        # Initialize an empty routing slip
        zero_greeks = GreekSet(0.0, 0.0, 0.0, 0.0)
        net_routing = DeskRoutingSlip(
            delta_1_desk=zero_greeks,
            vanilla_options_desk=zero_greeks,
            exotics_desk=zero_greeks,
            funding_desk=zero_greeks,
        )

        for trade in trades:
            # 1. Decompose the product
            decomposition = decompose(trade.product)

            for component in decomposition.components:
                # 2. Replicate the component (returns tuple of HedgeInstrument)
                instruments = self.replication_engine.replicate_component(component, model)
                portfolio = ReplicationPortfolio(instruments=instruments)

                # 3. Calculate Reallocated Greeks (Hedge vs Residual)
                reallocated = self.residual_calculator.calculate_residual(
                    component=component,
                    portfolio=portfolio,
                    model=model,
                    n_paths=n_paths,
                    seed=seed,
                )

                # Apply trade direction (e.g. if we are short the product, flip the greeks)
                # Note: component.direction is intrinsic to the product (e.g. short put).
                # Trade direction is whether the desk bought (+1) or sold (-1) the product.
                direction = trade.direction

                scaled_reallocated = ReallocatedGreeks(
                    total_product_greeks=GreekSet(
                        delta=reallocated.total_product_greeks.delta * direction,
                        gamma=reallocated.total_product_greeks.gamma * direction,
                        vega=reallocated.total_product_greeks.vega * direction,
                        rho=reallocated.total_product_greeks.rho * direction,
                    ),
                    hedge_portfolio_greeks=GreekSet(
                        delta=reallocated.hedge_portfolio_greeks.delta * direction,
                        gamma=reallocated.hedge_portfolio_greeks.gamma * direction,
                        vega=reallocated.hedge_portfolio_greeks.vega * direction,
                        rho=reallocated.hedge_portfolio_greeks.rho * direction,
                    ),
                    residual_exotic_greeks=GreekSet(
                        delta=reallocated.residual_exotic_greeks.delta * direction,
                        gamma=reallocated.residual_exotic_greeks.gamma * direction,
                        vega=reallocated.residual_exotic_greeks.vega * direction,
                        rho=reallocated.residual_exotic_greeks.rho * direction,
                    ),
                )

                # 4. Route the risks to the desks
                slip = DeskRouter.route(scaled_reallocated)

                # Accumulate
                net_routing = self._add_routing_slips(net_routing, slip)

        return EndOfDayRiskReport(
            total_trades_processed=len(trades),
            net_desk_routing=net_routing,
        )
