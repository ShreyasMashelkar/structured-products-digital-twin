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

from spdt.products.catalog import Autocallable, WorstOfAutocallable
from spdt.products.graph import Discount, PathSet, PriceResult, Product, present_value
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
    knots: set[float] = {0.0, *obs}
    knots.update(float(x) for x in mesh)
    return np.array(sorted(knots))


def price_mc(
    product: Product,
    model: PathModel,
    *,
    n_paths: int = 100_000,
    antithetic: bool = True,
    seed: int = 0,
    method: str = "pseudo",
    steps_per_year: int | None = None,
    discount: Discount | None = None,
) -> PriceResult:
    """Monte-Carlo price of ``product`` under ``model`` with a sampling standard error.

    ``discount`` overrides the discounting: pass a :class:`~spdt.products.graph.Discounter`
    to discount the note's funding leg on the issuer curve and its option leg on OIS. When
    omitted it falls back to the model's own flat ``discount`` (single curve, every leg).
    """
    grid = _simulation_grid(product.monitoring_times(), steps_per_year)
    normals = standard_normals(
        n_paths, grid.size - 1, antithetic=antithetic, seed=seed, method=method
    )
    spots = model.simulate(grid, normals)
    paths = PathSet(times=grid, spots=spots)
    cashflows = product.cashflows(paths)
    return present_value(cashflows, discount or model.discount, n_paths)


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


def price_worst_of(
    product: WorstOfAutocallable,
    spots0: NDArray,
    vols: NDArray,
    corr: NDArray,
    *,
    r: float,
    q: float = 0.0,
    n_paths: int = 100_000,
    seed: int = 0,
) -> PriceResult:
    """Price a first-class :class:`WorstOfAutocallable` on correlated GBM paths.

    ``spots0`` is the current per-asset spot (the simulation start); the note's own
    ``initial_fixings`` are the *struck* references, so bumping ``spots0`` against fixed
    fixings yields a real basket delta. ``corr`` is the (PSD-repaired) correlation matrix.
    """
    grid = _simulation_grid(product.monitoring_times(), None)
    rng = np.random.default_rng(seed)
    asset_paths = correlated_gbm_paths(spots0, vols, corr, grid, r=r, q=q, n_paths=n_paths, rng=rng)
    paths = PathSet(times=grid, spots=asset_paths)
    return present_value(product.cashflows(paths), lambda t: exp(-r * t), n_paths)


def worst_of_greeks(
    product: WorstOfAutocallable,
    spots0: NDArray,
    vols: NDArray,
    corr: NDArray,
    *,
    r: float,
    q: float = 0.0,
    n_paths: int = 40_000,
    seed: int = 0,
) -> dict[str, float]:
    """Parallel basket delta/gamma/vega and a correlation delta, by CRN central bumps."""
    s0 = np.asarray(spots0, dtype=float)
    v0 = np.asarray(vols, dtype=float)
    base = price_worst_of(product, s0, v0, corr, r=r, q=q, n_paths=n_paths, seed=seed).price

    def pv(spots=s0, vs=v0, c=corr):
        return price_worst_of(product, spots, vs, c, r=r, q=q, n_paths=n_paths, seed=seed).price

    hs = 0.01  # +1% parallel spot bump
    up_s = pv(spots=s0 * (1 + hs))
    dn_s = pv(spots=s0 * (1 - hs))
    up_v = pv(vs=v0 + 0.01)  # one-sided vega vs base keeps it cheap
    # Correlation delta: nudge every off-diagonal toward 1 by 5pts (kept PSD for small bump).
    n = corr.shape[0]
    bumped = np.array(corr, dtype=float)
    off = ~np.eye(n, dtype=bool)
    bumped[off] = np.clip(bumped[off] + 0.05, -0.99, 0.99)
    corr_up = pv(c=bumped)
    return {
        "delta": (up_s - dn_s) / (2 * hs),  # ∂PV per +1.00 (i.e. per 100%); /100 for per-1%
        "gamma": (up_s - 2 * base + dn_s) / (hs * hs),
        "vega": (up_v - base) / 0.01,
        "corr_delta": (corr_up - base) / 0.05,
        "pv": base,
    }
