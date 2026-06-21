"""Governance gate — APPROVE / REJECT / MANUAL_REVIEW a note from its exposure (ADR-0007, Phase 5).

The last link in the chain ``position → exposure → XVA → price → decision``. Phase 4 prices the note
all-in; the desk still has to decide whether to *do* the trade. This module mirrors XVA's
``TradeApprovalWorkflow`` decision logic — a limit check on EAD/PFE and a RAROC test against a hurdle,
resolving to APPROVED / REJECTED / MANUAL_REVIEW — but sources every input from the SPDT
:class:`ExposurePackage` and the XVA charge, **not** from XVA's own trade objects.

Per ADR-0007 ("reuse the backend, don't rebuild it") the heavy lifting stays in XVA's leaf engines —
:class:`LimitEngine`, :class:`RAROCEngine`, :class:`EconomicCapitalEngine` — and only the
orchestration lives here. The single coupling point remains the exposure cube: limits and capital are
derived from the package's path × time NPVs, so the two product models never have to meet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from integration.all_in_price import xva_charge
from integration.exposure_package import ExposurePackage
from src.economic_capital.econ_capital import EconomicCapitalEngine  # type: ignore  # via integration
from src.limits.limit_engine import LimitEngine  # type: ignore  # via integration
from src.raroc.raroc_engine import RAROCEngine  # type: ignore  # via integration
from src.xva.cva import CreditCurve  # type: ignore  # via integration


def exposure_metrics(
    pkg: ExposurePackage, *, alpha: float = 1.4, pfe_quantile: float = 0.95,
    eepe_horizon: float = 1.0,
) -> dict[str, float]:
    """Counterparty-credit-risk metrics for one packaged exposure, read off its NPV cube.

    Computed directly from ``pkg.npv_paths`` so the numbers governance gates on are the same
    exposures Phase 3 produced and Phase 4 charged:

    * ``EE_peak``  — peak of the expected-exposure profile EE(t) = E[max(Vₜ, 0)].
    * ``EPE``      — time-averaged EE over the full life (the funding/CVA-relevant mean exposure).
    * ``EEPE``     — *effective* EPE: the time-average of the non-decreasing running max of EE over
                     ``[0, min(eepe_horizon, maturity)]``. Basel caps the averaging window at one
                     year (``eepe_horizon=1.0``); pass the full maturity for an economic EAD.
    * ``PFE``      — peak potential future exposure: the largest, over time, of the ``pfe_quantile``
                     quantile of positive exposure across paths.
    * ``EAD``      — exposure at default = ``alpha · EEPE`` (Basel α defaults to 1.4).
    """
    positive = np.maximum(pkg.npv_paths, 0.0)  # (n_paths, n_times)
    ee = positive.mean(axis=0)
    grid = pkg.time_grid
    horizon = float(grid[-1] - grid[0])
    eff_ee = np.maximum.accumulate(ee)
    if horizon > 0.0:
        epe = float(np.trapezoid(ee, grid) / horizon)
        # EEPE averages effective EE only over [grid[0], min(eepe_horizon, maturity)].
        cap = min(grid[0] + eepe_horizon, grid[-1])
        mask = grid <= cap + 1e-12
        sub_t, sub_e = grid[mask], eff_ee[mask]
        span = float(sub_t[-1] - sub_t[0])
        eepe = float(np.trapezoid(sub_e, sub_t) / span) if span > 0.0 else float(sub_e[-1])
    else:  # degenerate single-point grid
        epe = eepe = float(ee.mean())
    pfe = float(np.quantile(positive, pfe_quantile, axis=0).max())
    return {
        "EE_peak": float(ee.max()),
        "EPE": epe,
        "EEPE": eepe,
        "PFE": pfe,
        "EAD": alpha * eepe,
    }


def economic_capital(
    pkg: ExposurePackage,
    credit_curve: CreditCurve,
    *,
    ead: float | None = None,
    confidence_level: float = 0.999,
    asset_correlation: float = 0.15,
    alpha: float = 1.4,
) -> dict[str, float]:
    """ASRF economic capital for the exposure against this counterparty (Basel-style UL).

    The counterparty's 1-year default probability and LGD come straight off the CDS-implied
    ``credit_curve``; the EAD comes off the exposure cube (or is supplied). Delegates the unexpected-
    loss arithmetic to XVA's :class:`EconomicCapitalEngine`.
    """
    if ead is None:
        ead = exposure_metrics(pkg, alpha=alpha)["EAD"]
    pd_1y = credit_curve.cumulative_default_probability(1.0)
    engine = EconomicCapitalEngine(confidence_level=confidence_level)
    return engine.compute_economic_capital(
        ead=ead, pd_1y=pd_1y, lgd=credit_curve.lgd, asset_correlation=asset_correlation
    )


@dataclass(frozen=True)
class GovernanceGate:
    """Mirrors XVA's ``TradeApprovalWorkflow`` over the SPDT exposure seam.

    Attributes:
        limits: limit definitions for XVA's :class:`LimitEngine` — dicts of
            ``LegalEntityID`` / ``Metric`` (``EAD`` or ``PFE``) / ``LimitAmount``.
        hurdle_rate: minimum acceptable standalone RAROC.
        funding_spread_bp: issuer funding spread driving the FVA component of the charge.
        confidence_level: confidence for economic capital (default 99.9%).
        asset_correlation: ASRF asset correlation for the capital calc.
        alpha: Basel α mapping effective EPE to EAD.
    """

    limits: list[dict[str, Any]] = field(default_factory=list)
    hurdle_rate: float = 0.10
    funding_spread_bp: float = 50.0
    confidence_level: float = 0.999
    asset_correlation: float = 0.15
    alpha: float = 1.4

    def evaluate(
        self,
        pkg: ExposurePackage,
        credit_curve: CreditCurve,
        *,
        revenue: float,
        base_portfolio_metrics: dict[str, float] | None = None,
        base_entity_metrics: dict[str, dict[str, float]] | None = None,
        legal_entity_id: str | None = None,
    ) -> dict[str, Any]:
        """Decide a proposed note from its exposure, the counterparty credit, and the desk's margin.

        ``revenue`` is the structuring margin the issuer keeps (note-currency units — e.g. the Phase-4
        fee). ``base_portfolio_metrics`` (``Revenue``/``Expected_Loss``/``XVA_Costs``/``Capital``) and
        ``base_entity_metrics`` describe the existing book so the gate can test *incremental* RAROC and
        limit utilisation; left unset, the trade is judged standalone against an empty book.

        Maps the charge onto the RAROC P&L economically: CVA is the (risk-neutral) expected credit loss,
        FVA the funding cost, and ASRF unexpected loss the capital the trade consumes.
        """
        charge = xva_charge(pkg, credit_curve, funding_spread_bp=self.funding_spread_bp)
        metrics = exposure_metrics(pkg, alpha=self.alpha)
        ec = economic_capital(
            pkg, credit_curve, ead=metrics["EAD"],
            confidence_level=self.confidence_level, asset_correlation=self.asset_correlation,
        )
        capital = ec["Economic_Capital"]

        # 1. Limits — incremental EAD/PFE against the counterparty's existing utilisation.
        le_id = legal_entity_id or f"LE_{pkg.counterparty_id}"
        incr_limit_metrics = {"EAD": metrics["EAD"], "PFE": metrics["PFE"]}
        limit_df = LimitEngine(self.limits).pre_trade_check(
            base_entity_metrics or {}, incr_limit_metrics, le_id
        )
        limit_status = "PASS"
        if not limit_df.empty:
            if "BREACH" in limit_df["Status"].values:
                limit_status = "FAIL"
            elif "AMBER" in limit_df["Status"].values:
                limit_status = "WARNING"

        # 2. RAROC — standalone hurdle and portfolio accretion. CVA→expected loss, FVA→XVA cost.
        base = base_portfolio_metrics or {}
        raroc = RAROCEngine(hurdle_rate=self.hurdle_rate).evaluate_incremental_trade(
            base_revenue=base.get("Revenue", 0.0),
            base_el=base.get("Expected_Loss", 0.0),
            base_xva=base.get("XVA_Costs", 0.0),
            base_cap=base.get("Capital", 0.0),
            incr_revenue=revenue,
            incr_el=charge["cva"],
            incr_xva=charge["fva"],
            incr_cap=capital,
        )

        # 3. Decision — mirrors TradeApprovalWorkflow: a breach rejects, a clean accretive trade
        #    approves, anything in between (sub-hurdle, dilutive, or amber) routes to manual review.
        decision = "MANUAL_REVIEW"
        reasons: list[str] = []
        if limit_status == "FAIL":
            decision = "REJECTED"
            reasons.append("Limit breach detected.")
        if not raroc["Meets_Hurdle"]:
            reasons.append("Standalone RAROC below hurdle.")
            if decision != "REJECTED":
                decision = "MANUAL_REVIEW"
        if not raroc["Improves_Portfolio"]:
            reasons.append("Trade dilutes portfolio RAROC.")
        if limit_status == "PASS" and raroc["Meets_Hurdle"] and raroc["Improves_Portfolio"]:
            decision = "APPROVED"
            reasons.append("Accretive and within limits.")
        if limit_status == "WARNING":
            reasons.append("Approaching limit (amber).")
            if decision == "APPROVED":
                decision = "MANUAL_REVIEW"

        return {
            "Decision": decision,
            "Reasons": reasons,
            "Limit_Status": limit_status,
            "CVA": charge["cva"],
            "FVA": charge["fva"],
            "XVA_Total": charge["total"],
            "EAD": metrics["EAD"],
            "PFE": metrics["PFE"],
            "EPE": metrics["EPE"],
            "Capital": capital,
            "Trade_RAROC": raroc["Trade_Standalone_RAROC"],
            "Portfolio_RAROC_Impact": raroc["New_RAROC"] - raroc["Base_RAROC"],
        }
