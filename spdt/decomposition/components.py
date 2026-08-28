"""Risk component taxonomy: the typed building blocks every product decomposes into.

An institutional exotics desk does not hedge a structured product as a single opaque object.
It first **decomposes** the product into hedgeable risk components — barrier, digital, vanilla,
forward, funding — each of which maps to a known hedging strategy and a set of liquid
instruments. This module defines that component vocabulary.

Every component is a frozen dataclass carrying:

* Economic terms (strike, barrier, expiry, notional, direction)
* Its discount leg (:class:`~spdt.products.graph.Leg` — OPTION or FUNDING)
* A ``hedge_strategy`` hint for the replication engine (Phase 2)
* An optional ``as_product()`` method that returns a standalone :class:`Product` primitive
  for independent pricing — enabling the *decomposition identity* check (sum of component PVs
  ≈ product PV) wherever the decomposition is exact.

The taxonomy is deliberately open: new component types (FX, dividend, credit) are added as
plain subclasses without touching the engine or the strategies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from spdt.products.graph import Leg, Product, ScaledProduct


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RiskComponent(ABC):
    """A single hedgeable risk component extracted from a structured product."""

    notional: float
    expiry: float
    underlying: str
    direction: int  # +1 long, -1 short (from the *issuer's* perspective)
    leg: Leg  # which curve this cashflow discounts on
    initial_fixing: float | None = field(default=None, kw_only=True)

    @property
    @abstractmethod
    def component_type(self) -> str:
        """Machine-readable type tag (e.g. ``"barrier"``, ``"digital"``)."""

    @property
    @abstractmethod
    def hedge_strategy(self) -> str:
        """Hint for the replication engine: how this component is typically hedged."""

    def as_product(self, reference_spot: float | None = None) -> Product | None:
        """Return a standalone :class:`Product` for independent pricing, if possible.

        Returns ``None`` when the component is descriptive only (e.g. an approximate
        decomposition of a path-dependent feature like an autocall trigger).
        """
        return None

    def fixing(self, reference_spot: float | None = None) -> float:
        """Return the immutable inception fixing used to turn relative levels into prices."""
        fixing = self.initial_fixing if self.initial_fixing is not None else reference_spot
        if fixing is None or fixing <= 0.0:
            raise ValueError("A positive initial_fixing or reference_spot is required")
        return fixing


# ---------------------------------------------------------------------------
# Funding / bond components
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FundingComponent(RiskComponent):
    """Par redemption at maturity — the zero-coupon bond leg.

    This is the issuer's debt: notional returned at maturity, discounted on the funding curve.
    """

    @property
    def component_type(self) -> str:
        return "funding"

    @property
    def hedge_strategy(self) -> str:
        return "curve_hedge"

    def as_product(self, reference_spot: float | None = None) -> Product | None:
        from spdt.products.legs import ZeroCouponLeg
        return ZeroCouponLeg(notional=self.notional * self.direction, maturity=self.expiry)


@dataclass(frozen=True)
class CouponComponent(RiskComponent):
    """Fixed or conditional coupons on a schedule.

    ``is_conditional`` distinguishes unconditional BRC-style fixed coupons from the digital
    coupons of a Phoenix (which pay only if spot > coupon_barrier). For conditional coupons,
    ``barrier`` carries the trigger level as a fraction of the initial fixing.
    """

    coupon_rate: float
    dates: tuple[float, ...]
    is_conditional: bool = False
    barrier: float | None = None  # coupon barrier (fraction of S₀), if conditional
    memory: bool = False  # Phoenix memory feature

    @property
    def component_type(self) -> str:
        return "coupon_conditional" if self.is_conditional else "coupon_fixed"

    @property
    def hedge_strategy(self) -> str:
        return "digital_replication" if self.is_conditional else "curve_hedge"

    def as_product(self, reference_spot: float | None = None) -> Product | None:
        if not self.is_conditional:
            from spdt.products.legs import FixedCouponLeg
            return FixedCouponLeg(
                notional=self.notional * self.direction,
                rate=self.coupon_rate,
                dates=self.dates,
            )
        return None  # conditional coupons are path-dependent


# ---------------------------------------------------------------------------
# Optionality components
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BarrierComponent(RiskComponent):
    """A knock-in or knock-out barrier option — the core risk of most structured notes.

    Carries the barrier level and the effective strike of the embedded option. For a BRC's
    down-and-in put, ``strike`` is the put strike and ``barrier`` is the knock-in level, both
    as fractions of the initial fixing.
    """

    strike: float  # as a fraction of S₀
    barrier: float  # as a fraction of S₀
    is_call: bool = False
    knock_in: bool = True  # True = DI, False = DO
    monitoring: tuple[float, ...] = ()  # barrier monitoring dates
    # Some barriers describe risk that another component already hedges. An autocallable's
    # early-redemption level is one: it is emitted so the barrier book, hit-probability engine
    # and pre-unwind scheduler can see it, while AutocallComponent carries the hedging. A
    # shark-fin's knock-out is another: the participation call beside it is already a
    # VanillaComponent. Replicating those barriers as well would hedge the same risk twice, so
    # they are marked descriptive and the replication engine skips them.
    descriptive_only: bool = False

    @property
    def component_type(self) -> str:
        kind = "knock_in" if self.knock_in else "knock_out"
        side = "call" if self.is_call else "put"
        return f"barrier_{kind}_{side}"

    @property
    def hedge_strategy(self) -> str:
        return "none" if self.descriptive_only else "semi_static_replication"

    def as_product(self, reference_spot: float | None = None) -> Product | None:
        from spdt.products.primitives import DownBarrierPut
        if not self.is_call:
            fixing = self.fixing(reference_spot)
            return ScaledProduct(
                DownBarrierPut(
                    strike=self.strike * fixing,
                    barrier=self.barrier * fixing,
                    expiry=self.expiry,
                    monitoring=self.monitoring or (self.expiry,),
                    knock_in=self.knock_in,
                ),
                self.notional * self.direction / fixing,
            )
        return None  # up-barrier call not yet in the primitives


@dataclass(frozen=True)
class VanillaComponent(RiskComponent):
    """A plain vanilla European call or put — delta-hedgeable.

    Used for the participation call in a capital-protected note and the always-live put in a
    reverse convertible.
    """

    strike: float  # as a fraction of S₀
    is_call: bool = True
    cap: float | None = None  # for capped calls, the cap level (fraction of S₀)

    @property
    def component_type(self) -> str:
        return "vanilla_call" if self.is_call else "vanilla_put"

    @property
    def hedge_strategy(self) -> str:
        return "delta_hedge"

    def as_product(self, reference_spot: float | None = None) -> Product | None:
        from spdt.products.primitives import EuropeanOption

        fixing = self.fixing(reference_spot)
        quantity = self.notional * self.direction / fixing
        base = EuropeanOption(self.strike * fixing, self.expiry, self.is_call)
        if self.cap is None:
            return ScaledProduct(base, quantity)
        if not self.is_call or self.cap <= self.strike:
            raise ValueError("A cap is only supported for calls with cap > strike")
        from spdt.products.legs import CompositeNote
        return CompositeNote(
            (
                ScaledProduct(base, quantity),
                ScaledProduct(EuropeanOption(self.cap * fixing, self.expiry, True), -quantity),
            )
        )


@dataclass(frozen=True)
class DigitalComponent(RiskComponent):
    """A cash-or-nothing digital — hedged via call-spread or put-spread replication.

    Used for autocall triggers (digital on spot ≥ autocall_level, paying par) and
    conditional coupons decomposed individually.
    """

    strike: float  # digital trigger level (fraction of S₀)
    payout: float  # cash amount paid if triggered
    is_call: bool = True  # True = pays if spot > strike

    @property
    def component_type(self) -> str:
        return "digital_call" if self.is_call else "digital_put"

    @property
    def hedge_strategy(self) -> str:
        return "digital_replication"

    def as_product(self, reference_spot: float | None = None) -> Product | None:
        from spdt.products.primitives import CashOrNothingDigital
        fixing = self.fixing(reference_spot)
        return CashOrNothingDigital(
            strike=self.strike * fixing,
            expiry=self.expiry,
            payout=self.payout * self.notional * self.direction,
            is_call=self.is_call,
        )


@dataclass(frozen=True)
class ForwardComponent(RiskComponent):
    """A linear (delta-one) forward exposure — hedged with futures or the underlying."""

    forward_price: float

    @property
    def component_type(self) -> str:
        return "forward"

    @property
    def hedge_strategy(self) -> str:
        return "futures_hedge"


# ---------------------------------------------------------------------------
# Multi-asset / higher-order components
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CorrelationComponent(RiskComponent):
    """Correlation exposure from a worst-of basket.

    The investor is short dispersion: lower correlation widens the worst-performer distribution
    and increases the probability of knock-in. This component captures the pure correlation
    risk that cannot be hedged with single-name instruments.
    """

    underlyings: tuple[str, ...]
    correlation: float  # current estimated correlation

    @property
    def component_type(self) -> str:
        return "correlation"

    @property
    def hedge_strategy(self) -> str:
        return "dispersion_trade"


@dataclass(frozen=True)
class AutocallComponent(RiskComponent):
    """An autocall trigger: early redemption at par if spot ≥ autocall_level on an obs date.

    Economically, this is a digital option on each observation date that kills the note.
    It is path-dependent (later triggers are conditional on earlier ones *not* firing), so
    ``as_product()`` returns ``None`` — the component is descriptive for risk decomposition,
    not independently priceable.
    """

    autocall_level: float  # as a fraction of S₀
    observation_dates: tuple[float, ...]  # dates on which autocall can trigger

    @property
    def component_type(self) -> str:
        return "autocall"

    @property
    def hedge_strategy(self) -> str:
        return "digital_strip_replication"
