"""Exposure export — SPDT *produces* an ``ExposurePackage`` (ADR-0007, Phase 3).

Mark-to-future: the position's NPV on every simulated path at every future time. For a European
this is exact (the Black-Scholes value of the remaining option along each path); path-dependent
notes (BRC → autocallable → worst-of) build on this loop with conditional repricing and come in
later increments. The vectorised BSM here matches the XVA engine's ``bsm_price`` convention
(continuous dividend ``q``, flat short rate read off the OIS curve) so the two implementations
agree elementwise — the cross-check that proves SPDT's exposure feeds the XVA stack faithfully.
"""

from __future__ import annotations

from math import exp, sqrt
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray
from scipy.special import ndtr

from integration.exposure_package import ExposurePackage

if TYPE_CHECKING:
    from integration.curve_adapter import SpdtCurveAsOIS
    from spdt.pricing.models import BlackScholes
    from spdt.products.primitives import EuropeanOption


def _bsm(
    spot: NDArray[np.float64], k: float, tau: float, r: float, q: float, sigma: float, is_call: bool
) -> NDArray[np.float64]:
    """Vectorised Black-Scholes-Merton value over a slice of spots (matches XVA ``bsm_price``)."""
    if tau <= 0.0:
        return np.maximum(spot - k, 0.0) if is_call else np.maximum(k - spot, 0.0)
    srt = sigma * sqrt(tau)
    d1 = (np.log(spot / k) + (r - q + 0.5 * sigma * sigma) * tau) / srt
    d2 = d1 - srt
    if is_call:
        return spot * exp(-q * tau) * ndtr(d1) - k * exp(-r * tau) * ndtr(d2)
    return k * exp(-r * tau) * ndtr(-d2) - spot * exp(-q * tau) * ndtr(-d1)


def mark_to_future_european(
    option: "EuropeanOption", *, r: float, q: float, sigma: float,
    spot_paths: NDArray[np.float64], time_grid: NDArray[np.float64], units: float = 1.0,
) -> NDArray[np.float64]:
    """NPV cube ``(n_paths, n_times)`` — the European repriced along each path at remaining tenor."""
    k, t_exp, is_call = option.strike, option.expiry, option.is_call
    npv = np.zeros_like(spot_paths)
    for i, t in enumerate(time_grid):
        npv[:, i] = units * _bsm(spot_paths[:, i], k, max(t_exp - t, 0.0), r, q, sigma, is_call)
    return npv


def european_exposure(
    option: "EuropeanOption", model: "BlackScholes",
    ois_curve: "SpdtCurveAsOIS", funding_curve: "SpdtCurveAsOIS", *,
    time_grid: NDArray[np.float64], n_paths: int = 20_000, seed: int = 0,
    counterparty_id: str = "CP-0", netting_set: str = "default",
    trade_id: str = "EUR-0", units: float = 1.0,
) -> ExposurePackage:
    """Simulate SPDT GBM paths, mark the European to future, and package the exposure for XVA."""
    from spdt.pricing.mc.rng import standard_normals

    times = np.asarray(time_grid, dtype=float)
    normals = standard_normals(n_paths, times.size - 1, seed=seed)
    spots = model.simulate(times, normals)
    r = ois_curve.zero_rate(option.expiry)
    npv = mark_to_future_european(
        option, r=r, q=model.q, sigma=model.sigma, spot_paths=spots, time_grid=times, units=units
    )
    return ExposurePackage(
        trade_id=trade_id, counterparty_id=counterparty_id, netting_set=netting_set,
        time_grid=times, npv_paths=npv, ois_curve=ois_curve, funding_curve=funding_curve,
    )


def _regression_exposure(
    cfs: list, spots: NDArray[np.float64], paths, s0: NDArray[np.float64],
    profile: NDArray[np.float64], ois_curve: "SpdtCurveAsOIS", funding_curve: "SpdtCurveAsOIS",
) -> NDArray[np.float64]:
    """Longstaff–Schwartz continuation-value cube for a single-asset note.

    EE puts a ``max`` *outside* the conditional expectation, so a single pathwise realisation
    biases it up (Jensen). At each profile time we regress the realised PV of *future* cashflows
    on a polynomial of the state — spot moneyness and the running minimum (which carries any
    barrier/knock-in status) — to estimate ``E[V_t | F_t]`` per path. A path whose last non-zero
    cashflow has already occurred has redeemed and is zeroed; that culling is why an autocallable's
    EE collapses on each autocall date while a non-callable note's does not.
    """
    from spdt.products.graph import Leg

    n_paths = spots.shape[0]
    ratio = spots / s0[:, None]
    running_min = np.minimum.accumulate(ratio, axis=1)
    # Last non-zero cashflow time per path → generic "has the note redeemed yet?" mask.
    last_cf = np.zeros(n_paths)
    for cf in cfs:
        nz = np.asarray(cf.amount, dtype=float) != 0.0
        last_cf = np.where(nz & (cf.time > last_cf), cf.time, last_cf)

    npv = np.zeros((n_paths, profile.size))
    for j, ti in enumerate(profile):
        idx = paths.index_of(float(ti))
        # Leg-aware discount of each future cashflow back to ti (funding leg on the issuer curve,
        # option leg on OIS) — the two-curve framework carried into the exposure.
        future = np.zeros(n_paths)
        for cf in cfs:
            if cf.time > ti + 1e-9:
                curve = funding_curve if cf.leg is Leg.FUNDING else ois_curve
                future += np.asarray(cf.amount, dtype=float) * (curve.df(cf.time) / curve.df(float(ti)))
        live = last_cf > ti + 1e-9
        m = ratio[:, idx]
        rmin = running_min[:, idx]
        basis = np.column_stack([np.ones(n_paths), m, m * m, rmin, rmin * m])
        if live.sum() > 16:
            coef, *_ = np.linalg.lstsq(basis[live], future[live], rcond=None)
            cont = basis @ coef
        else:
            cont = future
        npv[:, j] = np.where(live, cont, 0.0)
    return npv


