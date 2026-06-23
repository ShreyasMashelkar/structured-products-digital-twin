"""Black-76 pricing and implied-vol inversion of option settlement prices (L1).

The single most valuable thing the data layer does: the NSE F&O bhavcopy gives a daily
*settlement price* for every option contract. Combined with the underlying close and a
discount curve we invert Black-Scholes per contract to recover **implied vol per
(strike, expiry)** for every historical day — a genuine historical IV surface, for free.

We price on the **forward** (Black-76): ``F = S·exp((r−q)·T)`` and a discount factor ``D``
absorb the rate and dividend, so this module needs neither spot nor rates directly — just
the forward and the discount that the snapshot's OIS curve already provides. That keeps the
inversion model-agnostic to how the forward was built.

Inversion uses **Newton** on vega (quadratic convergence in the liquid belly) and falls
back to **Brent** on the wings, where vega → 0 and Newton steps blow up. We invert to IV
rather than storing prices so the surface layer (L2) is insensitive to later spot/rate moves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import erf, exp, log, pi, sqrt

from scipy.optimize import brentq

from spdt.core.types import Curve, year_fraction
from spdt.data.ingest import RawMarketData

_SQRT_2PI = sqrt(2.0 * pi)
_VOL_LOWER, _VOL_UPPER = 1e-6, 5.0  # search bracket for implied vol (0.0001% .. 500%)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / _SQRT_2PI


def bs_price(
    forward: float, strike: float, tau: float, sigma: float, discount: float, is_call: bool
) -> float:
    """Black-76 price of a European option given the forward and discount factor.

    Handles the degenerate ``sigma·√tau → 0`` case by returning discounted intrinsic value.
    """
    if tau <= 0.0 or sigma <= 0.0:
        intrinsic = max(forward - strike, 0.0) if is_call else max(strike - forward, 0.0)
        return discount * intrinsic
    vol = sigma * sqrt(tau)
    d1 = (log(forward / strike) + 0.5 * vol * vol) / vol
    d2 = d1 - vol
    if is_call:
        return discount * (forward * _norm_cdf(d1) - strike * _norm_cdf(d2))
    return discount * (strike * _norm_cdf(-d2) - forward * _norm_cdf(-d1))


def bs_vega(forward: float, strike: float, tau: float, sigma: float, discount: float) -> float:
    """Vega ``∂Price/∂σ`` (per unit vol, not per %), identical for calls and puts."""
    if tau <= 0.0 or sigma <= 0.0:
        return 0.0
    vol = sigma * sqrt(tau)
    d1 = (log(forward / strike) + 0.5 * vol * vol) / vol
    return discount * forward * sqrt(tau) * _norm_pdf(d1)


def implied_vol(
    price: float,
    forward: float,
    strike: float,
    tau: float,
    discount: float,
    is_call: bool,
    *,
    tol: float = 1e-9,
    max_iter: int = 100,
) -> float:
    """Invert ``price`` to a Black-76 implied volatility.

    Raises ``ValueError`` if the price violates the no-arbitrage bounds (so it cannot
    correspond to any non-negative vol) — e.g. a stale/crossed settlement print.
    """
    if tau <= 0.0:
        raise ValueError("cannot invert implied vol at or after expiry (tau <= 0)")

    # No-arbitrage bounds: discounted intrinsic ≤ price ≤ discounted forward/strike.
    intrinsic = discount * (max(forward - strike, 0.0) if is_call else max(strike - forward, 0.0))
    upper = discount * (forward if is_call else strike)
    if price < intrinsic - tol or price > upper + tol:
        raise ValueError(f"price {price} outside no-arbitrage bounds [{intrinsic}, {upper}]")

    # Newton from an at-the-money-ish seed; quadratic where vega is healthy.
    sigma = 0.2
    for _ in range(max_iter):
        diff = bs_price(forward, strike, tau, sigma, discount, is_call) - price
        if abs(diff) < tol:
            return sigma
        vega = bs_vega(forward, strike, tau, sigma, discount)
        if vega < 1e-12:
            break  # vega collapsed (deep wing) — hand off to Brent
        sigma -= diff / vega
        if not (_VOL_LOWER < sigma < _VOL_UPPER):
            break  # left the sensible bracket — hand off to Brent

    # Brent fallback: robust, derivative-free, guaranteed to bracket a sign change.
    def objective(s: float) -> float:
        return bs_price(forward, strike, tau, s, discount, is_call) - price

    try:
        return brentq(objective, _VOL_LOWER, _VOL_UPPER, xtol=tol, maxiter=max_iter)
    except ValueError as exc:  # no sign change in bracket
        raise ValueError(f"implied vol did not converge for strike {strike}") from exc


@dataclass(frozen=True)
class IVPoint:
    """One inverted implied-vol observation, the raw input to surface calibration (L2)."""

    expiry: date
    strike: float
    is_call: bool
    log_moneyness: float  # k = log(K/F)
    tau: float  # ACT/365F year fraction to expiry
    implied_vol: float


def invert_chain(
    raw: RawMarketData,
    ois_curve: Curve,
    *,
    moneyness_band: float | None = None,
    iv_bounds: tuple[float, float] | None = None,
) -> list[IVPoint]:
    """Invert every option settlement print in ``raw`` to an :class:`IVPoint`.

    The forward and discount come from the snapshot's OIS curve and the raw dividend yield:
    ``F = S·exp((r−q)·T)`` with ``r`` the OIS zero to expiry. Quotes that fail the
    no-arbitrage bounds (stale/crossed settlements) are skipped rather than aborting the day.

    Two optional **liquidity filters** keep noisy deep-wing settlement quotes out of the surface
    calibration (real EOD chains are dense with stale far strikes that inject static arbitrage):

    * ``moneyness_band`` — keep only ``|log(K/F)| ≤ band·√τ`` (a √time-scaled band, so it is wider
      for longer expiries where the smile genuinely spans more); ``None`` keeps every strike.
    * ``iv_bounds`` — drop inverted vols outside ``(lo, hi)`` (clearly bad prints); ``None`` keeps all.

    Defaults are ``None`` (no filtering) so synthetic/offline runs are unchanged; the live desk path
    passes both.
    """
    points: list[IVPoint] = []
    for q in raw.option_chain:
        tau = year_fraction(raw.date, q.expiry)
        if tau <= 0.0:
            continue
        rate = ois_curve.zero_rate(q.expiry)
        forward = raw.spot * exp((rate - raw.dividend_yield) * tau)
        discount = ois_curve.discount_factor(q.expiry)
        log_moneyness = log(q.strike / forward)
        if moneyness_band is not None and abs(log_moneyness) > moneyness_band * sqrt(tau):
            continue  # deep wing — illiquid/stale settlement, drop before it pollutes the surface
        try:
            iv = implied_vol(q.settlement_price, forward, q.strike, tau, discount, q.is_call)
        except ValueError:
            continue
        if iv_bounds is not None and not (iv_bounds[0] <= iv <= iv_bounds[1]):
            continue  # implausible inverted vol from a crossed/stale print
        points.append(IVPoint(q.expiry, q.strike, q.is_call, log_moneyness, tau, iv))
    return points

