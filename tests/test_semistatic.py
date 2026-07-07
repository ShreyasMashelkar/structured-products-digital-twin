"""Tests for the Semi-Static Hedging Framework (Phase 3)."""

from __future__ import annotations

import pytest

from spdt.book.book import Trade
from spdt.decomposition.components import BarrierComponent
from spdt.pricing.models.bs import BlackScholes
from spdt.products.catalog import BarrierReverseConvertible
from spdt.products.graph import Leg
from spdt.replication.portfolio import HedgeInstrument, ReplicationPortfolio
from spdt.semistatic import (
    BarrierBookManager,
    BarrierProbabilityEngine,
    PreUnwindOptimizer,
    RecalibrationActionType,
    RecalibrationManager,
    ReplicationMonitor,
)


@pytest.fixture
def model() -> BlackScholes:
    return BlackScholes(spot=100.0, sigma=0.2, r=0.05, q=0.0)


# ---------------------------------------------------------------------------
# Barrier Probability Engine
# ---------------------------------------------------------------------------

class TestBarrierProbabilityEngine:

    def test_p_hit_down_barrier(self, model):
        """Spot = 100, Barrier = 80, Vol = 20%, 1y. P(hit) should be well below 50%."""
        p_hit = BarrierProbabilityEngine.p_hit(
            spot=model.spot,
            barrier=80.0,
            sigma=model.sigma,
            t=1.0,
            r=model.r,
            q=model.q,
            is_down=True,
        )
        assert 0.0 < p_hit < 0.5

    def test_p_hit_certainty(self, model):
        """If spot is already at or below the down barrier, P(hit) = 1.0."""
        p_hit = BarrierProbabilityEngine.p_hit(
            spot=80.0,
            barrier=80.0,
            sigma=model.sigma,
            t=1.0,
            r=model.r,
            q=model.q,
            is_down=True,
        )
        assert p_hit == 1.0

    def test_distance_to_barrier(self, model):
        """Spot 100, Barrier 80. ln(100/80) / (0.2 * 1) = 0.223 / 0.2 = 1.11 stdevs."""
        d = BarrierProbabilityEngine.distance_to_barrier(
            spot=model.spot, barrier=80.0, sigma=model.sigma, t=1.0
        )
        assert abs(d - 1.1157) < 0.01

    def test_terminal_monitoring_probability_is_below_continuous(self, model):
        continuous = BarrierProbabilityEngine.p_hit(
            model.spot, 80.0, model.sigma, 1.0, model.r, model.q, True
        )
        terminal = BarrierProbabilityEngine.p_hit_discrete(
            model.spot, 80.0, model.sigma, (1.0,), model.r, model.q, True,
            n_paths=100_000, seed=4,
        )
        assert terminal < continuous


# ---------------------------------------------------------------------------
# Pre-Unwind Optimizer
# ---------------------------------------------------------------------------

class TestPreUnwindOptimizer:

    def test_unwind_schedule(self):
        assert PreUnwindOptimizer.get_unwind_fraction(0.40) == 0.0
        assert PreUnwindOptimizer.get_unwind_fraction(0.60) == 0.20
        assert PreUnwindOptimizer.get_unwind_fraction(0.80) == 0.50
        assert PreUnwindOptimizer.get_unwind_fraction(0.90) == 0.80
        assert PreUnwindOptimizer.get_unwind_fraction(0.99) == 1.00

    def test_incremental_unwind_recommendation(self):
        # Dummy portfolio with one instrument of weight 100
        portfolio = ReplicationPortfolio(
            instruments=(
                HedgeInstrument(None, 100.0, "vanilla_put", "barrier_static_strip"),
            )
        )

        # At P(KO) = 0.80, target is 50%. We are currently at 0%.
        rec1 = PreUnwindOptimizer.recommend(0.80, portfolio, 0.0)
        assert rec1.unwind_fraction == 0.50
        assert len(rec1.instruments_to_close) == 1
        assert rec1.instruments_to_close[0].weight == -50.0  # unwind half

        # Now spot moves and P(KO) = 0.90, target is 80%. We are currently at 50%.
        rec2 = PreUnwindOptimizer.recommend(0.90, portfolio, 0.50)
        assert abs(rec2.unwind_fraction - 0.30) < 1e-6
        assert abs(rec2.instruments_to_close[0].weight - (-30.0)) < 1e-6  # unwind 30 more

        # Spot retreats, P(KO) drops to 0.60. Target is 20%. We are at 80%.
        # We DO NOT rewind.
        rec3 = PreUnwindOptimizer.recommend(0.60, portfolio, 0.80)
        assert rec3.unwind_fraction == 0.0
        assert len(rec3.instruments_to_close) == 0


