"""All-in pricing — fold the XVA charge into the structurer's solve (ADR-0007, Phase 4).

The structuring desk solves the coupon so the note's PV equals ``par − fee`` (the issuer keeps the
fee as margin). But the issuer *also* bears the note's lifetime counterparty and funding cost — its
**XVA**. Carrying that in, fairness becomes ``PV = par − fee − XVA``: the target PV drops by the
charge, so the coupon the desk can offer drops with it — and drops *further* as the counterparty's
credit spread widens. That is the headline of combining the two desks: a price that is honest about
what the note actually costs to carry.

CVA comes straight from the XVA engine (EE × default-probability × discount). FVA is the funding
cost of the expected positive exposure at the issuer's funding spread (a standard FCA integral).
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from integration.exposure_package import ExposurePackage
from spdt.structurer.solver import par_target, solve_to_par
from src.xva.cva import CVAEngine, CreditCurve  # type: ignore  # resolved via integration


def xva_charge(
    pkg: ExposurePackage, credit_curve: "CreditCurve", *, funding_spread_bp: float = 50.0
) -> dict[str, float]:
    """CVA + FVA of a packaged exposure, in note currency units.

    CVA via the XVA engine; FVA = Σ EE(tᵢ)·s_fund·Δtᵢ·DF(tᵢ) — the cost of funding the expected
    positive exposure at the issuer's funding spread.
    """
    ee = pkg.expected_exposure()
    cva = float(CVAEngine(pkg.ois_curve).compute_cva(ee, pkg.time_grid, credit_curve))
    dt = np.diff(pkg.time_grid, prepend=0.0)
    df = np.array([pkg.funding_curve.df(float(t)) for t in pkg.time_grid])
    fva = float(np.sum(ee * (funding_spread_bp * 1e-4) * dt * df))
    return {"cva": cva, "fva": fva, "total": cva + fva}


def solve_coupon_all_in(
    price_of_coupon: Callable[[float], float],
    exposure_of_coupon: Callable[[float], ExposurePackage],
    credit_curve: "CreditCurve",
    *,
    par: float = 100.0,
    fee: float = 0.0,
    bracket: tuple[float, float] = (0.0, 0.20),
    funding_spread_bp: float = 50.0,
) -> dict[str, float | dict[str, float]]:
    """Solve the coupon twice — to par, then to par net of XVA — and return both with the charge.

    ``price_of_coupon`` maps a coupon to the note PV; ``exposure_of_coupon`` maps it to an
    :class:`ExposurePackage`. The XVA is evaluated at the no-XVA coupon (its dependence on the
    coupon is second-order), then the target PV is reduced by the charge and the coupon re-solved.
    """
    base = solve_to_par(price_of_coupon, par_target(par, fee), bracket)
    charge = xva_charge(exposure_of_coupon(base.param), credit_curve,
                        funding_spread_bp=funding_spread_bp)
    all_in = solve_to_par(price_of_coupon, par - fee - charge["total"], bracket)
    return {
        "coupon_base": base.param,
        "coupon_all_in": all_in.param,
        "xva": charge,
    }
