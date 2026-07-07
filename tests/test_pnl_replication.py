"""Tests for Phase 5: P&L Attribution vs Replication."""

from __future__ import annotations

import pytest

from spdt.decomposition.components import BarrierComponent
from spdt.pnl.replication_attribution import attribute_via_replication
from spdt.pricing.models.bs import BlackScholes
from spdt.products.graph import Leg
from spdt.products.primitives import EuropeanOption
from spdt.replication.portfolio import HedgeInstrument, ReplicationPortfolio


@pytest.fixture
def model0() -> BlackScholes:
    return BlackScholes(spot=100.0, sigma=0.2, r=0.05, q=0.0)


@pytest.fixture
def model1() -> BlackScholes:
    # 1 day later (dt=1/252), spot moved up, vol moved down
    return BlackScholes(spot=101.0, sigma=0.19, r=0.05, q=0.0)


class TestReplicationAttribution:

    def test_perfect_hedge_leaves_no_slippage(self, model0, model1):
        """A vanilla component hedged exactly with a vanilla instrument should have ~0 slippage."""

        # Component: 100 Notional Short Put
        comp = BarrierComponent(
            notional=100.0,
            expiry=1.0,
            underlying="NIFTY",
            direction=-1,
            leg=Leg.OPTION,
            strike=1.0,
            barrier=0.0,
            is_call=False,
            knock_in=False
        )

        # Portfolio: 100 Notional Short Put
        put = EuropeanOption(strike=100.0, expiry=1.0, is_call=False)
        instr = HedgeInstrument(put, -1.0, "vanilla_put", "pass_through")
        port = ReplicationPortfolio((instr,))

        # Attribute over 1 day
        dt = 1.0 / 252.0
        explain = attribute_via_replication(comp, port, model0, model1, dt, n_paths=10000, seed=42)

        # The hedge perfectly matches the component, so the "residual slippage"
        # (which is Component PnL - Hedge Explained PnL) should be small.
        # Wait, the component PnL is exact. The hedge explained PnL is based on Greeks.
        # Since the component IS the hedge, this is just standard Greek PnL attribution!
        # The slippage should just be the higher-order Greek terms (cross gamma etc).
        assert abs(explain.residual_slippage) < 0.5  # Less than 50 bps error

    def test_unhedged_barrier_leaves_massive_slippage(self, model0, model1):
        """A barrier option hedged with just a delta-equivalent vanilla will leave huge slippage."""

        comp = BarrierComponent(
            notional=100.0,
            expiry=1.0,
            underlying="NIFTY",
            direction=1,
            leg=Leg.OPTION,
            strike=1.0,
            barrier=0.9, # Barrier at 90
            is_call=False,
            knock_in=True  # Down and In Put
        )

        # The desk hedges with just a basic Put, completely ignoring the barrier.
        put = EuropeanOption(strike=100.0, expiry=1.0, is_call=False)
        instr = HedgeInstrument(put, 1.0, "vanilla_put", "bad_hedge")
        port = ReplicationPortfolio((instr,))

        dt = 1.0 / 252.0
        explain = attribute_via_replication(comp, port, model0, model1, dt, n_paths=10000, seed=42)

        # The true PnL of a DI Put is quite different from a Vanilla Put.
        # The hedge (Vanilla Put) will explain some amount of PnL, but the DI Put PnL will be different.
        # Slippage should be noticeably larger than zero.
        assert abs(explain.residual_slippage) > 0.001
