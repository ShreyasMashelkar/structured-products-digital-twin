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
from math import sqrt
from typing import Callable

import numpy as np
from numpy.typing import NDArray

_TIME_TOL = 1e-9


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
    """A per-path cash amount paid at a single year-fraction ``time``."""

    time: float
    amount: NDArray[np.float64]  # (n_paths,)


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


def present_value(
    cashflows: list[Cashflow], discount: Callable[[float], float], n_paths: int
) -> PriceResult:
    """Discount per-path cashflows to a PV with a standard error over paths."""
    per_path = np.zeros(n_paths)
    for cf in cashflows:
        per_path += discount(cf.time) * cf.amount
    price = float(per_path.mean())
    std_error = float(per_path.std(ddof=1) / sqrt(n_paths)) if n_paths > 1 else 0.0
    return PriceResult(price=price, std_error=std_error, n_paths=n_paths)