def note_exposure(
    note, model: "BlackScholes",
    ois_curve: "SpdtCurveAsOIS", funding_curve: "SpdtCurveAsOIS", *,
    time_grid: NDArray[np.float64], n_paths: int = 20_000, seed: int = 0,
    counterparty_id: str = "CP-0", netting_set: str = "default", trade_id: str = "NOTE-0",
) -> ExposurePackage:
    """Mark-to-future exposure of any single-asset SPDT note (autocallable, BRC, RC, CPN).

    Works for callable and non-callable, barrier and barrier-free notes alike: it reads the note's
    own ``cashflows`` and infers redemption and barrier state generically (see
    :func:`_regression_exposure`).
    """
    from spdt.pricing.mc.rng import standard_normals
    from spdt.products.graph import PathSet

    obs = np.asarray(note.monitoring_times(), dtype=float)
    profile = np.asarray(time_grid, dtype=float)
    grid = np.unique(np.concatenate([[0.0], profile, obs]))
    spots = model.simulate(grid, standard_normals(n_paths, grid.size - 1, seed=seed))
    paths = PathSet(times=grid, spots=spots)
    cfs = note.cashflows(paths)
    fixing = getattr(note, "initial_fixing", None)
    s0 = paths.initial if fixing is None else np.full(n_paths, fixing)

    npv = _regression_exposure(cfs, spots, paths, s0, profile, ois_curve, funding_curve)
    return ExposurePackage(
        trade_id=trade_id, counterparty_id=counterparty_id, netting_set=netting_set,
        time_grid=profile, npv_paths=npv, ois_curve=ois_curve, funding_curve=funding_curve,
    )


# The autocallable is just a callable single-asset note; keep the explicit name for callers.
autocallable_exposure = note_exposure


def worst_of_exposure(
    product, spots0: NDArray[np.float64], vols: NDArray[np.float64], corr: NDArray[np.float64],
    ois_curve: "SpdtCurveAsOIS", funding_curve: "SpdtCurveAsOIS", *,
    time_grid: NDArray[np.float64], r: float, q: float = 0.0,
    n_paths: int = 20_000, seed: int = 0,
    counterparty_id: str = "CP-0", netting_set: str = "default", trade_id: str = "WO-0",
) -> ExposurePackage:
    """Mark-to-future exposure of a worst-of autocallable on a correlated basket.

    Reuses the single-asset regression engine with the **worst performer's level** as the state
    (``minₐ Sₐ/Sₐ₀``, which starts at 1.0): the basket is what the note's barriers and autocall key
    off, so it is the right one-dimensional state to regress the continuation value on. Cashflows
    are taken from the full multi-asset paths; the EE still collapses as the basket autocalls.
    """
    from spdt.pricing.mc.paths import correlated_gbm_paths
    from spdt.products.graph import PathSet

    obs = np.asarray(product.monitoring_times(), dtype=float)
    profile = np.asarray(time_grid, dtype=float)
    grid = np.unique(np.concatenate([[0.0], profile, obs]))
    rng = np.random.default_rng(seed)
    asset_paths = correlated_gbm_paths(spots0, vols, corr, grid, r=r, q=q, n_paths=n_paths, rng=rng)
    paths = PathSet(times=grid, spots=asset_paths)
    cfs = product.cashflows(paths)
    basket = (asset_paths / np.asarray(spots0, dtype=float)).min(axis=2)  # worst performer, starts 1
    s0 = np.ones(n_paths)

    npv = _regression_exposure(cfs, basket, paths, s0, profile, ois_curve, funding_curve)
    return ExposurePackage(
        trade_id=trade_id, counterparty_id=counterparty_id, netting_set=netting_set,
        time_grid=profile, npv_paths=npv, ois_curve=ois_curve, funding_curve=funding_curve,
    )
