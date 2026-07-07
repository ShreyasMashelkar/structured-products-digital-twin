"""FastAPI service exposing the SPDT desk to the React front end (L14 backend).

A thin, typed HTTP layer over the existing engine — it does no quant of its own. ``/api/desk``
returns the full precomputed desk dataset (the same payload the Streamlit view used), and
``/api/structure`` runs a *live* price-to-par solve so the structuring screen is interactive.
The heavy desk build is cached in-process so the first request pays for it once.

    uvicorn webapp.server:app --port 8000 --reload
"""

from __future__ import annotations

import dataclasses
import os
import threading
import time
from datetime import date, timedelta
from math import exp
from typing import cast

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# `integration` is the sole cross-world seam — it re-exports everything (incl. CreditCurve) the
# desk needs from the vendored XVA engine, so the webapp never imports `src.*` directly.
from integration import (
    CSA,
    CreditCurve,
    GovernanceGate,
    SpdtCurveAsOIS,
    bacva_capital,
    collateralise,
    economic_capital,
    exposure_metrics,
    note_exposure,
    saccr_ead_equity,
    solve_coupon_all_in,
    stress_xva,
    term_structure_credit_curve,
    xva_charge,
    xva_sensitivities,
)
from spdt.core.types import Curve, year_fraction
from spdt.book.book import Trade as BookTrade
from spdt.dashboard.desk_data import build_desk_data
from spdt.greeks import bump_greeks
from spdt.pricing import BlackScholes, price_mc, price_worst_of
from spdt.products import (
    Autocallable,
    BarrierReverseConvertible,
    CapitalProtectedNote,
    Product,
    ReverseConvertible,
    WorstOfAutocallable,
)
from spdt.reporting import terminal_scenarios
from spdt.outcomes import OutcomeTerms, hedge_comparison, issuance_study
from spdt.stress import STANDARD_SCENARIOS
from spdt.structurer import (
    ClientBrief,
    ClientObjective,
    Proposal,
    SolveFor,
    par_target,
    recommend,
    solve_to_par,
)

