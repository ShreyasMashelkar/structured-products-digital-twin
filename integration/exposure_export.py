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
    from spdt.products.catalog import Autocallable
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


def autocallable_exposure(
    note: "Autocallable", model: "BlackScholes",
    ois_curve: "SpdtCurveAsOIS", funding_curve: "SpdtCurveAsOIS", *,
    time_grid: NDArray[np.float64], n_paths: int = 20_000, seed: int = 0,
    counterparty_id: str = "CP-0", netting_set: str = "default", trade_id: str = "AC-0",
) -> ExposurePackage:
    """Mark-to-future exposure of an autocallable by Longstaff–Schwartz continuation regression.

    A path-dependent note cannot use the simple pathwise-realised value (the ``max`` in EE sits
    *outside* the conditional expectation, so a single realisation biases it up — Jensen). Instead,
    at each profile time we regress the realised PV of *future* cashflows on a polynomial of the
    state to estimate the **continuation value** ``E[V_t | S_t]`` per path. Paths that have already
    autocalled have no later cashflows and are zeroed — which is exactly why the EE profile **rises
    then collapses** as observation dates cull the live notes.
    """
    from spdt.pricing.mc.rng import standard_normals
    from spdt.products.graph import PathSet

    obs = np.asarray(note.observation_times, dtype=float)
    profile = np.asarray(time_grid, dtype=float)
    grid = np.unique(np.concatenate([[0.0], profile, obs]))
    spots = model.simulate(grid, standard_normals(n_paths, grid.size - 1, seed=seed))
    paths = PathSet(times=grid, spots=spots)
    cfs = note.cashflows(paths)
    s0 = paths.initial if note.initial_fixing is None else np.full(n_paths, note.initial_fixing)

    # When each path autocalls (∞ ⇒ never): used to zero the mark once the note has redeemed.
    autocall_t = np.full(n_paths, np.inf)
    alive = np.ones(n_paths, dtype=bool)
    for t in obs[:-1]:
        spot = spots[:, paths.index_of(float(t))]
        called = alive & (spot >= note.autocall_level * s0)
        autocall_t[called] = t
        alive &= ~called

    npv = np.zeros((n_paths, profile.size))
    for j, ti in enumerate(profile):
        d_ti = funding_curve.df(float(ti))
        future = np.zeros(n_paths)  # realised PV (to ti) of cashflows strictly after ti
        for cf in cfs:
            if cf.time > ti + 1e-9:
                future += np.asarray(cf.amount, dtype=float) * (funding_curve.df(cf.time) / d_ti)
        live = autocall_t > ti + 1e-9
        m = spots[:, paths.index_of(float(ti))] / s0  # moneyness state
        basis = np.column_stack([np.ones(n_paths), m, m * m])
        if live.sum() > 16:
            coef, *_ = np.linalg.lstsq(basis[live], future[live], rcond=None)
            cont = basis @ coef
        else:
            cont = future
        npv[:, j] = np.where(live, cont, 0.0)

    return ExposurePackage(
        trade_id=trade_id, counterparty_id=counterparty_id, netting_set=netting_set,
        time_grid=profile, npv_paths=npv, ois_curve=ois_curve, funding_curve=funding_curve,
    )
