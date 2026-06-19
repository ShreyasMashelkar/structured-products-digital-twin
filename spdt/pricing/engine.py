"""Pricing engine: drive any DSL product through Monte-Carlo under a model (L4).

The engine is model-agnostic: it asks the product which times it must observe, asks the
model to simulate spots on that grid, evaluates the product's cashflows, and discounts them.
Swapping ``BlackScholes`` for local-vol/Heston/LSV later changes only the ``model`` argument.
Closed-form pricing (the MC benchmark) lives in :mod:`spdt.pricing.analytic`; a unified
dispatch that picks analytic-vs-MC per product is a later addition.
"""

from __future__ import annotations

from math import exp
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from spdt.products.catalog import Autocallable
from spdt.products.graph import PathSet, PriceResult, Product, present_value
from spdt.pricing.mc.paths import correlated_gbm_paths
from spdt.pricing.mc.rng import standard_normals


class PathModel(Protocol):
    """Anything that can simulate spot paths and discount cashflows."""

    def simulate(self, times: NDArray[np.float64], normals: NDArray[np.float64]): ...
    def discount(self, t: float) -> float: ...


def _simulation_grid(monitoring: tuple[float, ...], steps_per_year: int | None) -> NDArray:
    """Time grid for simulation: observation dates, optionally refined for path-dependent SDEs.

    Black-Scholes steps exactly between any dates, so it needs only the observation grid. A
    local-vol/stochastic-vol Euler scheme needs fine sub-steps; ``steps_per_year`` inserts a
    regular mesh while keeping every observation date exactly on the grid.
    """
    obs = sorted(set(monitoring))
    if steps_per_year is None:
        return np.array([0.0, *obs])
    n = max(1, int(np.ceil(obs[-1] * steps_per_year)))
    mesh = np.linspace(0.0, obs[-1], n + 1)
    return np.array(sorted(set([0.0, *mesh.tolist(), *obs])))


def price_mc(
    product: Product,
    model: PathModel,
    *,
    n_paths: int = 100_000,
    antithetic: bool = True,
    seed: int = 0,
    method: str = "pseudo",
    steps_per_year: int | None = None,
) -> PriceResult:
    """Monte-Carlo price of ``product`` under ``model`` with a sampling standard error."""
    grid = _simulation_grid(product.monitoring_times(), steps_per_year)
    normals = standard_normals(
        n_paths, grid.size - 1, antithetic=antithetic, seed=seed, method=method
    )
    spots = model.simulate(grid, normals)
    paths = PathSet(times=grid, spots=spots)
    cashflows = product.cashflows(paths)
    return present_value(cashflows, model.discount, n_paths)


def price_worst_of_autocallable(
    note: Autocallable,
    spots0: NDArray,
    vols: NDArray,
    corr: NDArray,
    *,
    r: float,
    q: float = 0.0,
    n_paths: int = 100_000,
    seed: int = 0,
) -> PriceResult:
    """Price a worst-of autocallable on a correlated basket, reusing the single-name DSL.

    Each asset is simulated as correlated GBM; the worst-of **basket level** at each date is
    ``minₐ Sₐ(t)/Sₐ(0)`` (so it starts at 1.0), and the ordinary :class:`Autocallable` payoff
    runs on that basket — the note's barriers (fractions of the initial fixing) become barriers
    on the worst performer. The note must have ``initial_fixing=None`` so the basket's 1.0 start
    is the reference.
    """
    grid = _simulation_grid(note.monitoring_times(), None)
    rng = np.random.default_rng(seed)
    asset_paths = correlated_gbm_paths(
        spots0, vols, corr, grid, r=r, q=q, n_paths=n_paths, rng=rng
    )
    basket = (asset_paths / np.asarray(spots0, dtype=float)).min(axis=2)
    paths = PathSet(times=grid, spots=basket)
    cashflows = note.cashflows(paths)
    return present_value(cashflows, lambda t: exp(-r * t), n_paths)