# --- configuration (all env-driven so the same image runs locally and deployed) -----------
_CORS = os.environ.get("SPDT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
_DESK_TTL = float(os.environ.get("SPDT_DESK_TTL", "3600"))  # seconds before a rebuild
_LIVE = os.environ.get("SPDT_LIVE", "").lower() in ("1", "true", "yes")
_SOURCE = os.environ.get("SPDT_SOURCE", "bhavcopy")  # live engine: bhavcopy (EOD) | dhan (intraday)
_API_TOKEN = os.environ.get("SPDT_API_TOKEN")  # when set, compute endpoints require it

app = FastAPI(title="SPDT Desk API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _CORS.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_token(x_api_token: str | None = Header(default=None)) -> None:
    """Header-token gate on compute endpoints. A no-op when SPDT_API_TOKEN is unset (dev)."""
    if _API_TOKEN and x_api_token != _API_TOKEN:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing X-API-Token")


# --- desk dataset cache: TTL-based so a long-lived process re-marks, not freezes -----------
@dataclasses.dataclass
class _DeskCache:
    payload: dict | None = None
    built_at: float = 0.0


_cache = _DeskCache()
_cache_lock = threading.Lock()


def _desk(force: bool = False) -> dict:
    """The desk payload, rebuilt when stale (older than the TTL) or on ``force``."""
    now = time.time()
    if _cache.payload is not None and not force and (now - _cache.built_at) < _DESK_TTL:
        return _cache.payload
    with _cache_lock:  # only one builder; others wait then see the fresh result
        if force or _cache.payload is None or (time.time() - _cache.built_at) >= _DESK_TTL:
            _cache.payload = build_desk_data(live=_LIVE, source=_SOURCE).payload
            _cache.built_at = time.time()
    assert _cache.payload is not None
    return _cache.payload


@app.get("/api/health")
def health() -> dict:
    built = _cache.built_at
    return {"status": "ok", "live": _LIVE, "desk_age_s": round(time.time() - built, 1) if built else None}


@app.get("/api/desk")
def desk() -> dict:
    """The whole desk payload: positions, greeks, P&L explain, reserves, stress, surface, …."""
    return _desk()


@app.post("/api/desk/refresh", dependencies=[Depends(require_token)])
def refresh_desk() -> dict:
    """Force a desk rebuild (admin) — re-marks the book on the latest snapshot."""
    d = _desk(force=True)
    return {"status": "rebuilt", "as_of": d["as_of"], "data_source": d["data_source"]}


class StructureRequest(BaseModel):
    target_coupon: float = 0.12
    max_downside: float = 0.30
    maturity: float = 1.0
    obs_per_year: int = 4
    fee: float = 1.0
    objective: str = "income"  # income | yield_enhanced | protection
    prefer_basket: bool = False
    product: str | None = None  # override: solve this family instead of the recommended one


class StructureCandidate(BaseModel):
    product_type: str
    label: str
    rationale: str
    fit_score: float


class StructureResponse(BaseModel):
    # The active structure — the recommended best fit, or the requested override — fully solved.
    product_type: str
    label: str
    rationale: str
    solve_for: str  # "coupon" | "participation"
    solved_annual_coupon: float | None  # for coupon notes
    solved_participation: float | None  # for capital-protected notes
    solved_display: str | None  # human headline, e.g. "6.21% p.a." or "1.85× upside"
    indicative_annual_coupon: float | None
    achieved_pv: float | None
    target_pv: float
    achievable: bool
    knock_in: float | None
    book_params: dict  # params (with the solved value filled in) to stage the trade
    book_observation_times: list[float]
    book_maturity: float
    x_label: str  # pv_curve x-axis label
    pv_curve: list[dict]  # [{"x": ..., "pv": ...}]
    alternatives: list[StructureCandidate]  # every family, ranked best-first (incl. the active one)


_OBJECTIVES = {
    "income": ClientObjective.INCOME,
    "yield_enhanced": ClientObjective.YIELD_ENHANCED,
    "protection": ClientObjective.PROTECTION,
}
# n_paths kept modest so the live solve stays responsive; worst-of pays for 3 correlated assets.
_SOLVE_PATHS = {"worst_of": 6_000}
_DEFAULT_SOLVE_PATHS = 12_000
_CURVE_POINTS = 12


def _price_proposal(prop: Proposal, free: float, spot: float, m: dict, *, n_paths: int) -> float:
    """Model PV of a proposal with its single free parameter set to ``free``."""
    p = dict(prop.params)
    p[prop.free_param_key] = free
    obs = prop.observation_times
    if prop.product_type == "worst_of":
        names = tuple(p["underlyings"])
        vols = np.array([m["atm_vol"] * vm for vm in p["vol_mult"]])
        spots0 = np.full(len(names), spot)
        corr = np.full((len(names), len(names)), p["correlation"])
        np.fill_diagonal(corr, 1.0)
        wo = WorstOfAutocallable(
            notional=100.0, observation_times=obs, coupon_rate=p["coupon_rate"],
            autocall_level=p["autocall_level"], coupon_barrier=p["coupon_barrier"],
            knock_in=p["knock_in"], memory=p["memory"], underlyings=names,
            initial_fixings=tuple(float(s) for s in spots0),
        )
        return price_worst_of(
            wo, spots0, vols, corr, r=m["r"], q=m["q"], n_paths=n_paths, seed=7
        ).price
    # single-underlying notes price under Black–Scholes on the desk's ATM vol
    model = BlackScholes(spot=spot, r=m["r"], q=m["q"], sigma=m["atm_vol"])
    if prop.product_type == "autocallable":
        note: Product = Autocallable(
            100.0, obs, p["coupon_rate"], p["autocall_level"], p["coupon_barrier"],
            p["knock_in"], p["memory"], initial_fixing=spot,
        )
    elif prop.product_type == "brc":
        note = BarrierReverseConvertible(
            100.0, obs, p["coupon_rate"], p["strike"], p["knock_in"], initial_fixing=spot,
        )
    elif prop.product_type == "capital_protected":
        note = CapitalProtectedNote(
            100.0, prop.maturity, p["protection"], p["participation"], p["strike"], p.get("cap"),
        )
    else:
        raise ValueError(f"unknown product_type {prop.product_type!r}")
    return price_mc(note, model, n_paths=n_paths, seed=7).price


def _solve_and_curve(
    prop: Proposal, spot: float, m: dict, obs_per_year: int, fee: float
) -> tuple[float | None, float | None, list[dict], float]:
    """Solve the proposal's free parameter to par and build a PV-vs-parameter curve."""
    n_paths = _SOLVE_PATHS.get(prop.product_type, _DEFAULT_SOLVE_PATHS)
    target = par_target(100.0, fee=fee)
    is_coupon = prop.solve_for == SolveFor.COUPON

    def pv_of(x: float) -> float:
        return _price_proposal(prop, x, spot, m, n_paths=n_paths)

    lo, hi = prop.bracket
    sweep_lo = hi / _CURVE_POINTS if is_coupon else 0.25
    curve = []
    for i in range(_CURVE_POINTS):
        x = sweep_lo + (hi - sweep_lo) * i / (_CURVE_POINTS - 1)
        xv = round(x * obs_per_year * 100, 3) if is_coupon else round(x, 3)
        curve.append({"x": xv, "pv": round(pv_of(x), 4)})

    try:
        solved = solve_to_par(pv_of, target, prop.bracket)
        return solved.param, solved.achieved_pv, curve, target
    except ValueError:
        return None, None, curve, target


@app.post("/api/structure", response_model=StructureResponse, dependencies=[Depends(require_token)])
def structure(req: StructureRequest) -> StructureResponse:
    """Client brief → recommended structure (best fit) → solve its free param to par (L6).

    Mirrors a real desk: the brief's *objective* + risk appetite pick the product family; the
    chosen note's coupon (income notes) or participation (capital-protected) is then solved to
    par. ``product`` overrides the recommendation so the desk can price an alternative family.
    """
    d = _desk()
    spot, m = d["spot"], d["model"]
    brief = ClientBrief(
        req.target_coupon, req.max_downside, req.maturity, req.obs_per_year,
        objective=_OBJECTIVES.get(req.objective, ClientObjective.INCOME),
        prefer_basket=req.prefer_basket,
    )
    ranked = recommend(brief)
    active = next((r for r in ranked if r.proposal.product_type == req.product), ranked[0])
    prop = active.proposal

    free, achieved, curve, target = _solve_and_curve(prop, spot, m, req.obs_per_year, req.fee)
    is_coupon = prop.solve_for == SolveFor.COUPON

    solved_annual = free * req.obs_per_year if (is_coupon and free is not None) else None
    solved_part = free if (not is_coupon and free is not None) else None
    indic_annual = prop.params["coupon_rate"] * req.obs_per_year if is_coupon else None
    if free is None:
        display: str | None = None
    elif is_coupon:
        display = f"{free * req.obs_per_year * 100:.2f}% p.a."
    else:
        display = f"{free:.2f}× upside"
    # Achievable = the client's coupon ask is met (income), or it priced to par at all (protection).
    achievable = bool(
        free is not None and (not is_coupon or (solved_annual or 0.0) >= req.target_coupon)
    )

    book_params = dict(prop.params)
    if free is not None:
        book_params[prop.free_param_key] = free

    return StructureResponse(
        product_type=prop.product_type,
        label=active.label,
        rationale=active.rationale,
        solve_for=prop.solve_for.value,
        solved_annual_coupon=round(solved_annual, 6) if solved_annual is not None else None,
        solved_participation=round(solved_part, 6) if solved_part is not None else None,
        solved_display=display,
        indicative_annual_coupon=round(indic_annual, 6) if indic_annual is not None else None,
        achieved_pv=round(achieved, 4) if achieved is not None else None,
        target_pv=target,
        achievable=achievable,
        knock_in=prop.params.get("knock_in"),
        book_params=book_params,
        book_observation_times=list(prop.observation_times),
        book_maturity=prop.maturity,
        x_label="annual coupon (%)" if is_coupon else "participation (×)",
        pv_curve=curve,
        alternatives=[
            StructureCandidate(
                product_type=r.proposal.product_type, label=r.label,
                rationale=r.rationale, fit_score=r.fit_score,
            )
            for r in ranked
        ],
    )


# --- generic term-sheet pricer (so the blotter can price arbitrary / staged trades) --------

class PriceRequest(BaseModel):
    product_type: str  # autocallable | brc | reverse_convertible | capital_protected
    notional: float = 100.0
    observation_times: list[float] | None = None
    maturity: float | None = None
    params: dict = {}


class SemiStaticTradeRequest(PriceRequest):
    trade_id: str
    underlying: str = "NIFTY"
    direction: int = 1
    initial_fixing: float | None = None
    barrier_breached: bool | None = None
    unwound_fraction: float = 0.0
    elapsed_years: float = 0.0


class SemiStaticRequest(BaseModel):
    trades: list[SemiStaticTradeRequest]
    spot: float
    sigma: float
    r: float
    q: float
    selected_trade_id: str | None = None


def _build_product(req: PriceRequest, spot: float) -> Product:
    """Reconstruct any catalog product from a term-sheet-shaped request (struck at spot)."""
    p = req.params
    obs = tuple(req.observation_times or [])
    kind = req.product_type
    if kind == "autocallable":
        return Autocallable(
            req.notional, obs, p.get("coupon_rate", 0.02), p.get("autocall_level", 1.0),
            p.get("coupon_barrier", 0.7), p.get("knock_in", 0.6), p.get("memory", False),
            initial_fixing=spot,
        )
    if kind == "brc":
        monitoring = p.get("barrier_monitoring")
        return BarrierReverseConvertible(
            req.notional, obs, p.get("coupon_rate", 0.06), p.get("strike", 1.0),
            p.get("knock_in", 0.7),
            barrier_monitoring=tuple(monitoring) if monitoring else None,
            initial_fixing=spot,
        )
    if kind == "reverse_convertible":
        return ReverseConvertible(
            req.notional, obs, p.get("coupon_rate", 0.08), p.get("strike", 1.0),
            initial_fixing=spot,
        )
    if kind == "capital_protected":
        return CapitalProtectedNote(
            req.notional, req.maturity or (obs[-1] if obs else 1.0),
            p.get("protection", 1.0), p.get("participation", 1.0), p.get("strike", 1.0),
            p.get("cap"), initial_fixing=spot,
        )
    raise ValueError(f"unknown product_type {kind!r}")


def _build_semistatic(req: SemiStaticRequest) -> dict:
    from spdt.dashboard.analytics_data import build_semistatic_payload

    trades: list[BookTrade] = []
    states: dict[str, dict] = {}
    for item in req.trades:
        try:
            fixing = item.initial_fixing or req.spot
            product = _build_product(item, fixing)
        except ValueError:
            continue
        trades.append(BookTrade(item.trade_id, product, item.underlying, item.direction))
        states[item.trade_id] = {
            "barrier_breached": item.barrier_breached,
            "unwound_fraction": item.unwound_fraction,
            "elapsed_years": item.elapsed_years,
        }
    model = BlackScholes(spot=req.spot, sigma=req.sigma, r=req.r, q=req.q)
    return build_semistatic_payload(
        trades, model, selected_trade_id=req.selected_trade_id, lifecycle_states=states
    )


@app.post("/api/semistatic", dependencies=[Depends(require_token)])
def semistatic(req: SemiStaticRequest) -> dict:
    """Rebuild semi-static analytics from the live blotter and current market state."""
    return _build_semistatic(req)


@app.get("/api/semistatic")
def semistatic_book() -> dict:
    """Backward-compatible server-book view of the same live analytics."""
    desk = _desk()
    market = desk["model"]
    trades = [
        SemiStaticTradeRequest(
            trade_id=p["trade_id"],
            underlying=p.get("underlying", desk["underlying"]),
            product_type=p["product_type"],
            notional=p["notional"],
            observation_times=p.get("observation_times"),
            maturity=p.get("maturity"),
            params=p.get("params", {}),
            initial_fixing=p.get("initial_fixing", desk["spot"]),
            barrier_breached=p.get("barrier_breached", False),
            unwound_fraction=p.get("unwound_fraction", 0.0),
        )
        for p in desk["positions"]
    ]
    return _build_semistatic(SemiStaticRequest(
        trades=trades,
        spot=desk["spot"],
        sigma=market["atm_vol"],
        r=market["r"],
        q=market["q"],
    ))


# --- Outcome Lab: issuance evidence → hedge economics → one end-to-end client decision ------

_outcome_cache: tuple[float, dict] | None = None
_outcome_lock = threading.Lock()


@app.get("/api/outcomes", dependencies=[Depends(require_token)])
def outcomes() -> dict:
    """Return studies for one actual 2Y autocallable in the current desk blotter."""
    global _outcome_cache
    d = _desk()
    cache_key = _cache.built_at
    if _outcome_cache is not None and _outcome_cache[0] == cache_key:
        return _outcome_cache[1]
    with _outcome_lock:
        if _outcome_cache is not None and _outcome_cache[0] == cache_key:
            return _outcome_cache[1]
        spot, m = d["spot"], d["model"]
        candidates = [
            p for p in d["positions"]
            if p["product_type"] == "autocallable" and p["maturity"] == 2.0
            and p["underlying"] == d["underlying"]
        ]
        if not candidates:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "desk snapshot has no 2Y single-index autocallable")
        source_trade = candidates[0]
        contract_id = source_trade["trade_id"]
        observations = source_trade["observation_times"]
        maturity = float(source_trade["maturity"])
        periods_per_year = max(round(len(observations) / maturity), 1)
        target_coupon_pa = 0.12
        xva_result = xva(XvaRequest(
            product_type=source_trade["product_type"],
            notional=float(source_trade["notional"]),
            observation_times=observations,
            maturity=maturity,
            params=source_trade["params"],
            counterparty="HEDGE-CP-01",
            cds_spread_bps=180.0,
            recovery_rate=0.40,
            funding_spread_bp=50.0,
            hurdle_rate=0.10,
            margin=1.0,
            cost_of_capital=0.12,
            collateralised=True,
            csa_threshold=0.0,
            n_paths=6_000,
        ))
        all_in = xva_result.get("all_in") or {}
        fair_coupon = all_in.get("coupon_base_pa")
        offered = all_in.get("coupon_all_in_pa")
        if fair_coupon is None or offered is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "book-trade coupon could not be solved before and after XVA")
        fair_coupon, offered = float(fair_coupon), float(offered)
        terms = OutcomeTerms(
            maturity=maturity,
            observations_per_year=periods_per_year,
            coupon_rate=offered / periods_per_year,
            knock_in=float(source_trade["params"]["knock_in"]),
            coupon_barrier=float(source_trade["params"]["coupon_barrier"]),
            autocall_level=float(source_trade["params"]["autocall_level"]),
        )
        issuance = issuance_study(spot, m["atm_vol"], terms)
        hedge = hedge_comparison(spot, m["atm_vol"], m["r"], m["q"], terms)
        coupon_gap = target_coupon_pa - offered
        target_met = coupon_gap <= 0.0
        proceed = target_met and xva_result["decision"] == "APPROVED"
        case = {
            "title": f"Book trade {contract_id} · client re-offer decision",
            "brief": {
                "objective": "Income mandate with defined conditional protection",
                "target_coupon_pa_pct": 100.0 * target_coupon_pa,
                "tenor_years": maturity,
                "max_downside": f"{100.0 * (1.0 - terms.knock_in):.1f}% distance to knock-in",
                "counterparty_cds_bp": 180,
                "counterparty_role": "OTC hedge counterparty (not the funded note investor)",
            },
            "structure": {
                "product": "Phoenix autocallable",
                "booked_coupon_pa_pct": round(100.0 * float(source_trade["coupon"]) * periods_per_year, 2),
                "fair_coupon_before_xva_pct": round(100.0 * fair_coupon, 2),
                "offered_coupon_after_xva_pct": round(100.0 * offered, 2),
                "target_shortfall_pct_pt": round(max(100.0 * coupon_gap, 0.0), 2),
                "knock_in_pct": round(100.0 * terms.knock_in, 1),
                "target_met": target_met,
            },
            "investor_outcome": {
                "ensemble_autocall_rate_pct": issuance["autocall_rate_pct"],
                "ensemble_loss_rate_pct": issuance["loss_rate_pct"],
                "tail_return_pct": issuance["tail_return_pct"],
            },
            "desk_outcome": {
                "selected_hedge": hedge["best_strategy"],
                "pnl_risk_reduction_pct": hedge["best_risk_reduction_pct"],
                "hedge_cost": next(
                    row["transaction_cost"] for row in hedge["strategies"]
                    if row["strategy"] == hedge["best_strategy"]
                ),
                "selection_rule": hedge["selection_rule"],
            },
            "ccr_outcome": {
                "xva_total": round(float(xva_result["charge"]["total"]), 4),
                "ead": round(float(xva_result["metrics"]["ead"]), 4),
                "economic_capital": round(float(xva_result["capital"]["economic"]), 4),
                "raroc_pct": round(float(xva_result["trade_raroc"] * 100.0), 2),
                "decision": xva_result["decision"],
            },
            "recommendation": "Proceed to term sheet" if proceed else "Restructure or reset client target",
            "restructuring_actions": [
                "Lower the target coupon to the XVA-adjusted offer",
                "Move the knock-in barrier higher within the client's loss budget",
                "Extend tenor or reduce issuer margin, subject to governance approval",
            ],
            "decision_reasons": xva_result["reasons"],
            "disclosure": "Illustrative, model-generated case study; not investment advice or realised client performance.",
            "contract_id": contract_id,
        }
        payload = {
            "as_of": d["as_of"], "contract_id": contract_id,
            "source_trade": {
                "trade_id": contract_id, "underlying": source_trade["underlying"],
                "notional": source_trade["notional"], "maturity": maturity,
                "booked_coupon_pa_pct": round(100.0 * float(source_trade["coupon"]) * periods_per_year, 2),
                "knock_in_pct": round(100.0 * terms.knock_in, 1),
                "coupon_barrier_pct": round(100.0 * terms.coupon_barrier, 1),
                "observation_frequency": f"{periods_per_year} per year",
            },
            "run_metadata": {"model": "BS + contractual payoff MC", "currency": "INR", "seed_policy": "fixed documented ensemble"},
            "issuance": issuance, "hedge": hedge, "case_study": case,
        }
        _outcome_cache = (cache_key, payload)
        return payload


