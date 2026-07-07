"""Tests for the Universal Replication Framework (Phase 2).

Verifies that:
1. Each RiskComponent replicates to the correct instruments (e.g. Barrier -> Vanilla Puts).
2. The static vanilla strip reproduces the barrier component PV.
3. The call-spread weights for a digital correctly size the maximum payout.
4. The ReplicationEngine can orchestrate a full Decomposition.
5. Unknown strategies raise exceptions.
"""

from __future__ import annotations

import pytest

from spdt.decomposition import decompose
from spdt.decomposition.components import (
    BarrierComponent,
    DigitalComponent,
    VanillaComponent,
)
from spdt.pricing.engine import price_mc
from spdt.pricing.models.bs import BlackScholes
from spdt.products.catalog import BarrierReverseConvertible
from spdt.products.graph import Leg
from spdt.replication import replicate
from spdt.replication.engine import ReplicationEngine
from spdt.replication.strategies.barrier_replication import BarrierReplicationStrategy
from spdt.replication.strategies.digital_replication import DigitalReplicationStrategy


@pytest.fixture
def model() -> BlackScholes:
    return BlackScholes(spot=100.0, sigma=0.2, r=0.05, q=0.0)


# ---------------------------------------------------------------------------
# Barrier Replication (Mirror Strike)
# ---------------------------------------------------------------------------

class TestBarrierReplication:

    def test_down_out_uses_in_out_parity(self, model):
        component = BarrierComponent(
            notional=100.0,
            expiry=1.0,
            underlying="NIFTY",
            direction=-1,  # Short the DO put
            leg=Leg.OPTION,
            strike=1.0,  # 100
            barrier=0.8, # 80
            is_call=False,
            knock_in=False, # Let's test a DO Put to see the Vanilla - Mirror logic
        )

        strategy = BarrierReplicationStrategy()
        instruments = strategy.replicate(component, model)

        assert len(instruments) > 5
        base_put = [i for i in instruments if i.purpose == "barrier_base"][0]
        assert base_put.instrument.strike == 100.0
        assert base_put.weight == -1.0  # 100 cash notional / 100 initial fixing
        assert all(i.purpose == "barrier_static_strip" for i in instruments[1:])

    def test_di_put_replication_matches_pv(self, model):
        component = BarrierComponent(
            notional=100.0,
            expiry=1.0,
            underlying="NIFTY",
            direction=1,
            leg=Leg.OPTION,
            strike=1.0,
            barrier=0.8,
            is_call=False,
            knock_in=True,
            monitoring=(0.25, 0.5, 0.75, 1.0),
            initial_fixing=100.0,
        )

        strategy = BarrierReplicationStrategy()
        instruments = strategy.replicate(component, model)

        assert len(instruments) > 5
        target = price_mc(component.as_product(model.spot), model, n_paths=80_000, seed=9).price
        hedge = sum(
            item.weight * price_mc(item.instrument, model, n_paths=80_000, seed=9).price
            for item in instruments
        )
        assert abs(target - hedge) < 0.10

    def test_strip_respects_listed_grid_and_gross_limit(self):
        nifty = BlackScholes(spot=24_100.0, sigma=0.2, r=0.05, q=0.01)
        component = BarrierComponent(
            notional=100.0, expiry=2.0, underlying="NIFTY", direction=1,
            leg=Leg.OPTION, strike=1.0, barrier=0.7, monitoring=(2.0,),
            initial_fixing=24_100.0,
        )
        instruments = BarrierReplicationStrategy(n_paths=12_000).replicate(component, nifty)
        assert all(item.instrument.strike % 50.0 == 0.0 for item in instruments)
        gross = sum(abs(item.weight) * nifty.spot for item in instruments)
        assert gross <= 5.0 * component.notional


# ---------------------------------------------------------------------------
# Digital Replication (Call Spread)
# ---------------------------------------------------------------------------

class TestDigitalReplication:

    def test_call_spread_strikes_and_weights(self, model):
        component = DigitalComponent(
            notional=100.0,
            expiry=1.0,
            underlying="NIFTY",
            direction=1,
            leg=Leg.OPTION,
            strike=1.0,  # 100
            payout=0.05, # Pays 5 on notional 100
            is_call=True,
        )

        strategy = DigitalReplicationStrategy(relative_spread_width=0.02)
        instruments = strategy.replicate(component, model)

        assert len(instruments) == 2
        long_leg = [i for i in instruments if i.purpose == "call_spread_long"][0]
        short_leg = [i for i in instruments if i.purpose == "call_spread_short"][0]

        # dK = 100 * 0.02 = 2.0
        # K_low = 100 - 1 = 99
        # K_high = 100 + 1 = 101
        assert long_leg.instrument.strike == 99.0
        assert short_leg.instrument.strike == 101.0

        # Payout target = 5.0 * direction 1 = 5.0
        # dK = 2.0
        # units = 5.0 / 2.0 = 2.5
        assert long_leg.weight == 2.5
        assert short_leg.weight == -2.5


# ---------------------------------------------------------------------------
# Full Engine Orchestration
# ---------------------------------------------------------------------------

class TestReplicationEngine:

    def test_replicate_brc(self, model):
        brc = BarrierReverseConvertible(
            notional=100.0,
            observation_times=(1.0,),
            coupon_rate=0.05,
            strike=1.0,
            knock_in=0.8,
        )

        decomp = decompose(brc)
        portfolio = replicate(decomp, model)

        # BRC = ZCB + FixedCoupons - a liquid vanilla strip for the DI put.
        assert len(portfolio.instruments) > 5
        purposes = [i.purpose for i in portfolio.instruments]
        assert purposes.count("curve_hedge") == 2
        assert purposes.count("barrier_static_strip") > 3

    def test_autocall_replication_dispatches_all_components(self, model):
        from spdt.products.catalog import Autocallable

        note = Autocallable(
            100.0, (0.5, 1.0), 0.02, initial_fixing=100.0
        )
        portfolio = replicate(decompose(note), model)
        assert portfolio.instruments
        assert any(i.purpose == "call_spread_long" for i in portfolio.instruments)

    def test_unregistered_strategy_raises(self, model):
        # Create an engine with nothing registered
        engine = ReplicationEngine()

        component = VanillaComponent(
            notional=100.0, expiry=1.0, underlying="NIFTY", direction=1, leg=Leg.OPTION, strike=1.0
        )

        with pytest.raises(ValueError, match="No replication strategy registered"):
            engine.replicate_component(component, model)
