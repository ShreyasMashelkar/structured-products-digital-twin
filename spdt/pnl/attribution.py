"""Daily P&L attribution: explain ΔPV as a sum of risk-factor contributions (L10).

Every day a desk reconciles the change in each trade's value against a second-order Taylor
expansion in the risk factors::

    ΔPV ≈ Δ·ΔS + ½Γ·ΔS²        (spot)
         + Θ·Δt                 (time)
         + ν·Δσ + ½·volga·Δσ²   (vol)
         + vanna·ΔS·Δσ          (cross)
         + ρ·Δr                 (rates)
         + RESIDUAL

The **residual** — full-revaluation ΔPV minus the explained terms — is the headline number:
small means the Greeks and the repricing agree (the model is internally consistent); large
flags a missing risk factor or big convexity (high gamma/vanna near a barrier). All
sensitivities are computed at D-1 under common random numbers, so the explain isn't swamped
by Monte-Carlo noise.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from spdt.greeks.buckets import bucketed_vega
from spdt.pricing.engine import price_mc
from spdt.pricing.models import BlackScholes
from spdt.pricing.models.term_vol import TermVolBlackScholes
from spdt.products.catalog import (
    Autocallable,
    BarrierReverseConvertible,
    CapitalProtectedNote,
    ReverseConvertible,
)
from spdt.products.graph import Product
from spdt.products.primitives import CashOrNothingDigital, DownBarrierPut, EuropeanOption


def age(product: Product, dt: float) -> Product:
    """Advance a product by ``dt`` years (observation/expiry times move closer).

    Raises if an observation would cross the as-of date — daily attribution assumes ``dt`` is
    small enough that no cashflow is realised inside the step (which would be separate P&L).
    """
    if isinstance(product, (Autocallable, BarrierReverseConvertible, ReverseConvertible)):
        new_times = tuple(t - dt for t in product.observation_times)
        if min(new_times) <= 0.0:
            raise ValueError("dt crosses an observation date; realised cashflow not handled")
        if isinstance(product, BarrierReverseConvertible) and product.barrier_monitoring is not None:
            mon = tuple(t - dt for t in product.barrier_monitoring if t - dt > 0.0)
            return dataclasses.replace(product, observation_times=new_times, barrier_monitoring=mon)
        return dataclasses.replace(product, observation_times=new_times)
    if isinstance(product, CapitalProtectedNote):
        if product.maturity - dt <= 0.0:
            raise ValueError("dt crosses maturity")
        return dataclasses.replace(product, maturity=product.maturity - dt)
    if isinstance(product, (EuropeanOption, CashOrNothingDigital)):
        if product.expiry - dt <= 0.0:
            raise ValueError("dt crosses expiry")
        return dataclasses.replace(product, expiry=product.expiry - dt)
    if isinstance(product, DownBarrierPut):
        return dataclasses.replace(
            product,
            expiry=product.expiry - dt,
            monitoring=tuple(t - dt for t in product.monitoring if t - dt > 0.0),
        )
    raise TypeError(f"don't know how to age {type(product).__name__}")


@dataclass(frozen=True)
class PnLExplain:
    """A trade's daily P&L decomposed into risk-factor contributions (design doc §7)."""

    total: float  # actual full-revaluation ΔPV
    delta_pnl: float
    gamma_pnl: float
    theta_pnl: float
    vega_pnl: float
    volga_pnl: float
    vanna_pnl: float
    rho_pnl: float
    explained: float  # sum of the Taylor terms above
    residual: float  # total − explained (the headline diagnostic)

    @property
    def residual_fraction(self) -> float:
        """Residual as a fraction of the total move (0 if nothing moved)."""
        return self.residual / self.total if self.total else 0.0