@app.post("/api/price", dependencies=[Depends(require_token)])
def price(req: PriceRequest) -> dict:
    """Price any term sheet (PV, greeks, scenario-at-maturity, stress) under the desk model."""
    d = _desk()
    spot, m = d["spot"], d["model"]
    model = BlackScholes(spot=spot, r=m["r"], q=m["q"], sigma=m["atm_vol"])
    product = _build_product(req, spot)

    pv = price_mc(product, model, n_paths=40_000, seed=7)
    greeks = bump_greeks(product, model, n_paths=40_000, seed=7)
    scen = terminal_scenarios(product, (0.4, 0.6, 0.8, 1.0, 1.2))
    base = pv.price
    stress = [
        {
            "scenario": sc.name,
            "pnl": price_mc(product, sc.apply(model), n_paths=40_000, seed=7).price - base,
        }
        for sc in STANDARD_SCENARIOS
    ]
    return {
        "pv": pv.price,
        "std_error": pv.std_error,
        "greeks": {"delta": greeks.delta, "gamma": greeks.gamma, "vega": greeks.vega,
                   "rho": greeks.rho, "cash_delta": greeks.delta * spot * 0.01,
                   "vega_pt": greeks.vega / 100.0},
        "scenarios": [
            {"terminal_level": s.terminal_level, "ki_breached": s.ki_breached,
             "payment_pct": s.payment_pct} for s in scen
        ],
        "stress": stress,
    }


