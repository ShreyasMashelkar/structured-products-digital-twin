"""Tests for the Desk Risk Aggregation Engine (Phase 6)."""

from __future__ import annotations

import pytest

from spdt.book.book import Trade
from spdt.desk.aggregator import DeskRiskAggregator
from spdt.pricing.models.bs import BlackScholes
from spdt.products.catalog import BarrierReverseConvertible, CapitalProtectedNote


@pytest.fixture
def model() -> BlackScholes:
    return BlackScholes(spot=100.0, sigma=0.2, r=0.05, q=0.0)


class TestDeskRiskAggregator:

    def test_aggregate_mixed_book(self, model):
        """End-to-end test of the full architecture (Phase 1-6)."""

        # 1. BRC: Investor sells down-and-in put (desk is LONG the put -> positive gamma)
        # BRC = Zero Coupon Bond + Fixed Coupons - DI Put
        # Since desk sells the BRC (trade.direction = -1), desk is:
        # Short ZCB, Short Coupons, Long DI Put
        brc = BarrierReverseConvertible(
            notional=100_000.0,
            observation_times=(1.0,),
            coupon_rate=0.05,
            strike=1.0,
            knock_in=0.80,
        )
        trade1 = Trade("T1", brc, direction=-1)

        # 2. CPN: Investor buys a call option (desk is SHORT the call -> negative gamma)
        # CPN = ZCB + Call Option
        # Desk sells the CPN (trade.direction = -1), desk is:
        # Short ZCB, Short Call Option
        cpn = CapitalProtectedNote(
            notional=100_000.0,
            maturity=1.0,
            participation=1.0,
            strike=1.0,
        )
        trade2 = Trade("T2", cpn, direction=-1)

        aggregator = DeskRiskAggregator()

        # Run the aggregator (using a small number of paths for speed in tests)
        report = aggregator.generate_eod_report([trade1, trade2], model, n_paths=2_000, seed=42)

        assert report.total_trades_processed == 2

        # -------------------------------------------------------------------
        # Sanity check the Desk Routing Slip
        # -------------------------------------------------------------------
        slip = report.net_desk_routing

        # 1. Delta 1 Desk should have non-zero delta from the hedges
        # BRC hedge: Long Mirror Put, Short base Put (wait, it's a DI Put, so just Long Mirror Put)
        # Trade is -1 (sell BRC), so Desk is Long BRC's embedded short put -> Desk is Long DI Put.
        # Mirror put is a put, so Delta is negative. Desk is Long, so Delta is negative.
        # CPN hedge: Call Option. Trade is -1, so Desk is Short Call -> Delta is negative.
        # Therefore, total hedge delta should be negative.
        assert slip.delta_1_desk.delta < 0

        # 2. Vanilla Options Desk should have the hedge Vega.
        # Mirror Put has positive vega. Long it -> positive.
        # Short Call has positive vega. Short it -> negative.
        # Depending on strikes (64 for mirror, 100 for call), they will net. But it should exist.
        assert slip.vanilla_options_desk.vega != 0.0

        # 3. Exotics Desk holds the residual tracking error.
        # The BRC DI Put has a local gamma cliff near the barrier that the mirror strike
        # cannot perfectly replicate over discrete time / MC noise.
        # Thus, Exotics will hold some non-zero residual gamma/delta.
        assert slip.exotics_desk.gamma != 0.0

        # 4. Funding desk holds the Rho (Interest rate risk).
        # Short ZCBs have negative Rho (higher rates = lower value = desk makes money).
        # Wait, if rate goes up, ZCB value goes down. Desk is Short ZCB, so desk liability goes down -> Positive PnL.
        # Delta PV = Rho * dr. If dr > 0, PnL > 0, so Rho > 0.
        # Let's just ensure it's not zero.
        assert slip.funding_desk.rho != 0.0
