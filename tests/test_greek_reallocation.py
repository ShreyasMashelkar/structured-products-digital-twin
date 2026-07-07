"""Tests for the Greek Reallocation Engine (Phase 4)."""

from __future__ import annotations

import pytest

from spdt.decomposition.components import BarrierComponent
from spdt.greeks.bump import GreekSet
from spdt.pricing.models.bs import BlackScholes
from spdt.products.graph import Leg
from spdt.products.primitives import EuropeanOption
from spdt.replication.portfolio import HedgeInstrument, ReplicationPortfolio
from spdt.greeks.reallocation import GreekReallocator
from spdt.greeks.residual import ResidualGreekCalculator
from spdt.greeks.routing import DeskRouter


@pytest.fixture
def model() -> BlackScholes:
    return BlackScholes(spot=100.0, sigma=0.2, r=0.05, q=0.0)


class TestGreekReallocator:

    def test_aggregation_and_reallocation(self):
        instr1 = HedgeInstrument(None, 10.0, "vanilla_put", "barrier_base")
        instr2 = HedgeInstrument(None, -5.0, "vanilla_put", "barrier_static_strip")

        instrument_greeks = {
            instr1: GreekSet(delta=-0.5, gamma=0.01, vega=0.2, rho=0.0),
            instr2: GreekSet(delta=-0.2, gamma=0.005, vega=0.1, rho=0.0),
        }

        # Total portfolio:
        # Delta = 10 * -0.5 + -5 * -0.2 = -5.0 + 1.0 = -4.0
        # Gamma = 10 * 0.01 + -5 * 0.005 = 0.1 - 0.025 = 0.075
        # Vega = 10 * 0.2 + -5 * 0.1 = 2.0 - 0.5 = 1.5

        hedge_greeks = GreekReallocator.aggregate_hedge_greeks(instrument_greeks)
        assert abs(hedge_greeks.delta - (-4.0)) < 1e-6
        assert abs(hedge_greeks.gamma - 0.075) < 1e-6
        assert abs(hedge_greeks.vega - 1.5) < 1e-6

        # Suppose the full product actually has Delta -3.8 and Gamma 0.1
        total_greeks = GreekSet(delta=-3.8, gamma=0.1, vega=1.6, rho=0.0)

        reallocated = GreekReallocator.reallocate(total_greeks, instrument_greeks)

        res = reallocated.residual_exotic_greeks
        assert abs(res.delta - 0.2) < 1e-6    # -3.8 - (-4.0)
        assert abs(res.gamma - 0.025) < 1e-6  # 0.1 - 0.075
        assert abs(res.vega - 0.1) < 1e-6     # 1.6 - 1.5


class TestResidualGreekCalculator:

    def test_residual_calculation(self, model):
        calc = ResidualGreekCalculator(rel_spot_bump=0.01)

        # Let's test a simple Vanilla component exactly hedged by a Vanilla option.
        # The residual should be perfectly 0.

        comp = BarrierComponent(100.0, 1.0, "NIFTY", 1, Leg.OPTION, 1.0, 0.0, False, False)
        # ^ Barrier of 0, knock_in=False makes it effectively a vanilla Put.

        put = EuropeanOption(strike=100.0, expiry=1.0, is_call=False)
        instr = HedgeInstrument(put, 1.0, "vanilla_put", "pass_through")
        port = ReplicationPortfolio((instr,))

        reallocated = calc.calculate_residual(comp, port, model, n_paths=10000, seed=42)

        # MC noise might cause tiny discrepancies, but should be close to 0
        res = reallocated.residual_exotic_greeks
        assert abs(res.delta) < 0.5
        assert abs(res.gamma) < 0.5


class TestDeskRouter:

    def test_desk_routing(self):
        total = GreekSet(delta=100.0, gamma=5.0, vega=20.0, rho=10.0)
        hedge = GreekSet(delta=90.0, gamma=4.0, vega=18.0, rho=8.0)

        reallocated = GreekReallocator.reallocate(total, {
            HedgeInstrument(None, 1.0, "dummy", "dummy"): hedge
        })

        slip = DeskRouter.route(reallocated)

        assert slip.delta_1_desk.delta == 90.0
        assert slip.delta_1_desk.gamma == 0.0

        assert slip.vanilla_options_desk.delta == 0.0
        assert slip.vanilla_options_desk.gamma == 4.0
        assert slip.vanilla_options_desk.vega == 18.0

        assert slip.exotics_desk.delta == 10.0
        assert slip.exotics_desk.gamma == 1.0
        assert slip.exotics_desk.vega == 2.0

        assert slip.funding_desk.rho == 8.0