# --- Counterparty & XVA: the per-trade charge + governance gate (ADR-0007, Phase 6) ---------
#
# The thin React surface the ADR allows: one tab over the integration layer's
# exposure → XVA → governance seam. The endpoint marks the note to future, charges its CVA/FVA,
# derives the CCR metrics and economic capital, and runs the governance gate — no quant of its own,
# all of it borrowed from `integration/`.

# A flat curve is sufficient for the per-trade charge surface (the desk's full bootstrapped curve
# isn't in the cached payload); year-fraction tenors make the anchor date immaterial.
_CURVE_TAUS = (0.5, 1.0, 2.0, 3.0, 5.0)
_SPREAD_SWEEP_BPS = (0.0, 50.0, 100.0, 150.0, 200.0, 300.0, 400.0, 600.0, 800.0)
_COUPON_PRODUCTS = {"autocallable", "brc", "reverse_convertible"}  # notes the coupon can be solved for


def _flat_curve(rate: float) -> SpdtCurveAsOIS:
    anchor = date(2026, 1, 1)
    pillars = tuple(anchor + timedelta(days=round(365 * t)) for t in _CURVE_TAUS)
    dfs = {p: exp(-rate * year_fraction(anchor, p)) for p in pillars}
    return SpdtCurveAsOIS(Curve(anchor=anchor, pillars=pillars, discount_factors=dfs))