# ---------------------------------------------------------------------------
# Recalibration Manager
# ---------------------------------------------------------------------------

class TestRecalibrationManager:

    def test_recalibration_state_machine(self, model):
        monitor = ReplicationMonitor(error_threshold=5.0)
        manager = RecalibrationManager(monitor, p_hit_threshold_unwind=0.85)

        # 1. Normal state: small error, low P(KO)
        # We pass a dummy component without an as_product() to force tracking error to 0.0
        # By setting direction=0, the notional becomes 0 in the test, so PV=0
        comp = BarrierComponent(100, 1.0, "NIFTY", 0, Leg.OPTION, 1.0, 0.5, False, True)
        port = ReplicationPortfolio(())

        action = manager.evaluate(comp, port, model)
        assert action.action_type == RecalibrationActionType.RECOMPUTE_GREEKS

        # 2. Pre-unwind threshold breached
        comp2 = BarrierComponent(100, 1.0, "NIFTY", -1, Leg.OPTION, 1.0, 0.99, False, False)
        # With barrier at 0.99, P(hit) will be very high (> 85%)
        action2 = manager.evaluate(comp2, port, model)
        assert action2.action_type == RecalibrationActionType.PRE_UNWIND

        # A breached knock-in transitions to its live vanilla exposure; it is not unwound.
        knocked_in = BarrierComponent(
            100, 1.0, "NIFTY", -1, Leg.OPTION, 1.0, 0.8, False, True,
            initial_fixing=100.0,
        )
        breached_model = BlackScholes(spot=79.0, sigma=0.2, r=0.05, q=0.0)
        action3 = manager.evaluate(knocked_in, port, breached_model)
        assert action3.action_type == RecalibrationActionType.REBUILD_HEDGE

    def test_barrier_remains_fixed_when_spot_moves(self):
        component = BarrierComponent(
            100, 1.0, "NIFTY", -1, Leg.OPTION, 1.0, 0.8, False, True,
            initial_fixing=100.0,
        )
        near = BlackScholes(spot=82.0, sigma=0.2, r=0.05, q=0.0)
        far = BlackScholes(spot=120.0, sigma=0.2, r=0.05, q=0.0)
        barrier = component.barrier * component.fixing(near.spot)
        p_near = BarrierProbabilityEngine.p_hit(near.spot, barrier, near.sigma, 1, near.r, near.q, True)
        p_far = BarrierProbabilityEngine.p_hit(far.spot, barrier, far.sigma, 1, far.r, far.q, True)
        assert p_near > p_far


# ---------------------------------------------------------------------------
# Barrier Book Manager
# ---------------------------------------------------------------------------

class TestBarrierBookManager:

    def test_barrier_clustering(self, model):
        # Trade 1: Short BRC at 80% knock-in
        brc1 = BarrierReverseConvertible(100, (1.0,), 0.05, 1.0, 0.80)
        t1 = Trade("T1", brc1, direction=1)  # Book holds note long (investor short DI put -> book long DI put)

        # Trade 2: Short BRC at 78% knock-in (should cluster with 80%)
        brc2 = BarrierReverseConvertible(100, (1.0,), 0.05, 1.0, 0.78)
        t2 = Trade("T2", brc2, direction=1)

        # Trade 3: Short BRC at 60% knock-in
        brc3 = BarrierReverseConvertible(100, (1.0,), 0.05, 1.0, 0.60)
        t3 = Trade("T3", brc3, direction=1)

        manager = BarrierBookManager([t1, t2, t3])
        clusters = manager.get_barrier_clusters(model, bin_size=0.05)

        # Should have exactly two clusters: 0.80 (sum of 0.80 and 0.78) and 0.60
        assert len(clusters) == 2

        c_80 = [c for c in clusters if abs(c.barrier_level - 0.80) < 1e-6][0]
        c_60 = [c for c in clusters if abs(c.barrier_level - 0.60) < 1e-6][0]

        # Each BRC has a BarrierComponent with direction -1 and Notional 100
        # Trade direction is +1
        # Net notional = 100 * -1 * 1 = -100
        # 0.80 cluster has two trades = -200
        assert c_80.total_notional == -200.0
        assert c_60.total_notional == -100.0

        # 0.80 cluster should have higher P(KO) than 0.60 cluster
        assert c_80.p_hit > c_60.p_hit
