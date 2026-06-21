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
