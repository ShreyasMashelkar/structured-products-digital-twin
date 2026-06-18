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

from spdt.products.graph import Cashflow, PathSet, Product
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
        alive = np.ones(paths.n_paths, dtype=bool)
        missed = np.zeros(paths.n_paths)
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
                cfs.append(Cashflow(t, coupon))

            if i < last:
                called = alive & (spot >= self.autocall_level * s0)
                if called.any():
                    cfs.append(Cashflow(t, np.where(called, n, 0.0)))
                alive = alive & ~called
            else:
                ki_breached = spot <= self.knock_in * s0
                principal = np.where(
                    alive, np.where(ki_breached, n * spot / s0, n), 0.0
                )
                cfs.append(Cashflow(t, principal))

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
