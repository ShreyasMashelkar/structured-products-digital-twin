"""Tests for the Portfolio Hedging Engine."""

from spdt.greeks.bump import GreekSet
from spdt.portfolio.netting import NettingEngine


class TestPortfolioNetting:

    def test_perfect_offset(self):
        # Two trades perfectly offsetting each other
        gross = GreekSet(delta=200.0, gamma=100.0, vega=20.0, rho=0.0)
        net = GreekSet(delta=0.0, gamma=0.0, vega=0.0, rho=0.0)

        engine = NettingEngine()
        benefit = engine.compute_netting_benefit(gross, net)

        assert benefit.delta_netting_pct == 1.0
        assert benefit.gamma_netting_pct == 1.0
        assert benefit.vega_netting_pct == 1.0

    def test_partial_offset(self):
        gross = GreekSet(delta=200.0, gamma=100.0, vega=20.0, rho=0.0)
        net = GreekSet(delta=100.0, gamma=50.0, vega=0.0, rho=0.0)

        engine = NettingEngine()
        benefit = engine.compute_netting_benefit(gross, net)

        assert benefit.delta_netting_pct == 0.5
        assert benefit.gamma_netting_pct == 0.5
        assert benefit.vega_netting_pct == 1.0
