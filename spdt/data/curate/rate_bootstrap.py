"""Bootstrap the OIS / risk-free curve from money-market and OIS quotes (design doc §2.2).

Rates are **bootstrapped, not assumed flat**: we solve the discount factors maturity by
maturity so that every quoted instrument reprices to par, then interpolate between pillars
(log-linear on discount factors, consistent with :class:`~spdt.core.types.Curve`).

Two instrument kinds:

* **Money market / T-bill** (zero-coupon, simple interest): ``D(T) = 1 / (1 + y·τ)``.
* **OIS par swap** (fixed vs compounded overnight): the floating leg is worth ``1 − D(T)``,
  so the par condition ``S·Σ τ_i D(t_i) = 1 − D(T)`` gives, for the newest pillar,
  ``D(T_n) = (1 − S·A_prev) / (1 + S·τ_n)`` where ``A_prev`` is the annuity of the already-
  bootstrapped coupon dates. OIS coupons are assumed to fall on prior pillars (the standard
  co-terminal bootstrap convention).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import exp, log

from scipy.optimize import brentq

from spdt.core.types import Curve, year_fraction


@dataclass(frozen=True)
class RateInstrument:
    """A single calibrating quote on the OIS/risk-free curve."""

    maturity: date
    rate: float
    kind: str = "ois"  # "zero" (T-bill / deposit, simple interest) or "ois" (par swap)


def bootstrap_discount_factors(
    anchor: date, instruments: list[RateInstrument]
) -> dict[date, float]:
    """Solve discount factors at each instrument maturity so every quote reprices to par."""
    insts = sorted(instruments, key=lambda x: x.maturity)
    if not insts:
        raise ValueError("need at least one instrument to bootstrap")

    discount: dict[date, float] = {}
    for inst in insts:
        tau = year_fraction(anchor, inst.maturity)
        if tau <= 0.0:
            raise ValueError(f"instrument maturity {inst.maturity} is not after {anchor}")

        if inst.kind == "zero":
            discount[inst.maturity] = 1.0 / (1.0 + inst.rate * tau)
        elif inst.kind == "ois":
            total_days = (inst.maturity - anchor).days
            coupon_dates = [
                anchor + timedelta(days=365 * n)
                for n in range(1, total_days // 365 + 1)
                if 365 * n < total_days
            ]
            coupon_dates.append(inst.maturity)

            def par_error(terminal_df: float) -> float:
                points = sorted({anchor: 1.0, **discount, inst.maturity: terminal_df}.items())

                def interpolated_df(coupon_date: date) -> float:
                    if coupon_date in discount:
                        return discount[coupon_date]
                    for (d0, df0), (d1, df1) in zip(points, points[1:]):
                        if d0 < coupon_date < d1:
                            span = year_fraction(d0, d1)
                            weight = year_fraction(d0, coupon_date) / span
                            return exp(log(df0) + weight * (log(df1) - log(df0)))
                    raise ValueError(f"cannot interpolate OIS coupon date {coupon_date}")

                annuity = 0.0
                previous = anchor
                for coupon_date in coupon_dates:
                    df = terminal_df if coupon_date == inst.maturity else interpolated_df(coupon_date)
                    annuity += year_fraction(previous, coupon_date) * df
                    previous = coupon_date
                return inst.rate * annuity - (1.0 - terminal_df)

            try:
                discount[inst.maturity] = brentq(par_error, 1e-12, 10.0)
            except ValueError as exc:
                raise ValueError(f"cannot bootstrap OIS maturity {inst.maturity}") from exc
        else:
            raise ValueError(f"unknown instrument kind {inst.kind!r}")

    return discount


def bootstrap_ois_curve(anchor: date, instruments: list[RateInstrument]) -> Curve:
    """Bootstrap and wrap the discount factors in a :class:`Curve`."""
    discount = bootstrap_discount_factors(anchor, instruments)
    pillars = tuple(sorted(discount))
    return Curve(anchor=anchor, pillars=pillars, discount_factors=discount)


def bootstrap_zero_rates(anchor: date, instruments: list[RateInstrument]) -> dict[date, float]:
    """Continuously-compounded zero rates at the pillars (drop into ``RawMarketData``)."""
    discount = bootstrap_discount_factors(anchor, instruments)
    return {d: -log(df) / year_fraction(anchor, d) for d, df in discount.items()}
