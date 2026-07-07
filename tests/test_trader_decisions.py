"""Tests for the Trader Decision Engine."""

from spdt.decisions.engine import Action, TraderDecisionEngine
from spdt.desk.aggregator import DeskRoutingSlip, EndOfDayRiskReport
from spdt.greeks.bump import GreekSet


class TestTraderDecisionEngine:

    def test_no_action_when_within_limits(self):
        engine = TraderDecisionEngine(delta_limit=100.0, vega_limit=100.0, residual_gamma_limit=100.0)

        report = EndOfDayRiskReport(
            total_trades_processed=10,
            net_desk_routing=DeskRoutingSlip(
                delta_1_desk=GreekSet(delta=50.0, gamma=0.0, vega=0.0, rho=0.0),
                vanilla_options_desk=GreekSet(delta=0.0, gamma=0.0, vega=50.0, rho=0.0),
                exotics_desk=GreekSet(delta=0.0, gamma=50.0, vega=0.0, rho=0.0),
                funding_desk=GreekSet(0.0, 0.0, 0.0, 0.0),
            )
        )

        decisions = engine.evaluate_eod_risk(report)
        assert len(decisions) == 1
        assert decisions[0].action == Action.NO_ACTION

    def test_delta_and_residual_gamma_breach(self):
        engine = TraderDecisionEngine(delta_limit=100.0, vega_limit=100.0, residual_gamma_limit=100.0)

        report = EndOfDayRiskReport(
            total_trades_processed=10,
            net_desk_routing=DeskRoutingSlip(
                delta_1_desk=GreekSet(delta=150.0, gamma=0.0, vega=0.0, rho=0.0),
                vanilla_options_desk=GreekSet(delta=0.0, gamma=0.0, vega=50.0, rho=0.0),
                exotics_desk=GreekSet(delta=0.0, gamma=200.0, vega=0.0, rho=0.0),
                funding_desk=GreekSet(0.0, 0.0, 0.0, 0.0),
            )
        )

        decisions = engine.evaluate_eod_risk(report)
        assert len(decisions) == 2

        # Urgency 5 should be first (Rebuild Replication), Urgency 4 second (Delta Hedge)
        assert decisions[0].action == Action.REBUILD_REPLICATION
        assert decisions[0].urgency == 5
        assert decisions[1].action == Action.DELTA_HEDGE
        assert decisions[1].urgency == 4
