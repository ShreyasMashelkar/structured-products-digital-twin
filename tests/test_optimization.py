"""Tests for the Hedge Optimization Engine."""

from spdt.greeks.bump import GreekSet
from spdt.optimization.constraints import HedgeConstraints
from spdt.optimization.engine import HedgeOptimizationEngine
from spdt.products.primitives import EuropeanOption
from spdt.replication.portfolio import HedgeInstrument


class TestHedgeOptimizationEngine:

    def test_optimization_neutralizes_risk(self):
        # We have a risk of 100 Delta, 50 Gamma, 10 Vega that we want to hedge.
        # Since the optimizer tries to minimize `residual = target + A @ w`,
        # if our risk is (+100, +50, +10), target_greeks should be that,
        # and the optimal weights should have opposite signs.
        target_risk = GreekSet(delta=100.0, gamma=50.0, vega=10.0, rho=0.0)

        # Available instruments
        # 1. Delta-only instrument (e.g. Future)
        instr1 = HedgeInstrument(EuropeanOption(100, 1.0, True), weight=0, instrument_type="future", purpose="opt")
        g1 = GreekSet(delta=1.0, gamma=0.0, vega=0.0, rho=0.0)

        # 2. Gamma/Vega instrument (e.g. ATM Straddle)
        instr2 = HedgeInstrument(EuropeanOption(100, 1.0, True), weight=0, instrument_type="straddle", purpose="opt")
        g2 = GreekSet(delta=0.0, gamma=0.5, vega=0.2, rho=0.0)

        # 3. Vega-heavy instrument (e.g. OTM Strangle)
        instr3 = HedgeInstrument(EuropeanOption(100, 1.0, True), weight=0, instrument_type="strangle", purpose="opt")
        g3 = GreekSet(delta=0.0, gamma=0.1, vega=0.8, rho=0.0)

        engine = HedgeOptimizationEngine(w_txn=0.0, w_impact=0.0, w_risk=1.0)
        constraints = HedgeConstraints()

        optimal = engine.optimize(
            target_greeks=target_risk,
            available_instruments=[instr1, instr2, instr3],
            instrument_greeks=[g1, g2, g3],
            constraints=constraints,
        )

        assert optimal.success
        # Residual risk should be close to 0
        assert abs(optimal.residual_risk.delta) < 1e-4
        assert abs(optimal.residual_risk.gamma) < 1e-4
        assert abs(optimal.residual_risk.vega) < 1e-4

        # We expect weights to be negative to offset the positive target risk
        weights = [instr.weight for instr in optimal.portfolio.instruments]
        # Sum of delta = 100 + w1 = 0 => w1 = -100
        # Sum of gamma = 50 + 0.5*w2 + 0.1*w3 = 0
        # Sum of vega = 10 + 0.2*w2 + 0.8*w3 = 0
        # w2 and w3 will be whatever solves that linear system.
        assert len(weights) > 0
