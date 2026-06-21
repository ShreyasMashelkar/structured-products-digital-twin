"""XVA risk & regulatory metrics at the seam (ADR-0007).

What a CVA/CCR desk monitors *daily*, computed off the exposure cube and the charge:

* **CS01** — the CVA's sensitivity to a 1bp parallel widening of the counterparty's CDS curve (the
  CVA trader's primary hedge ratio), by bump-and-revalue.
* **JTD** — jump-to-default: the loss if the counterparty defaults *now*, ``LGD · current exposure``.
* **Credit stress** — the charge re-struck under a set of CDS-spread shocks.
* **SA-CCR EAD (equity)** — the Basel standardised-approach EAD for an equity derivative
  (``α·(RC + PFE add-on)`` with the **equity** supervisory factors), the regulatory counterpart to
  the economic ``α·EEPE`` read off the cube. SA-CCR is deliberately supervisory-factor driven, not
  Monte-Carlo driven — so this is a parallel regulatory number, not a function of the cube.
"""

from __future__ import annotations

from math import sqrt
from typing import Sequence

from integration.all_in_price import xva_charge
from integration.exposure_package import ExposurePackage
from src.xva.cva import CreditCurve  # type: ignore  # resolved via integration

# Basel SA-CCR supervisory factors for the equity asset class.
_SF_EQUITY_SINGLE_NAME = 0.32
_SF_EQUITY_INDEX = 0.20
_MPOR_FLOOR_YEARS = 10.0 / 250.0  # 10-business-day floor on remaining maturity


def cva_cs01(pkg: ExposurePackage, credit_curve: "CreditCurve", *, bump_bp: float = 1.0) -> float:
    """CS01 — change in CVA for a ``+bump_bp`` parallel shift of the CDS curve (bump & revalue)."""
    base = xva_charge(pkg, credit_curve)["cva"]
    bumped = xva_charge(pkg, credit_curve.shift(bump_bp))["cva"]
    return bumped - base


def xva_sensitivities(
    pkg: ExposurePackage, credit_curve: "CreditCurve", *, bump_bp: float = 1.0
) -> dict[str, float]:
    """CVA plus the two first-order credit risks a desk hedges: CS01 and jump-to-default.

    JTD is the immediate-default loss net of the CVA already taken: ``LGD·max(EE(0),0) − CVA``.
    """
    ee0 = float(pkg.expected_exposure()[0])
    cva = xva_charge(pkg, credit_curve)["cva"]
    jtd_gross = credit_curve.lgd * max(ee0, 0.0)
    return {
        "cva": cva,
        "cs01": cva_cs01(pkg, credit_curve, bump_bp=bump_bp),
        "jtd_gross": jtd_gross,
        "jtd_net": jtd_gross - cva,
    }


def stress_xva(
    pkg: ExposurePackage,
    credit_curve: "CreditCurve",
    *,
    shocks_bp: Sequence[float] = (-100.0, -50.0, 0.0, 50.0, 100.0, 200.0, 400.0),
) -> list[dict[str, float]]:
    """Re-strike the charge under a set of CDS-spread shocks — the CVA stress ladder."""
    out = []
    for s in shocks_bp:
        ch = xva_charge(pkg, credit_curve.shift(s) if s else credit_curve)
        out.append({"shift_bp": float(s), "cva": ch["cva"], "total": ch["total"]})
    return out


def saccr_ead_equity(
    notional: float,
    maturity: float,
    *,
    current_value: float = 0.0,
    collateral: float = 0.0,
    delta: float = 1.0,
    single_name: bool = True,
    alpha: float = 1.4,
) -> dict[str, float]:
    """Basel SA-CCR exposure-at-default for a single equity derivative.

    ``EAD = α·(RC + PFE)`` with ``RC = max(V − C, 0)`` and the equity PFE add-on
    ``|δ|·SF·notional·MF``, where SF = 32% (single name) / 20% (index) and the unmargined maturity
    factor ``MF = sqrt(min(M, 1y))`` (M floored at the 10-business-day MPoR). The regulatory mirror
    of the cube-based ``α·EEPE`` EAD in :func:`integration.governance.exposure_metrics`.
    """
    rc = max(current_value - collateral, 0.0)
    sf = _SF_EQUITY_SINGLE_NAME if single_name else _SF_EQUITY_INDEX
    eff_maturity = max(maturity, _MPOR_FLOOR_YEARS)
    mf = sqrt(min(eff_maturity, 1.0))
    addon = abs(delta) * sf * notional * mf
    ead = alpha * (rc + addon)
    return {"rc": rc, "addon": addon, "pfe": addon, "ead": ead}
