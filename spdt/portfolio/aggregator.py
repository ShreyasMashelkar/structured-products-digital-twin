"""Portfolio Risk Aggregator: sweep a book of trades and aggregate net Greeks."""

from __future__ import annotations

from typing import Sequence

from spdt.book.book import Trade
from spdt.decomposition import decompose
from spdt.greeks.bump import GreekSet
from spdt.greeks.residual import ResidualGreekCalculator
from spdt.replication.engine import ReplicationEngine, get_engine


class PortfolioAggregator:
    """Aggregates net risks across the full portfolio before hedging."""

    def __init__(
        self,
        replication_engine: ReplicationEngine | None = None,
        residual_calculator: ResidualGreekCalculator | None = None,
    ):
        self.replication_engine = replication_engine or get_engine()
        self.residual_calculator = residual_calculator or ResidualGreekCalculator()

    def aggregate_gross_and_net_risk(
        self, trades: Sequence[Trade], model, n_paths: int = 10_000, seed: int = 0
    ) -> tuple[GreekSet, GreekSet]:
        """Returns (gross_risk, net_risk). Gross is sum of absolute risks, Net is sum of signed risks."""

        net_delta = 0.0
        net_gamma = 0.0
        net_vega = 0.0

        gross_delta = 0.0
        gross_gamma = 0.0
        gross_vega = 0.0

        for trade in trades:
            decomposition = decompose(trade.product)
            for component in decomposition.components:
                # 1. Replicate to get standard hedges
                instruments = self.replication_engine.replicate_component(component, model)

                # 2. Get component risks
                # We could run full residual calc, or just bump the component directly
                # To keep it fast for portfolio aggregation, we'll just sum the raw greeks of the component.
                # Actually, the DeskRiskAggregator does residual splits. For pure netting, we just want net product risk.

                # Let's use the residual calculator to get the total product greeks
                from spdt.replication.portfolio import ReplicationPortfolio
                portfolio = ReplicationPortfolio(instruments=instruments)

                reallocated = self.residual_calculator.calculate_residual(
                    component, portfolio, model, n_paths=n_paths, seed=seed
                )

                dir = trade.direction
                d = reallocated.total_product_greeks.delta * dir
                g = reallocated.total_product_greeks.gamma * dir
                v = reallocated.total_product_greeks.vega * dir

                net_delta += d
                net_gamma += g
                net_vega += v

                gross_delta += abs(d)
                gross_gamma += abs(g)
                gross_vega += abs(v)

        gross = GreekSet(delta=gross_delta, gamma=gross_gamma, vega=gross_vega, rho=0.0)
        net = GreekSet(delta=net_delta, gamma=net_gamma, vega=net_vega, rho=0.0)
        return gross, net
