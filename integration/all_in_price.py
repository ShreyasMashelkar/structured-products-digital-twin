"""All-in pricing — fold the XVA charge into the structurer's solve (ADR-0007, Phase 4).

The structuring desk solves the coupon so the note's PV equals ``par − fee`` (the issuer keeps the
fee as margin). But the issuer *also* bears the note's lifetime counterparty and funding cost — its
**XVA**. Carrying that in, fairness becomes ``PV = par − fee − XVA``: the target PV drops by the
charge, so the coupon the desk can offer drops with it — and drops *further* as the counterparty's
credit spread widens. That is the headline of combining the two desks: a price that is honest about
what the note actually costs to carry.

CVA comes straight from the XVA engine (EE × default-probability × discount). FVA is the funding
cost of the expected positive exposure at the issuer's funding spread (a standard FCA integral).
Optionally the charge also carries **DVA** (the mirror benefit from the issuer's own default),
**KVA** (the cost of holding regulatory capital over the trade's life), and a **wrong-way-risk**
tilt on the CVA exposure — so the all-in number can be unilateral CVA+FVA (the default) or a fuller
``CVA + FVA + KVA − DVA``.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from integration.ccr_overlays import wrong_way_ee
from integration.exposure_package import ExposurePackage
from spdt.structurer.solver import par_target, solve_to_par
from src.xva.cva import CVAEngine, CreditCurve  # type: ignore  # resolved via integration
from src.xva.kva import KVAEngine  # type: ignore  # resolved via integration


def xva_charge(
    pkg: ExposurePackage,
    credit_curve: "CreditCurve",
    *,
    funding_spread_bp: float = 50.0,
    own_credit_curve: "CreditCurve | None" = None,
    cost_of_capital: float = 0.0,
    risk_weight: float = 1.0,
    wwr_beta: float = 0.0,
) -> dict[str, float]:
    """XVA of a packaged exposure, in note currency units: ``total = CVA + FVA + KVA − DVA``.

    * **CVA** via the XVA engine, on the (optionally wrong-way-tilted) EE.
    * **FVA** = Σ EE(tᵢ)·s_fund·Δtᵢ·DF(tᵢ) — funding the expected positive exposure.
    * **DVA** (only if ``own_credit_curve`` is given) — the mirror benefit from the issuer's own
      default, on the expected *negative* exposure; it enters ``total`` with a minus sign.
    * **KVA** (only if ``cost_of_capital > 0``) — the lifetime cost of capital on the EAD profile
      (α·EE), via the engine's ``KVAEngine``.

    With the defaults (no own curve, zero cost-of-capital, ``wwr_beta=0``) this is exactly unilateral
    CVA + FVA, so callers that don't ask for the extras are unaffected.
    """
    ee = pkg.expected_exposure()
    ee_cva = wrong_way_ee(pkg, beta=wwr_beta) if wwr_beta else ee
    engine = CVAEngine(pkg.ois_curve)
    cva = float(engine.compute_cva(ee_cva, pkg.time_grid, credit_curve))

    dt = np.diff(pkg.time_grid, prepend=0.0)
    df = np.array([pkg.funding_curve.df(float(t)) for t in pkg.time_grid])
    fva = float(np.sum(ee * (funding_spread_bp * 1e-4) * dt * df))

    dva = 0.0
    if own_credit_curve is not None:
        ene = pkg.expected_negative_exposure()
        dva = float(engine.compute_dva(ene, pkg.time_grid, own_credit_curve))

    kva = 0.0
    if cost_of_capital > 0.0:
        kva = float(
            KVAEngine(pkg.ois_curve, cost_of_capital=cost_of_capital)
            .compute_kva_from_exposure(ee, pkg.time_grid, risk_weight=risk_weight)["KVA"]
        )

    total = cva + fva + kva - dva
    return {"cva": cva, "fva": fva, "dva": dva, "kva": kva, "total": total}


def solve_coupon_all_in(
    price_of_coupon: Callable[[float], float],
    exposure_of_coupon: Callable[[float], ExposurePackage],
    credit_curve: "CreditCurve",
    *,
    par: float = 100.0,
    fee: float = 0.0,
    bracket: tuple[float, float] = (0.0, 0.20),
    funding_spread_bp: float = 50.0,
    own_credit_curve: "CreditCurve | None" = None,
    cost_of_capital: float = 0.0,
    risk_weight: float = 1.0,
    wwr_beta: float = 0.0,
) -> dict[str, float | dict[str, float]]:
    """Solve the coupon twice — to par, then to par net of XVA — and return both with the charge.

    ``price_of_coupon`` maps a coupon to the note PV; ``exposure_of_coupon`` maps it to an
    :class:`ExposurePackage`. The XVA is evaluated at the no-XVA coupon (its dependence on the
    coupon is second-order), then the target PV is reduced by the charge and the coupon re-solved.
    The charge components (DVA / KVA / wrong-way) follow the same knobs as :func:`xva_charge`.
    """
    base = solve_to_par(price_of_coupon, par_target(par, fee), bracket)
    charge = xva_charge(
        exposure_of_coupon(base.param), credit_curve, funding_spread_bp=funding_spread_bp,
        own_credit_curve=own_credit_curve, cost_of_capital=cost_of_capital,
        risk_weight=risk_weight, wwr_beta=wwr_beta,
    )
    all_in = solve_to_par(price_of_coupon, par - fee - charge["total"], bracket)
    return {
        "coupon_base": base.param,
        "coupon_all_in": all_in.param,
        "xva": charge,
    }
