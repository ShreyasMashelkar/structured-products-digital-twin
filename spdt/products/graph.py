"""The payoff-DSL core: paths in, dated cashflows out (L3).

A structured note is represented as a **composition of primitives** evaluated against a set
of simulated paths, not a hardcoded payoff formula. Every product implements one method —
``cashflows(paths) -> list[Cashflow]`` — and a product is built by wiring primitives that
each contribute cashflows (see :mod:`spdt.products.primitives` and
:mod:`spdt.products.catalog`). This is what lets "build a Phoenix" become "wire
MemoryCoupon + Autocall + KnockIn".

Pricing is deliberately *not* here: a product emits per-path cashflows at year-fraction
times; the pricing engine (L4) supplies the paths and the discounting. That separation is
what lets the same product price under BS, local-vol or LSV without change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from math import sqrt
from typing import Callable, Union

import numpy as np
from numpy.typing import NDArray

_TIME_TOL = 1e-9


class Leg(str, Enum):
    """Which curve a cashflow discounts on (design doc §2.2, ADR-0002).

    A structured note splits into two economically distinct legs that a real desk discounts
    on *different* curves:

    * ``OPTION`` — the optionality the issuer hedges in the market (the embedded puts/calls).
      Discounted on the **OIS / risk-free** curve, the rate at which the hedge is funded.
    * ``FUNDING`` — the note's bond-like cashflows (principal redemption, fixed coupons). This
      is the issuer's *debt*, discounted on the **issuer funding** curve (OIS + spread).

    Collapsing both onto a single flat rate would misprice the funding-spread economics that
    explain a note's cost decomposition, which is the whole reason the snapshot carries two
    bootstrapped curves.
    """

    OPTION = "option"
    FUNDING = "funding"


@dataclass(frozen=True)
class PathSet:
    """Simulated underlying paths sampled on a shared time grid (single asset for now).

    ``times[0]`` is always 0 (the as-of date) and ``spots[:, 0]`` the initial fixing, so
    barrier/autocall levels are taken relative to ``spots[:, 0]``. Multi-asset paths
    (worst-of) extend ``spots`` with a trailing asset axis in a later slice.
    """

    times: NDArray[np.float64]  # (m+1,), increasing year fractions, times[0] == 0
    spots: NDArray[np.float64]  # (n_paths, m+1)

    @property
    def n_paths(self) -> int:
        return self.spots.shape[0]

    @property
    def initial(self) -> NDArray[np.float64]:
        return self.spots[:, 0]

    def index_of(self, time: float) -> int:
        """Column index of an observation ``time`` on the grid (must be present)."""
        idx = int(np.searchsorted(self.times, time))
        for cand in (idx, idx - 1):
            if 0 <= cand < self.times.size and abs(self.times[cand] - time) <= _TIME_TOL:
                return cand
        raise KeyError(f"time {time} not on the path grid {self.times}")


@dataclass
class Cashflow:
    """A per-path cash amount paid at a single year-fraction ``time``.

    ``leg`` tags which curve the flow discounts on (see :class:`Leg`). It defaults to
    ``OPTION`` so bare option primitives discount on the risk-free curve; notes tag their
    bond-like flows ``FUNDING``. The tag only bites when a :class:`Discounter` is used — a
    plain single-curve discount callable ignores it (backward compatible).
    """

    time: float
    amount: NDArray[np.float64]  # (n_paths,)
    leg: Leg = Leg.OPTION


class Product(ABC):
    """A structured product: a generator of dated, per-path cashflows."""

    @abstractmethod
    def monitoring_times(self) -> tuple[float, ...]:
        """Strictly-positive year fractions the product must observe (e.g. obs dates)."""

    @abstractmethod
    def cashflows(self, paths: PathSet) -> list[Cashflow]:
        """Per-path cashflows generated on ``paths``."""


@dataclass(frozen=True)
class PriceResult:
    """A Monte-Carlo price with its sampling uncertainty."""

    price: float
    std_error: float
    n_paths: int


@dataclass(frozen=True)
class Discounter:
    """Two-curve discounting: routes each cashflow to the curve its :class:`Leg` names.

    Built from a snapshot's bootstrapped curves (``Discounter.from_snapshot``), this is what
    makes the funding spread a real, priced quantity rather than a flat-rate approximation.
    ``ois`` discounts ``OPTION`` legs, ``funding`` discounts ``FUNDING`` legs; both are
    callables mapping a year fraction to a discount factor.
    """

    ois: Callable[[float], float]
    funding: Callable[[float], float]

    def for_leg(self, leg: Leg) -> Callable[[float], float]:
        return self.funding if leg is Leg.FUNDING else self.ois

    @classmethod
    def from_snapshot(cls, snapshot) -> "Discounter":  # noqa: ANN001 (avoid core import cycle)
        """Build a two-curve discounter from a snapshot's OIS and funding curves."""
        return cls(ois=snapshot.ois_curve.df, funding=snapshot.funding_curve.df)


# A discount specification: either a single curve (callable, applied to every leg) or a
# two-curve :class:`Discounter` that routes by leg.
Discount = Union[Callable[[float], float], Discounter]


def present_value(cashflows: list[Cashflow], discount: Discount, n_paths: int) -> PriceResult:
    """Discount per-path cashflows to a PV with a standard error over paths.

    ``discount`` is either a plain ``Callable[[year_fraction], DF]`` (one curve for every
    flow — the simple/back-compatible path) or a :class:`Discounter` that sends each flow to
    the curve named by its leg.
    """
    per_path = np.zeros(n_paths)
    for cf in cashflows:
        d = discount.for_leg(cf.leg) if isinstance(discount, Discounter) else discount
        per_path += d(cf.time) * cf.amount
    price = float(per_path.mean())
    std_error = float(per_path.std(ddof=1) / sqrt(n_paths)) if n_paths > 1 else 0.0
    return PriceResult(price=price, std_error=std_error, n_paths=n_paths)
