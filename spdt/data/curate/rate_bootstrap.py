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
from datetime import date
from math import log

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
    ois_coupon_dates: list[date] = []  # only OIS pillars carry fixed coupons (annual grid)

    for inst in insts:
        tau = year_fraction(anchor, inst.maturity)
        if tau <= 0.0:
            raise ValueError(f"instrument maturity {inst.maturity} is not after {anchor}")

        if inst.kind == "zero":
            discount[inst.maturity] = 1.0 / (1.0 + inst.rate * tau)
        elif inst.kind == "ois":
            # Annuity over the already-bootstrapped OIS coupon dates, plus this final accrual.
            annuity_prev = 0.0
            last = anchor
            for cd in ois_coupon_dates:
                annuity_prev += year_fraction(last, cd) * discount[cd]
                last = cd
            tau_n = year_fraction(last, inst.maturity)
            discount[inst.maturity] = (1.0 - inst.rate * annuity_prev) / (1.0 + inst.rate * tau_n)
            ois_coupon_dates.append(inst.maturity)
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
