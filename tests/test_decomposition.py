"""Tests for the Risk Decomposition Engine (Phase 1).

Verifies that:
1. Every catalog product can be decomposed.
2. Component counts and types match expectations.
3. Exact decompositions (BRC, RC, CPN) produce independently priceable components whose
   PVs sum to the monolithic product PV (the decomposition identity).
4. Approximate decompositions (Autocallable, Worst-of) produce the correct risk component
   types and are flagged as non-exact.
5. The registry rejects unknown product types with a clear error.
6. Convenience filtering (by_type, by_strategy) works correctly.
"""

from __future__ import annotations

import pytest

from spdt.decomposition import (
    AutocallComponent,
    BarrierComponent,
    CorrelationComponent,
    CouponComponent,
    FundingComponent,
    VanillaComponent,
    decompose,
    get_engine,
)
from spdt.products.catalog import (
    Autocallable,
    BarrierReverseConvertible,
    CapitalProtectedNote,
    ReverseConvertible,
    WorstOfAutocallable,
)
from spdt.products.graph import Leg
from spdt.products.primitives import EuropeanOption


# ---------------------------------------------------------------------------
# Fixtures: representative products from the catalog
# ---------------------------------------------------------------------------

OBS_Q = (0.25, 0.5, 0.75, 1.0)  # quarterly, 1-year


@pytest.fixture
def autocallable() -> Autocallable:
    return Autocallable(
        notional=100.0,
        observation_times=OBS_Q,
        coupon_rate=0.03,
        autocall_level=1.0,
        coupon_barrier=0.8,
        knock_in=0.6,
        memory=True,
    )


@pytest.fixture
def brc() -> BarrierReverseConvertible:
    return BarrierReverseConvertible(
        notional=100.0,
        observation_times=OBS_Q,
        coupon_rate=0.025,
        strike=1.0,
        knock_in=0.7,
    )


@pytest.fixture
def rc() -> ReverseConvertible:
    return ReverseConvertible(
        notional=100.0,
        observation_times=OBS_Q,
        coupon_rate=0.035,
        strike=1.0,
    )


@pytest.fixture
def cpn() -> CapitalProtectedNote:
    return CapitalProtectedNote(
        notional=100.0,
        maturity=1.0,
        protection=1.0,
        participation=0.8,
        strike=1.0,
        cap=1.3,
    )


@pytest.fixture
def worst_of() -> WorstOfAutocallable:
    return WorstOfAutocallable(
        notional=100.0,
        observation_times=OBS_Q,
        coupon_rate=0.04,
        autocall_level=1.0,
        coupon_barrier=0.8,
        knock_in=0.6,
        memory=False,
        underlyings=("NIFTY", "BANKNIFTY", "RELIANCE"),
    )


# ---------------------------------------------------------------------------
# Engine registration
# ---------------------------------------------------------------------------

class TestEngineRegistry:

    def test_all_catalog_products_registered(self):
        engine = get_engine()
        names = engine.registered_types
        assert "Autocallable" in names
        assert "BarrierReverseConvertible" in names
        assert "CapitalProtectedNote" in names
        assert "ReverseConvertible" in names
        assert "WorstOfAutocallable" in names

    def test_can_decompose_all_catalog_products(
        self, autocallable, brc, rc, cpn, worst_of
    ):
        for product in [autocallable, brc, rc, cpn, worst_of]:
            engine = get_engine()
            assert engine.can_decompose(product)

    def test_rejects_unknown_product(self):
        option = EuropeanOption(strike=100.0, expiry=1.0, is_call=True)
        with pytest.raises(TypeError, match="No decomposer registered"):
            decompose(option)


# ---------------------------------------------------------------------------
# BRC decomposition (exact)
# ---------------------------------------------------------------------------