def _credit(cds_spread_bps: float, recovery_rate: float) -> CreditCurve:
    return CreditCurve(cds_spread_bps=max(cds_spread_bps, 1e-6), recovery_rate=recovery_rate)


class XvaRequest(BaseModel):
    product_type: str = "autocallable"  # single-asset notes only (autocallable | brc | reverse_convertible | capital_protected)
    notional: float = 100.0
    observation_times: list[float] | None = None
    maturity: float | None = None
    params: dict = {}
    counterparty: str = "CP-0"
    cds_spread_bps: float = 200.0       # 5y CDS; anchors the credit curve
    cds_1y_bps: float | None = None     # if given (with the 5y above), build a term-structure curve
    recovery_rate: float = 0.40
    funding_spread_bp: float = 50.0
    hurdle_rate: float = 0.10
    margin: float | None = None         # structuring margin in note units; default 1% of notional
    ead_limit: float | None = None
    pfe_limit: float | None = None
    # XVA depth (all opt-in; defaults reproduce unilateral CVA+FVA)
    own_cds_bps: float | None = None    # issuer's own CDS → DVA benefit
    cost_of_capital: float = 0.0        # > 0 turns on KVA
    include_mva: bool = False           # fund initial margin → MVA
    wwr_beta: float = 0.0               # wrong-way-risk tilt on the CVA exposure
    collateralised: bool = False        # apply a CSA before charging
    csa_threshold: float = 0.0
    mpor_days: int = 10
    # regulatory inputs
    single_name: bool = True            # equity SA-CCR supervisory factor (32% vs 20% index)
    sector: str = "Corporate"           # BA-CVA risk-weight bucket
    rating: str = "IG"
    n_paths: int = 12_000


