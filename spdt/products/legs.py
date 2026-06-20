"""Composable payoff legs: notes wired from primitives, not hardcoded (L3).

The catalog products (:mod:`spdt.products.catalog`) write their cashflows out in one method —
fast to read, but it hides the design doc's central claim that a structured note *is a
portfolio of optionality*. This module makes that literal: each economic leg is its own
:class:`~spdt.products.graph.Product`, and a :class:`CompositeNote` simply sums the cashflows
of its legs on shared paths. "Build a BRC" becomes "wire a zero-coupon bond + fixed coupons −
a down-and-in put", and the composed note prices identically to the monolithic one (see the
tests). This is the DSL the README advertises, available additively without disturbing the
working catalog classes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from spdt.products.graph import Cashflow, Leg, PathSet, Product


@dataclass(frozen=True)
class CompositeNote(Product):
    """A note as the sum of its legs: cashflows are the concatenation of each leg's cashflows."""

    legs: tuple[Product, ...]

    def monitoring_times(self) -> tuple[float, ...]:
        times: set[float] = set()
        for leg in self.legs:
            times.update(leg.monitoring_times())
        return tuple(sorted(times))

    def cashflows(self, paths: PathSet) -> list[Cashflow]:
        out: list[Cashflow] = []
        for leg in self.legs:
            out.extend(leg.cashflows(paths))
        return out


@dataclass(frozen=True)
class ZeroCouponLeg(Product):
    """Par redemption at maturity — the bond leg (funding curve)."""

    notional: float
    maturity: float

    def monitoring_times(self) -> tuple[float, ...]:
        return (self.maturity,)

    def cashflows(self, paths: PathSet) -> list[Cashflow]:
        return [Cashflow(self.maturity, np.full(paths.n_paths, float(self.notional)), Leg.FUNDING)]


@dataclass(frozen=True)
class FixedCouponLeg(Product):
    """Unconditional fixed coupons on a schedule (funding curve)."""

    notional: float
    rate: float
    dates: tuple[float, ...]

    def monitoring_times(self) -> tuple[float, ...]:
        return self.dates

    def cashflows(self, paths: PathSet) -> list[Cashflow]:
        amt = self.rate * self.notional
        return [Cashflow(t, np.full(paths.n_paths, amt), Leg.FUNDING) for t in self.dates]


@dataclass(frozen=True)
class ShortDownInPutLeg(Product):
    """Short a down-and-in put struck at ``strike``·S₀, knocking in at ``knock_in``·S₀.

    ``knock_in=None`` makes the put always live (a plain short put). Negative cashflow on the
    option curve — the optionality the investor sold and the issuer hedges.
    """

    notional: float
    strike: float
    maturity: float
    monitoring: tuple[float, ...]
    knock_in: float | None = None

    def monitoring_times(self) -> tuple[float, ...]:
        return tuple(sorted(set(self.monitoring) | {self.maturity}))

    def cashflows(self, paths: PathSet) -> list[Cashflow]:
        s0 = paths.initial
        s0_col = np.reshape(s0, (-1, 1))
        s_t = paths.spots[:, paths.index_of(self.maturity)]
        put = np.maximum(self.strike - s_t / s0, 0.0)
        if self.knock_in is not None:
            cols = [paths.index_of(t) for t in sorted(set(self.monitoring))]
            breached = (paths.spots[:, cols] <= self.knock_in * s0_col).any(axis=1)
            put = np.where(breached, put, 0.0)
        return [Cashflow(self.maturity, -self.notional * put, Leg.OPTION)]


@dataclass(frozen=True)
class ParticipationCallLeg(Product):
    """Long ``participation`` of the underlying's upside above ``strike``·S₀, optionally capped."""

    notional: float
    participation: float
    strike: float
    maturity: float
    cap: float | None = None

    def monitoring_times(self) -> tuple[float, ...]:
        return (self.maturity,)

    def cashflows(self, paths: PathSet) -> list[Cashflow]:
        ret = paths.spots[:, paths.index_of(self.maturity)] / paths.initial
        upside = np.maximum(ret - self.strike, 0.0)
        if self.cap is not None:
            upside = np.minimum(upside, self.cap - self.strike)
        return [Cashflow(self.maturity, self.notional * self.participation * upside, Leg.OPTION)]


def brc_from_legs(
    notional: float,
    observation_times: tuple[float, ...],
    coupon_rate: float,
    *,
    strike: float = 1.0,
    knock_in: float = 0.7,
) -> CompositeNote:
    """A barrier reverse convertible wired from primitives — equals the monolithic catalog one."""
    maturity = observation_times[-1]
    return CompositeNote(
        legs=(
            ZeroCouponLeg(notional, maturity),
            FixedCouponLeg(notional, coupon_rate, observation_times),
            ShortDownInPutLeg(notional, strike, maturity, observation_times, knock_in=knock_in),
        )
    )


def capital_protected_from_legs(
    notional: float,
    maturity: float,
    *,
    protection: float = 1.0,
    participation: float = 1.0,
    strike: float = 1.0,
    cap: float | None = None,
) -> CompositeNote:
    """A capital-protected note wired from a zero-coupon bond + a participation call."""
    return CompositeNote(
        legs=(
            ZeroCouponLeg(notional * protection, maturity),
            ParticipationCallLeg(notional, participation, strike, maturity, cap=cap),
        )
    )