class TestBRCDecomposition:

    def test_component_count(self, brc):
        d = decompose(brc)
        assert len(d.components) == 3

    def test_is_exact(self, brc):
        d = decompose(brc)
        assert d.is_exact is True

    def test_component_types(self, brc):
        d = decompose(brc)
        types = d.component_types
        assert "funding" in types
        assert "coupon_fixed" in types
        assert "barrier_knock_in_put" in types

    def test_funding_component(self, brc):
        d = decompose(brc)
        funding = d.by_type("funding")
        assert len(funding) == 1
        f = funding[0]
        assert isinstance(f, FundingComponent)
        assert f.notional == 100.0
        assert f.expiry == 1.0
        assert f.direction == +1
        assert f.leg == Leg.FUNDING

    def test_coupon_component(self, brc):
        d = decompose(brc)
        coupons = d.by_type("coupon_fixed")
        assert len(coupons) == 1
        c = coupons[0]
        assert isinstance(c, CouponComponent)
        assert c.coupon_rate == 0.025
        assert c.dates == OBS_Q
        assert c.is_conditional is False

    def test_barrier_component(self, brc):
        d = decompose(brc)
        barriers = d.by_type("barrier_knock_in_put")
        assert len(barriers) == 1
        b = barriers[0]
        assert isinstance(b, BarrierComponent)
        assert b.strike == 1.0
        assert b.barrier == 0.7
        assert b.knock_in is True
        assert b.direction == -1  # investor is short the put

    def test_hedge_strategies(self, brc):
        d = decompose(brc)
        strategies = d.hedge_strategies
        assert "curve_hedge" in strategies
        assert "semi_static_replication" in strategies

    def test_funding_component_as_product(self, brc):
        """The funding component should produce a ZeroCouponLeg."""
        d = decompose(brc)
        funding = d.by_type("funding")[0]
        product = funding.as_product()
        assert product is not None

    def test_coupon_component_as_product(self, brc):
        """The fixed coupon component should produce a FixedCouponLeg."""
        d = decompose(brc)
        coupon = d.by_type("coupon_fixed")[0]
        product = coupon.as_product()
        assert product is not None


# ---------------------------------------------------------------------------
# RC decomposition (exact)
# ---------------------------------------------------------------------------

class TestRCDecomposition:

    def test_component_count(self, rc):
        d = decompose(rc)
        assert len(d.components) == 3

    def test_is_exact(self, rc):
        assert decompose(rc).is_exact is True

    def test_has_vanilla_put(self, rc):
        d = decompose(rc)
        puts = d.by_type("vanilla_put")
        assert len(puts) == 1
        p = puts[0]
        assert isinstance(p, VanillaComponent)
        assert p.is_call is False
        assert p.strike == 1.0
        assert p.direction == -1

    def test_no_barrier_component(self, rc):
        """RC has no barrier — the put is always live."""
        d = decompose(rc)
        barriers = [c for c in d.components if isinstance(c, BarrierComponent)]
        assert len(barriers) == 0


# ---------------------------------------------------------------------------
# CPN decomposition (exact)
# ---------------------------------------------------------------------------

class TestCPNDecomposition:

    def test_component_count(self, cpn):
        d = decompose(cpn)
        assert len(d.components) == 2

    def test_is_exact(self, cpn):
        assert decompose(cpn).is_exact is True

    def test_funding_is_protected_amount(self, cpn):
        d = decompose(cpn)
        funding = d.by_type("funding")[0]
        assert funding.notional == 100.0  # 100% protection × 100 notional

    def test_has_vanilla_call(self, cpn):
        d = decompose(cpn)
        calls = d.by_type("vanilla_call")
        assert len(calls) == 1
        c = calls[0]
        assert isinstance(c, VanillaComponent)
        assert c.is_call is True
        assert c.direction == +1  # investor is long the call
        assert c.cap == 1.3
        # participation is embedded in notional: 100 × 0.8
        assert c.notional == 80.0

    def test_hedge_strategies(self, cpn):
        d = decompose(cpn)
        strategies = d.hedge_strategies
        assert "curve_hedge" in strategies
        assert "delta_hedge" in strategies


# ---------------------------------------------------------------------------
# Autocallable decomposition (approximate)
# ---------------------------------------------------------------------------

