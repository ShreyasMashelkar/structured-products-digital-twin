"""Payoff primitives: the small grammar products are composed from (L3).

Each primitive is a :class:`~spdt.products.graph.Product` in its own right — vanilla and
digital Europeans plus a single knock barrier — so they double as standalone test
instruments (priced against closed forms) and as building blocks for the catalog. Barriers
are **discretely monitored** on the supplied schedule; the continuity correction for the
continuous-monitoring limit (Broadie–Glasserman–Kou) is a later refinement.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from spdt.products.graph import Cashflow, PathSet, Product


def _vanilla_payoff(spot: NDArray[np.float64], strike: float, is_call: bool) -> NDArray[np.float64]:
    return np.maximum(spot - strike, 0.0) if is_call else np.maximum(strike - spot, 0.0)


@dataclass(frozen=True)
class EuropeanOption(Product):
    """Plain vanilla European call/put paying intrinsic value at expiry."""

    strike: float
    expiry: float  # year fraction
    is_call: bool = True

    def monitoring_times(self) -> tuple[float, ...]:
        return (self.expiry,)

    def cashflows(self, paths: PathSet) -> list[Cashflow]:
        s_t = paths.spots[:, paths.index_of(self.expiry)]
        return [Cashflow(self.expiry, _vanilla_payoff(s_t, self.strike, self.is_call))]


@dataclass(frozen=True)
class CashOrNothingDigital(Product):
    """Cash-or-nothing digital paying ``payout`` if in the money at expiry."""

    strike: float
    expiry: float
    payout: float = 1.0
    is_call: bool = True

    def monitoring_times(self) -> tuple[float, ...]:
        return (self.expiry,)

    def cashflows(self, paths: PathSet) -> list[Cashflow]:
        s_t = paths.spots[:, paths.index_of(self.expiry)]
        hit = (s_t > self.strike) if self.is_call else (s_t < self.strike)
        return [Cashflow(self.expiry, self.payout * hit.astype(float))]


@dataclass(frozen=True)
class DownBarrierPut(Product):
    """Down-and-in / down-and-out European put, discretely monitored.

    ``knock_in=True`` gives the down-and-in put (pays the put only if the barrier is breached
    on a monitoring date); ``False`` gives the down-and-out. By construction
    ``down-and-in + down-and-out = vanilla put`` on every path — the parity used to validate
    the Monte-Carlo engine without coding a fragile barrier closed form.
    """

    strike: float
    barrier: float
    expiry: float
    monitoring: tuple[float, ...]
    knock_in: bool = True

    def monitoring_times(self) -> tuple[float, ...]:
        return tuple(sorted(set(self.monitoring) | {self.expiry}))

    def cashflows(self, paths: PathSet) -> list[Cashflow]:
        cols = [paths.index_of(t) for t in self.monitoring_times()]
        breached = (paths.spots[:, cols] <= self.barrier).any(axis=1)
        s_t = paths.spots[:, paths.index_of(self.expiry)]
        put = _vanilla_payoff(s_t, self.strike, is_call=False)
        active = breached if self.knock_in else ~breached
        return [Cashflow(self.expiry, put * active.astype(float))]
