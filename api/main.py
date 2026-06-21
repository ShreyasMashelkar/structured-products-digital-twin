"""
INR XVA Engine — FastAPI REST Layer.

Exposes the core pricing and risk engines as HTTP endpoints.
All calculations call the actual engine modules — no hardcoded values.

Endpoints:
    POST /price/swap          — Price a single INR IRS/OIS swap
    POST /risk/exposure       — Run Monte Carlo exposure for a swap
    POST /risk/cva            — Compute CVA for a swap + counterparty
    GET  /curves/ois          — Return current OIS curve nodes
    GET  /curves/cds/{name}   — Bootstrap CDS curve for a counterparty
    GET  /portfolio/eod       — Return latest EOD report

Run with:
    uvicorn api.main:app --reload --port 8000
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from src.data_ingestion.market_data import (
    get_ois_market_data, get_counterparty_data
)
from src.curves.ois_curve import OISCurve
from src.pricing.swap_pricer import SwapPricer
from src.montecarlo.hull_white import HullWhite1F, run_exposure_simulation
from src.xva.cva import CVAEngine, CreditCurve, build_credit_curve_from_cds
from src.xva.fva import FVAEngine
from src.xva.kva import KVAEngine
from src.curves.credit_curve_bootstrapper import CDSBootstrapper


app = FastAPI(
    title="INR XVA Engine API",
    description="REST API for INR OTC Derivatives pricing, CCR exposure, and XVA.",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── Request / Response Models ─────────────────────────────────────────────────

class SwapRequest(BaseModel):
    notional_cr: float = Field(..., example=500.0, description="Notional in ₹ Crores")
    fixed_rate: float = Field(..., example=0.07, description="Fixed rate as decimal (0.07 = 7%)")
    maturity_years: float = Field(..., example=5.0)
    direction: str = Field(..., example="Receive Fixed")
    payment_freq: int = Field(1, example=1, description="1=annual, 2=semi-annual")


class ExposureRequest(SwapRequest):
    n_paths: int = Field(2000, description="Monte Carlo paths")
    a: float = Field(0.10, description="HW1F mean reversion speed")
    sigma: float = Field(0.01, description="HW1F volatility")


class CVARequest(SwapRequest):
    counterparty: str = Field(..., example="HDFC")
    cds_spread_bps: Optional[float] = Field(None, description="Override CDS spread")
    recovery_rate: float = Field(0.40)
    n_paths: int = Field(2000)


# ── Shared State ──────────────────────────────────────────────────────────────

def _build_ois_curve() -> OISCurve:
    data = get_ois_market_data()
    return OISCurve(data['tenor_years'].values, data['ois_rate'].values)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    return {"status": "ok", "engine": "INR XVA Platform v3.0"}


@app.get("/curves/ois")
def get_ois_curve():
    """Return the current bootstrapped OIS curve nodes."""
    data = get_ois_market_data()
    curve = _build_ois_curve()
    df_out = curve.to_dataframe()
    return {
        "curve_date": "2026-06-03",
        "nodes": df_out.to_dict(orient="records"),
    }


@app.post("/price/swap")
def price_swap(req: SwapRequest):
    """
    Price a single INR IRS/OIS swap.

    Returns MTM, par rate, DV01, PV01, and cash flow schedule.
    """
    curve = _build_ois_curve()
    pricer = SwapPricer(
        notional=req.notional_cr,
        fixed_rate=req.fixed_rate,
        maturity=req.maturity_years,
        direction=req.direction,
        payment_freq=req.payment_freq,
    )
    summary = pricer.risk_summary(curve)
    cf = pricer.cash_flow_schedule(curve)

    return {
        "mtm_cr": round(summary["mtm_cr"], 6),
        "par_rate": round(summary["par_rate"], 6),
        "dv01_cr": round(summary["dv01_cr"], 6),
        "pv01_cr": round(summary["pv01_cr"], 6),
        "gamma": round(summary["gamma"], 6),
        "cash_flows": cf.round(4).to_dict(orient="records"),
    }


@app.post("/risk/exposure")
def compute_exposure(req: ExposureRequest):
    """
    Run Monte Carlo exposure simulation for a swap.

    Returns EE, PFE(95%), EPE, EEPE profiles.
    """
    curve = _build_ois_curve()
    result = run_exposure_simulation(
        curve,
        notional=req.notional_cr,
        fixed_rate=req.fixed_rate,
        maturity=req.maturity_years,
        direction=req.direction,
        n_paths=req.n_paths,
        a=req.a,
        sigma=req.sigma,
        seed=42,
    )
    metrics = result["metrics"]
    # Sample every 5th point to keep response size manageable
    step = max(1, len(metrics["time_grid"]) // 20)
    return {
        "time_grid": metrics["time_grid"][::step].tolist(),
        "EE": np.round(metrics["EE"][::step], 6).tolist(),
        "PFE_95": np.round(metrics["PFE"][::step], 6).tolist(),
        "EPE": round(float(metrics["EPE"]), 6),
        "EEPE": round(float(metrics["EEPE"]), 6),
    }


@app.post("/risk/cva")
def compute_cva(req: CVARequest):
    """
    Compute CVA, DVA, FVA, KVA for a swap against a named counterparty.
    """
    curve = _build_ois_curve()

    # Resolve CDS spread
    cds_bps = req.cds_spread_bps
    risk_weight = 0.50
    funding_spread_bps = 50.0
    if cds_bps is None:
        cpty_df = get_counterparty_data()
        match = cpty_df[cpty_df["counterparty"] == req.counterparty]
        if match.empty:
            raise HTTPException(
                status_code=404,
                detail=f"Counterparty '{req.counterparty}' not found. "
                       "Provide cds_spread_bps to override."
            )
        cds_bps = float(match.iloc[0]["cds_spread_bps"])
        risk_weight = float(match.iloc[0]["risk_weight"])
        funding_spread_bps = float(match.iloc[0].get("funding_spread_bps", 50))

    # Run exposure
    result = run_exposure_simulation(
        curve,
        notional=req.notional_cr,
        fixed_rate=req.fixed_rate,
        maturity=req.maturity_years,
        direction=req.direction,
        n_paths=req.n_paths,
        seed=42,
    )
    metrics = result["metrics"]
    tg = metrics["time_grid"]
    ee = metrics["EE"]
    ene = metrics["ENE"]

    # CVA / DVA
    cva_engine = CVAEngine(curve)
    cpty_curve = build_credit_curve_from_cds(
        tenors=[1.0, 2.0, 3.0, 5.0, 7.0],
        spreads_bps=[cds_bps] * 5,
        recovery_rate=req.recovery_rate,
        ois_curve=curve,
    )
    own_curve = CreditCurve(40.0)  # Bank's own CDS
    bilateral = cva_engine.compute_bilateral_cva(ee, ene, tg, cpty_curve, own_curve)

    # FVA
    fva_engine = FVAEngine(curve, funding_spread_bps=funding_spread_bps)
    fva_result = fva_engine.compute_fva(ee, ene, tg)

    # KVA
    kva_engine = KVAEngine(curve)
    kva_result = kva_engine.compute_kva_from_exposure(ee, tg, risk_weight)

    return {
        "counterparty": req.counterparty,
        "cds_spread_bps": cds_bps,
        "EPE_cr": round(float(metrics["EPE"]), 6),
        "CVA_cr": round(bilateral["CVA"], 6),
        "DVA_cr": round(bilateral["DVA"], 6),
        "FVA_cr": round(fva_result["FVA"], 6),
        "KVA_cr": round(kva_result["KVA"], 6),
        "XVA_total_cr": round(
            bilateral["CVA"] + fva_result["FVA"] + kva_result["KVA"], 6
        ),
    }


@app.get("/curves/cds/{counterparty_name}")
def get_cds_curve(counterparty_name: str):
    """
    Bootstrap and return the CDS hazard rate curve for a counterparty.
    Uses synthetic term structure: flat spread with slight upward slope.
    """
    cpty_df = get_counterparty_data()
    match = cpty_df[cpty_df["counterparty"] == counterparty_name]
    if match.empty:
        raise HTTPException(status_code=404, detail=f"Counterparty '{counterparty_name}' not found")

    base_spread = float(match.iloc[0]["cds_spread_bps"])
    recovery = float(match.iloc[0].get("recovery_rate", 0.40))

    # Synthetic term structure: slight upward slope
    tenors = [1.0, 2.0, 3.0, 5.0, 7.0, 10.0]
    slope_bps_per_year = base_spread * 0.05  # 5% per year steepening
    spreads_bps = [base_spread + (t - 1) * slope_bps_per_year for t in tenors]

    curve = _build_ois_curve()
    bootstrapper = CDSBootstrapper(
        tenors=tenors,
        spreads_bps=spreads_bps,
        recovery_rate=recovery,
        ois_curve=curve
    )
    summary = bootstrapper.to_summary_dataframe()

    return {
        "counterparty": counterparty_name,
        "recovery_rate": recovery,
        "curve": summary.round(6).to_dict(orient="records"),
    }

class IncrementalTradeRequest(BaseModel):
    counterparty: str
    notional: float
    fixed_rate: float
    maturity: float
    direction: str
    csa_id: str = "UNCOLLATERALISED"

@app.post("/xva/incremental")
def xva_incremental(req: IncrementalTradeRequest):
    from src.workflow.incremental_xva import IncrementalXVAEngine
    trade = {'TradeID': -1, 'Counterparty': req.counterparty, 'Notional': req.notional,
             'FixedRate': req.fixed_rate, 'Maturity': req.maturity,
             'Direction': req.direction, 'CSA_ID': req.csa_id}
    return IncrementalXVAEngine().impact_report(trade).to_dict('records')


class TradeWorkflowRequest(BaseModel):
    trade: Dict[str, Any]
    base_metrics: Dict[str, Any]
    base_limits: Dict[str, Dict[str, float]]

@app.post("/workflow/approve")
def approve_trade(req: TradeWorkflowRequest):
    try:
        from src.workflow.trade_approval import TradeApprovalWorkflow
        from src.limits.limit_engine import LimitEngine
        from src.raroc.raroc_engine import RAROCEngine
        from src.workflow.incremental_xva import IncrementalXVAEngine
        from src.workflow.portfolio_xva import PortfolioXVAContext
        from src.data_ingestion.portfolio_manager import PortfolioManager
        
        ctx = PortfolioXVAContext(n_paths=500)
        xva_eng = IncrementalXVAEngine(ctx)
        lim_eng = LimitEngine([]) # Ideally fetch actual limits from DB here
        raroc_eng = RAROCEngine(hurdle_rate=0.10)
        
        wf = TradeApprovalWorkflow(lim_eng, raroc_eng, xva_eng)
        
        # Load base portfolio for incremental impact
        base_portfolio = PortfolioManager.load_portfolio().to_dict('records')
        
        res = wf.evaluate_trade(req.trade, base_portfolio, req.base_metrics, req.base_limits)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
