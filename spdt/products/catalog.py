"""Catalog: real structured notes composed from primitives (L3).

The flagship is the single-underlying **autocallable** (Phoenix when memory coupons are on),
which is exactly the composition the design doc calls out: an observation schedule wiring
together an *autocall* trigger, a (memory) *coupon*, and a terminal *knock-in* that puts the
investor long the downside. Decomposed, the investor is short optionality (the KI put) in
exchange for an enhanced conditional coupon — which is why this single product exercises the
whole pricing/Greeks/risk stack.

Levels (autocall / coupon / knock-in) are expressed as fractions of the initial fixing
``S₀ = spots[:, 0]``, so the same note reprices on any snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from spdt.products.graph import Cashflow, Leg, PathSet, Product
from spdt.products.termsheet import TermSheet


@dataclass(frozen=True)
class Autocallable(Product):
    """Single-underlying autocallable / Phoenix note.

    Parameters are fractions of the initial fixing. At each observation date a conditional
    coupon pays if spot ≥ ``coupon_barrier``; before maturity the note redeems at par early
    if spot ≥ ``autocall_level``. If it survives to maturity, principal is returned at par
    unless ``knock_in`` is breached at maturity, in which case the investor takes the spot
    return (``S_T / S₀``). With ``memory`` on, missed coupons accrue and pay on the next
    coupon-qualifying date (the Phoenix feature).
    """

    notional: float
    observation_times: tuple[float, ...]
    coupon_rate: float  # per-observation coupon, as a fraction of notional
    autocall_level: float = 1.0
    coupon_barrier: float = 0.8
    knock_in: float = 0.6
    memory: bool = False
    initial_fixing: float | None = None  # struck reference; None ⇒ float with the path start

    def monitoring_times(self) -> tuple[float, ...]:
        return self.observation_times

    def cashflows(self, paths: PathSet) -> list[Cashflow]:
        # Levels are struck at inception. With a fixed initial_fixing, bumping spot moves the
        # path relative to fixed barriers (a non-trivial delta); left None the fixing floats
        # with the path start, which is scale-invariant (zero delta) but identical in price.
        s0 = paths.initial if self.initial_fixing is None else self.initial_fixing
        n = self.notional
        alive: NDArray[np.bool_] = np.ones(paths.n_paths, dtype=bool)
        missed: NDArray[np.float64] = np.zeros(paths.n_paths)
        last = len(self.observation_times) - 1
        cfs: list[Cashflow] = []

        for i, t in enumerate(self.observation_times):
            spot = paths.spots[:, paths.index_of(t)]

            pays_coupon = alive & (spot >= self.coupon_barrier * s0)
            if self.memory:
                coupon = np.where(pays_coupon, (missed + 1.0) * self.coupon_rate * n, 0.0)
                missed = np.where(
                    pays_coupon, 0.0, np.where(alive & ~pays_coupon, missed + 1.0, missed)
                )
            else:
                coupon = np.where(pays_coupon, self.coupon_rate * n, 0.0)
            if coupon.any():
                cfs.append(Cashflow(t, coupon, Leg.FUNDING))

            if i < last:
                called = alive & (spot >= self.autocall_level * s0)
                if called.any():
                    cfs.append(Cashflow(t, np.where(called, n, 0.0), Leg.FUNDING))
                alive = alive & ~called
            else:
                ki_breached = spot <= self.knock_in * s0
                principal = np.where(
                    alive, np.where(ki_breached, n * spot / s0, n), 0.0
                )
                # The whole note is the issuer's liability: coupons, early redemption and final
                # principal (including the embedded knock-in downside, which only pays if the
                # note survives to maturity) all discount on the funding curve.
                cfs.append(Cashflow(t, principal, Leg.FUNDING))

        return cfs

    @classmethod
    def from_termsheet(cls, ts: TermSheet, *, initial_fixing: float | None = None) -> Autocallable:
        """Build the priceable product from its economic terms."""
        p = ts.params
        return cls(
            notional=ts.notional,
            observation_times=ts.observation_times,
            coupon_rate=p["coupon_rate"],
            autocall_level=p.get("autocall_level", 1.0),
            coupon_barrier=p.get("coupon_barrier", 0.8),
            knock_in=p.get("knock_in", 0.6),
            memory=p.get("memory", False),
            initial_fixing=initial_fixing,
        )


@dataclass(frozen=True)
class BarrierReverseConvertible(Product):
    """Barrier reverse convertible (BRC) — design doc §3.

    Decomposed exactly as the doc states::

        BRC = ZeroCouponNote(par) + FixedCoupon(c) − DownAndIn_Put(strike, barrier)

    The investor receives a high *fixed* (unconditional) coupon and par back at maturity —
    *unless* the underlying has breached the down ``knock_in`` barrier on a monitoring date,
    in which case principal is reduced by the in-the-money amount of a put struck at
    ``strike``. So the investor is **short** a down-and-in put and the issuer is long it; the
    high coupon is the premium for that sold optionality. Levels are fractions of the initial
    fixing ``S₀`` so the same note reprices on any snapshot.
    """

    notional: float
    observation_times: tuple[float, ...]  # coupon dates; the last is maturity
    coupon_rate: float  # per-observation fixed coupon, as a fraction of notional
    strike: float = 1.0  # put strike, as a fraction of S₀ (par)
    knock_in: float = 0.7  # down-barrier, as a fraction of S₀
    barrier_monitoring: tuple[float, ...] | None = None  # default: the observation dates
    initial_fixing: float | None = None

    def monitoring_times(self) -> tuple[float, ...]:
        mon = self.barrier_monitoring or self.observation_times
        return tuple(sorted(set(self.observation_times) | set(mon)))

    def cashflows(self, paths: PathSet) -> list[Cashflow]:
        s0 = paths.initial if self.initial_fixing is None else self.initial_fixing
        n = self.notional
        cfs: list[Cashflow] = []

        # Fixed coupon on every observation date (unconditional — that's the "reverse
        # convertible": the investor is paid up front for the downside they've sold). These are
        # the issuer's debt service ⇒ funding leg.
        for t in self.observation_times:
            cfs.append(Cashflow(t, np.full(paths.n_paths, self.coupon_rate * n), Leg.FUNDING))

        # Down-and-in put: breached if spot ≤ knock_in·S₀ on any monitoring date.
        mon = self.barrier_monitoring or self.observation_times
        cols = [paths.index_of(t) for t in sorted(set(mon))]
        s0_col = np.reshape(s0, (-1, 1))  # (n,1) per-path fixing, or (1,1) when struck
        breached = (paths.spots[:, cols] <= self.knock_in * s0_col).any(axis=1)

        maturity = self.observation_times[-1]
        s_t = paths.spots[:, paths.index_of(maturity)]
        # Split the two legs explicitly (the doc's decomposition): par redemption is the bond
        # ⇒ funding curve; the short down-and-in put is hedged optionality ⇒ OIS curve.
        put = np.maximum(self.strike - s_t / s0, 0.0)
        cfs.append(Cashflow(maturity, np.full(paths.n_paths, float(n)), Leg.FUNDING))
        cfs.append(Cashflow(maturity, -n * np.where(breached, put, 0.0), Leg.OPTION))
        return cfs

    @classmethod
    def from_termsheet(
        cls, ts: TermSheet, *, initial_fixing: float | None = None
    ) -> BarrierReverseConvertible:
        p = ts.params
        bm = p.get("barrier_monitoring")
        return cls(
            notional=ts.notional,
            observation_times=ts.observation_times,
            coupon_rate=p["coupon_rate"],
            strike=p.get("strike", 1.0),
            knock_in=p.get("knock_in", 0.7),
            barrier_monitoring=tuple(bm) if bm is not None else None,
            initial_fixing=initial_fixing,
        )


@dataclass(frozen=True)
class ReverseConvertible(Product):
    """Reverse convertible (RC) — design doc §3, the BRC's barrier-free sibling.

    ::

        RC = ZeroCouponNote(par) + FixedCoupon(c) − vanilla Put(strike)

    Identical to a :class:`BarrierReverseConvertible` except the investor's short put is
    *always* live — there is no knock-in barrier protecting the downside — so the coupon is
    correspondingly higher. Useful as the limiting case (``knock_in → ∞``) and the simplest
    "yield-enhancement on a single name" note. Levels are fractions of the initial fixing.
    """

    notional: float
    observation_times: tuple[float, ...]  # coupon dates; the last is maturity
    coupon_rate: float
    strike: float = 1.0  # put strike, as a fraction of S₀
    initial_fixing: float | None = None

    def monitoring_times(self) -> tuple[float, ...]:
        return self.observation_times

    def cashflows(self, paths: PathSet) -> list[Cashflow]:
        s0 = paths.initial if self.initial_fixing is None else self.initial_fixing
        n = self.notional
        cfs: list[Cashflow] = [
            Cashflow(t, np.full(paths.n_paths, self.coupon_rate * n), Leg.FUNDING)
            for t in self.observation_times
        ]
        maturity = self.observation_times[-1]
        s_t = paths.spots[:, paths.index_of(maturity)]
        put = np.maximum(self.strike - s_t / s0, 0.0)  # short a vanilla put, always live
        cfs.append(Cashflow(maturity, np.full(paths.n_paths, float(n)), Leg.FUNDING))
        cfs.append(Cashflow(maturity, -n * put, Leg.OPTION))
        return cfs

    @classmethod
    def from_termsheet(
        cls, ts: TermSheet, *, initial_fixing: float | None = None
    ) -> ReverseConvertible:
        p = ts.params
        return cls(
            notional=ts.notional,
            observation_times=ts.observation_times,
            coupon_rate=p["coupon_rate"],
            strike=p.get("strike", 1.0),
            initial_fixing=initial_fixing,
        )


@dataclass(frozen=True)
class CapitalProtectedNote(Product):
    """Capital-protected note (CPN) — design doc §3, the structurer's "protection + upside".

    Decomposed as::

        CPN = ZeroCouponNote(protection) + participation · Call(strike, cap)

    At maturity the investor is guaranteed ``protection`` of notional back (e.g. 1.0 = 100%
    capital protected) plus ``participation`` of the underlying's upside above ``strike``,
    optionally capped at ``cap``. The investor is **long** a call (financed by giving up the
    coupon that the zero-coupon bond would otherwise have paid). Levels are fractions of the
    initial fixing ``S₀``.
    """

    notional: float
    maturity: float
    protection: float = 1.0  # fraction of notional returned at maturity
    participation: float = 1.0  # upside participation rate
    strike: float = 1.0  # call strike, as a fraction of S₀
    cap: float | None = None  # max underlying return participated in (fraction of S₀); None ⇒ uncapped

    def monitoring_times(self) -> tuple[float, ...]:
        return (self.maturity,)

    def cashflows(self, paths: PathSet) -> list[Cashflow]:
        s0 = paths.initial
        n = self.notional
        ret = paths.spots[:, paths.index_of(self.maturity)] / s0
        upside = np.maximum(ret - self.strike, 0.0)
        if self.cap is not None:
            upside = np.minimum(upside, self.cap - self.strike)
        # Two legs (the doc's decomposition): the protected principal is the zero-coupon bond
        # ⇒ funding curve; the participation call is hedged optionality ⇒ OIS curve.
        return [
            Cashflow(self.maturity, np.full(paths.n_paths, self.protection * n), Leg.FUNDING),
            Cashflow(self.maturity, n * self.participation * upside, Leg.OPTION),
        ]

    @classmethod
    def from_termsheet(cls, ts: TermSheet) -> CapitalProtectedNote:
        p = ts.params
        return cls(
            notional=ts.notional,
            maturity=ts.maturity,
            protection=p.get("protection", 1.0),
            participation=p.get("participation", 1.0),
            strike=p.get("strike", 1.0),
            cap=p.get("cap"),
        )


@dataclass(frozen=True)
class WorstOfAutocallable(Product):
    """Worst-of autocallable on a correlated basket — the desk's correlation-selling workhorse.

    The payoff is the single-name :class:`Autocallable` run on the **worst performer** of the
    basket: at each observation the basket level is ``minₐ Sₐ(t)/Kₐ`` (struck to 1.0 at
    inception). Selling the worst-of lets the desk pay a *higher* coupon than any single name,
    because correlation widens the dispersion the investor is short — which is exactly why
    worst-of notes are a large share of real structured-note issuance. Multi-asset: ``cashflows``
    consumes a 3-D ``(paths, times, assets)`` :class:`PathSet` (see
    :func:`spdt.pricing.engine.price_worst_of`); the correlation matrix is a first-class,
    shockable risk factor (unlike a single-name note, this one actually *uses* correlation).
    """

    notional: float
    observation_times: tuple[float, ...]
    coupon_rate: float
    autocall_level: float = 1.0
    coupon_barrier: float = 0.8
    knock_in: float = 0.6
    memory: bool = False
    underlyings: tuple[str, ...] = ()
    initial_fixings: tuple[float, ...] | None = None  # struck per-asset references; None ⇒ float

    def monitoring_times(self) -> tuple[float, ...]:
        return self.observation_times

    def cashflows(self, paths: PathSet) -> list[Cashflow]:
        s = paths.spots  # (n_paths, n_times, n_assets)
        if self.initial_fixings is None:
            ref = s[:, 0:1, :]  # struck at the path start ⇒ scale-invariant (zero delta)
        else:
            ref = np.asarray(self.initial_fixings, dtype=float).reshape(1, 1, -1)
        basket = (s / ref).min(axis=2)  # worst performer, struck to 1.0 at inception
        # Barriers are fixed at 1.0 (not floated to the basket's start) so that bumping spot
        # against fixed per-asset fixings produces a genuine basket delta.
        inner = Autocallable(
            self.notional, self.observation_times, self.coupon_rate, self.autocall_level,
            self.coupon_barrier, self.knock_in, self.memory, initial_fixing=1.0,
        )
        return inner.cashflows(PathSet(times=paths.times, spots=basket))