def attribute(
    product: Product,
    model0: BlackScholes,
    model1: BlackScholes,
    dt: float,
    *,
    n_paths: int = 200_000,
    seed: int = 0,
    rel_spot_bump: float = 1e-2,
    vol_bump: float = 1e-2,
    rate_bump: float = 1e-4,
) -> PnLExplain:
    """Attribute the D-1→D P&L of ``product`` to its risk factors with a residual check."""

    def pv(model: BlackScholes, prod: Product) -> float:
        return price_mc(prod, model, n_paths=n_paths, seed=seed).price

    s0, sig0, r0 = model0.spot, model0.sigma, model0.r
    h_s, h_v, h_r = s0 * rel_spot_bump, vol_bump, rate_bump
    base = pv(model0, product)

    def at(spot: float | None = None, sigma: float | None = None, r: float | None = None) -> float:
        return pv(
            dataclasses.replace(
                model0,
                spot=s0 if spot is None else spot,
                sigma=sig0 if sigma is None else sigma,
                r=r0 if r is None else r,
            ),
            product,
        )

    # First/second-order sensitivities at D-1 (CRN: every revaluation shares the seed).
    up_s, dn_s = at(spot=s0 + h_s), at(spot=s0 - h_s)
    up_v, dn_v = at(sigma=sig0 + h_v), at(sigma=sig0 - h_v)
    up_r, dn_r = at(r=r0 + h_r), at(r=r0 - h_r)
    pp = at(spot=s0 + h_s, sigma=sig0 + h_v)
    pm = at(spot=s0 + h_s, sigma=sig0 - h_v)
    mp = at(spot=s0 - h_s, sigma=sig0 + h_v)
    mm = at(spot=s0 - h_s, sigma=sig0 - h_v)

    delta = (up_s - dn_s) / (2 * h_s)
    gamma = (up_s - 2 * base + dn_s) / (h_s * h_s)
    vega = (up_v - dn_v) / (2 * h_v)
    volga = (up_v - 2 * base + dn_v) / (h_v * h_v)
    vanna = (pp - pm - mp + mm) / (4 * h_s * h_v)
    rho = (up_r - dn_r) / (2 * h_r)
    theta = (pv(model0, age(product, dt)) - base) / dt  # ∂PV/∂t at constant market

    # Risk-factor moves D-1 → D.
    d_s = model1.spot - s0
    d_sig = model1.sigma - sig0
    d_r = model1.r - r0

    delta_pnl = delta * d_s
    gamma_pnl = 0.5 * gamma * d_s * d_s
    theta_pnl = theta * dt
    vega_pnl = vega * d_sig
    volga_pnl = 0.5 * volga * d_sig * d_sig
    vanna_pnl = vanna * d_s * d_sig
    rho_pnl = rho * d_r
    explained = (
        delta_pnl + gamma_pnl + theta_pnl + vega_pnl + volga_pnl + vanna_pnl + rho_pnl
    )

    # Actual P&L: full reval at D (market moved and the trade aged by dt).
    total = pv(model1, age(product, dt)) - base
    return PnLExplain(
        total=total,
        delta_pnl=delta_pnl,
        gamma_pnl=gamma_pnl,
        theta_pnl=theta_pnl,
        vega_pnl=vega_pnl,
        volga_pnl=volga_pnl,
        vanna_pnl=vanna_pnl,
        rho_pnl=rho_pnl,
        explained=explained,
        residual=total - explained,
    )


@dataclass(frozen=True)
class VegaBucketExplain:
    """Vega P&L decomposed across the vol term structure (the desk's vega ladder explain).

    ``by_bucket`` maps each knot tenor to ``vega_bucket · Δσ_bucket``; ``explained`` is their
    sum; ``total`` is the full-revaluation vega P&L (vols moved bucket-by-bucket, spot held);
    ``residual`` is the convexity (volga/cross-bucket) the first-order ladder leaves behind.
    A flat-vol explain collapses all of this into a single number and cannot say *which* tenor
    drove the day's vol P&L.
    """

    by_bucket: dict[float, float]
    explained: float
    total: float
    residual: float


def vega_bucket_explain(
    product: Product,
    model0: TermVolBlackScholes,
    model1: TermVolBlackScholes,
    *,
    n_paths: int = 200_000,
    seed: int = 0,
    vol_bump: float = 1e-2,
) -> VegaBucketExplain:
    """Attribute the vol P&L of ``product`` to each term-structure bucket, with a residual.

    ``model0``/``model1`` share spot/rates and differ only in their forward-vol term structure
    (yesterday's vs today's surface), so this isolates the vega P&L from delta/theta.
    """
    if model0.knot_times != model1.knot_times:
        raise ValueError("the two surfaces must share the same bucket tenors")
    ladder = bucketed_vega(product, model0, n_paths=n_paths, seed=seed, vol_bump=vol_bump)
    by_bucket = {
        tk: ladder[tk] * (v1 - v0)
        for tk, v0, v1 in zip(model0.knot_times, model0.knot_vols, model1.knot_vols)
    }
    explained = sum(by_bucket.values())

    def pv(m: TermVolBlackScholes) -> float:
        return price_mc(product, m, n_paths=n_paths, seed=seed).price

    total = pv(model1) - pv(model0)
    return VegaBucketExplain(
        by_bucket=by_bucket, explained=explained, total=total, residual=total - explained
    )