@app.post("/api/xva", dependencies=[Depends(require_token)])
def xva(req: XvaRequest) -> dict:
    """Mark a note to future → charge CVA/FVA → derive EAD/PFE + capital → run the governance gate.

    Returns the per-trade charge, the expected-exposure profile (the autocall cliff is visible here),
    a counterparty-spread sweep of the charge, and the APPROVED / REJECTED / MANUAL_REVIEW decision.
    """
    if req.product_type == "worst_of":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "worst-of exposure is not yet wired to the XVA tab")
    d = _desk()
    spot, m = d["spot"], d["model"]
    model = BlackScholes(spot=spot, r=m["r"], q=m["q"], sigma=m["atm_vol"])
    product = _build_product(
        PriceRequest(product_type=req.product_type, notional=req.notional,
                     observation_times=req.observation_times, maturity=req.maturity, params=req.params),
        spot,
    )

    ois = _flat_curve(m["r"])
    funding = _flat_curve(m["r"] + req.funding_spread_bp * 1e-4)
    mat = req.maturity or (req.observation_times[-1] if req.observation_times else 1.0)
    grid: np.ndarray
    if req.collateralised or req.include_mva:
        # MPoR-aware grid: do not approximate a 10-day close-out gap on two-month exposure steps.
        step = max(req.mpor_days / 365.0, 1.0 / 365.0)
        grid = np.arange(0.0, mat, step, dtype=np.float64)
    else:
        grid = np.linspace(0.0, mat * 0.975, 14, dtype=np.float64)
    try:
        raw_pkg = note_exposure(product, model, ois, funding, time_grid=grid,
                                n_paths=req.n_paths, seed=7, counterparty_id=req.counterparty)
    except Exception as e:  # a product whose exposure the seam can't yet build
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"could not build exposure: {e}") from e

    # Counterparty credit: a bootstrapped term structure when a 1y point is given, else flat.
    if req.cds_1y_bps is not None:
        credit = term_structure_credit_curve(
            [1.0, 5.0], [max(req.cds_1y_bps, 1e-6), max(req.cds_spread_bps, 1e-6)],
            recovery_rate=req.recovery_rate, ois_curve=ois,
        )
    else:
        credit = _credit(req.cds_spread_bps, req.recovery_rate)
    own_credit = _credit(req.own_cds_bps, req.recovery_rate) if req.own_cds_bps else None

    # Optional CSA: charge the residual (collateralised) exposure.
    pkg = collateralise(raw_pkg, CSA(threshold=req.csa_threshold, mpor_days=req.mpor_days)) \
        if req.collateralised else raw_pkg

    charge = xva_charge(
        pkg, credit, funding_spread_bp=req.funding_spread_bp, own_credit_curve=own_credit,
        cost_of_capital=req.cost_of_capital, wwr_beta=req.wwr_beta, include_mva=req.include_mva,
    )
    metrics = exposure_metrics(pkg)
    ec = economic_capital(pkg, credit, ead=metrics["EAD"])
    sens = xva_sensitivities(pkg, credit)
    current_value = float(raw_pkg.npv_paths[:, 0].mean())
    saccr = saccr_ead_equity(req.notional, mat, current_value=current_value, single_name=req.single_name)
    bacva = bacva_capital(saccr["ead"], mat, sector=req.sector, rating=req.rating)

    limits = []
    le_id = f"LE_{req.counterparty}"
    if req.ead_limit:
        limits.append({"LegalEntityID": le_id, "Metric": "EAD", "LimitAmount": req.ead_limit})
    if req.pfe_limit:
        limits.append({"LegalEntityID": le_id, "Metric": "PFE", "LimitAmount": req.pfe_limit})
    margin = req.margin if req.margin is not None else req.notional * 0.01
    gate = GovernanceGate(limits=limits, hurdle_rate=req.hurdle_rate,
                          funding_spread_bp=req.funding_spread_bp)
    decision = gate.evaluate(pkg, credit, revenue=margin)

    ee = pkg.expected_exposure()
    profile = [{"t": round(float(t), 4), "ee": round(float(v), 5)}
               for t, v in zip(pkg.time_grid, ee)]
    spread_curve = [
        {"cds_bp": bp, **{k: round(v, 5) for k, v in
                          xva_charge(pkg, _credit(bp, req.recovery_rate),
                                     funding_spread_bp=req.funding_spread_bp).items()}}
        for bp in _SPREAD_SWEEP_BPS
    ]
    stress_ladder = [
        {"shift_bp": row["shift_bp"], "cva": round(row["cva"], 5), "total": round(row["total"], 5)}
        for row in stress_xva(pkg, credit)
    ]

    # The all-in coupon (the punchline): re-solve the coupon to par, then to par − XVA, and report
    # both annualised. Only for coupon-bearing notes; uses the full charge knobs.
    all_in = None
    if req.product_type in _COUPON_PRODUCTS:
        def _make(c: float) -> Product:
            return _build_product(
                PriceRequest(product_type=req.product_type, notional=req.notional,
                             observation_times=req.observation_times, maturity=req.maturity,
                             params={**req.params, "coupon_rate": c}),
                spot,
            )

        def _price(c: float) -> float:
            return price_mc(_make(c), model, n_paths=12_000, seed=7).price

        def _expo(c: float):
            p = note_exposure(_make(c), model, ois, funding, time_grid=grid,
                              n_paths=8_000, seed=7, counterparty_id=req.counterparty)
            return collateralise(p, CSA(threshold=req.csa_threshold, mpor_days=req.mpor_days)) \
                if req.collateralised else p

        try:
            res = solve_coupon_all_in(
                _price, _expo, credit, par=req.notional, fee=margin, bracket=(0.0, 0.30),
                funding_spread_bp=req.funding_spread_bp, own_credit_curve=own_credit,
                cost_of_capital=req.cost_of_capital, include_mva=req.include_mva, wwr_beta=req.wwr_beta,
            )
            ppy = max(round(len(req.observation_times) / mat) if req.observation_times and mat else 1, 1)
            cb = cast(float, res["coupon_base"]) * ppy
            ca = cast(float, res["coupon_all_in"]) * ppy
            all_in = {"coupon_base_pa": cb, "coupon_all_in_pa": ca,
                      "drop_bp": (cb - ca) * 1e4, "periods_per_year": ppy, "infeasible": False}
        except Exception:  # XVA too large to price with a non-negative coupon
            all_in = {"infeasible": True}

    return {
        "charge": {k: charge[k] for k in ("cva", "fva", "dva", "kva", "mva", "total")},
        "metrics": {"ead": metrics["EAD"], "pfe": metrics["PFE"], "epe": metrics["EPE"],
                    "ee_peak": metrics["EE_peak"], "expected_loss": ec["Expected_Loss"]},
        "sensitivities": {"cs01": sens["cs01"], "jtd_gross": sens["jtd_gross"], "jtd_net": sens["jtd_net"]},
        "capital": {"economic": ec["Economic_Capital"], "regulatory_bacva": bacva["capital"],
                    "saccr_ead": saccr["ead"], "bacva_risk_weight_pct": bacva["risk_weight_pct"]},
        "decision": decision["Decision"],
        "reasons": decision["Reasons"],
        "limit_status": decision["Limit_Status"],
        "trade_raroc": decision["Trade_RAROC"],
        "margin": margin,
        "all_in": all_in,
        "collateralised": req.collateralised,
        "profile": profile,
        "spread_curve": spread_curve,
        "stress_ladder": stress_ladder,
        "inputs": {"cds_spread_bps": req.cds_spread_bps, "recovery_rate": req.recovery_rate,
                   "funding_spread_bp": req.funding_spread_bp, "hurdle_rate": req.hurdle_rate},
    }


# --- static front end -----------------------------------------------------------------------
# In production a single process serves the built React app (webapp/frontend/dist) at "/", so
# the SPA and its relative /api/* calls are same-origin (no CORS, no token needed). Mounted
# LAST so every /api/* route declared above still takes precedence over this catch-all. A no-op
# in dev, where there is no dist and Vite serves the UI on :5173 and proxies /api back here.
from pathlib import Path  # noqa: E402

from fastapi.staticfiles import StaticFiles  # noqa: E402

_DIST = Path(__file__).resolve().parent / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="spa")
