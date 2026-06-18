"""Pricing engine: drive any DSL product through Monte-Carlo under a model (L4).

The engine is model-agnostic: it asks the product which times it must observe, asks the
model to simulate spots on that grid, evaluates the product's cashflows, and discounts them.
Swapping ``BlackScholes`` for local-vol/Heston/LSV later changes only the ``model`` argument.
Closed-form pricing (the MC benchmark) lives in :mod:`spdt.pricing.analytic`; a unified
dispatch that picks analytic-vs-MC per product is a later addition.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from spdt.products.graph import PathSet, PriceResult, Product, present_value
from spdt.pricing.mc.rng import standard_normals


class PathModel(Protocol):
    """Anything that can simulate spot paths and discount cashflows."""

    def simulate(self, times: NDArray[np.float64], normals: NDArray[np.float64]): ...
    def discount(self, t: float) -> float: ...


def price_mc(
    product: Product,
    model: PathModel,
    *,
    n_paths: int = 100_000,
    antithetic: bool = True,
    seed: int = 0,
    method: str = "pseudo",
) -> PriceResult:
    """Monte-Carlo price of ``product`` under ``model`` with a sampling standard error."""
    grid = np.array((0.0, *sorted(set(product.monitoring_times()))))
    normals = standard_normals(
        n_paths, grid.size - 1, antithetic=antithetic, seed=seed, method=method
    )
    spots = model.simulate(grid, normals)
    paths = PathSet(times=grid, spots=spots)
    cashflows = product.cashflows(paths)
    return present_value(cashflows, model.discount, n_paths)