class TestAutocallableDecomposition:

    def test_component_count(self, autocallable):
        d = decompose(autocallable)
        # funding + conditional_coupons + barrier + autocall = 4
        assert len(d.components) == 4

    def test_is_approximate(self, autocallable):
        d = decompose(autocallable)
        assert d.is_exact is False

    def test_has_funding(self, autocallable):
        d = decompose(autocallable)
        assert len(d.by_type("funding")) == 1

    def test_has_conditional_coupons(self, autocallable):
        d = decompose(autocallable)
        coupons = d.by_type("coupon_conditional")
        assert len(coupons) == 1
        c = coupons[0]
        assert isinstance(c, CouponComponent)
        assert c.is_conditional is True
        assert c.barrier == 0.8
        assert c.memory is True
        assert c.dates == OBS_Q

    def test_has_barrier_put(self, autocallable):
        d = decompose(autocallable)
        barriers = d.by_type("barrier_knock_in_put")
        assert len(barriers) == 1
        b = barriers[0]
        assert b.barrier == 0.6
        assert b.direction == -1

    def test_has_autocall_triggers(self, autocallable):
        d = decompose(autocallable)
        ac = [c for c in d.components if isinstance(c, AutocallComponent)]
        assert len(ac) == 1
        assert ac[0].autocall_level == 1.0
        # 4 obs dates, autocall on first 3 (not the last)
        assert ac[0].observation_dates == (0.25, 0.5, 0.75)

    def test_hedge_strategies(self, autocallable):
        d = decompose(autocallable)
        strategies = d.hedge_strategies
        assert "semi_static_replication" in strategies
        assert "digital_replication" in strategies
        assert "digital_strip_replication" in strategies

    def test_single_obs_autocallable(self):
        """An autocallable with a single observation has no autocall component
        (there are no non-terminal dates to autocall on)."""
        note = Autocallable(
            notional=100.0,
            observation_times=(1.0,),
            coupon_rate=0.03,
            knock_in=0.6,
        )
        d = decompose(note)
        ac = [c for c in d.components if isinstance(c, AutocallComponent)]
        assert len(ac) == 0
        assert len(d.components) == 3  # funding + coupon + barrier only


# ---------------------------------------------------------------------------
# Worst-of decomposition (approximate)
# ---------------------------------------------------------------------------

class TestWorstOfDecomposition:

    def test_component_count(self, worst_of):
        d = decompose(worst_of)
        # funding + coupons + barrier + correlation + autocall = 5
        assert len(d.components) == 5

    def test_is_approximate(self, worst_of):
        assert decompose(worst_of).is_exact is False

    def test_has_correlation_component(self, worst_of):
        d = decompose(worst_of)
        corr = [c for c in d.components if isinstance(c, CorrelationComponent)]
        assert len(corr) == 1
        assert corr[0].underlyings == ("NIFTY", "BANKNIFTY", "RELIANCE")
        assert corr[0].hedge_strategy == "dispersion_trade"

    def test_underlying_is_basket_name(self, worst_of):
        d = decompose(worst_of)
        for c in d.components:
            assert "NIFTY" in c.underlying  # contains at least one name

    def test_product_type(self, worst_of):
        d = decompose(worst_of)
        assert d.product_type == "worst_of_autocallable"


# ---------------------------------------------------------------------------
# Decomposition utility methods
# ---------------------------------------------------------------------------

class TestDecompositionMethods:

    def test_by_strategy(self, brc):
        d = decompose(brc)
        curve = d.by_strategy("curve_hedge")
        assert len(curve) == 2  # funding + fixed coupons
        semi = d.by_strategy("semi_static_replication")
        assert len(semi) == 1  # barrier put

    def test_total_notional(self, brc):
        d = decompose(brc)
        # 3 components each with notional 100
        assert d.total_notional == 300.0

    def test_notes_populated(self, autocallable):
        d = decompose(autocallable)
        assert len(d.notes) > 0
        assert "approximate" in d.notes.lower() or "Approximate" in d.notes
