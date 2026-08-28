"""FastAPI service exposing the SPDT desk to the React front end (L14 backend).

A thin, typed HTTP layer over the existing engine — it does no quant of its own. ``/api/desk``
returns the full precomputed desk dataset (the same payload the Streamlit view used), and
``/api/structure`` runs a *live* price-to-par solve so the structuring screen is interactive.
The heavy desk build is cached in-process so the first request pays for it once.

    uvicorn webapp.server:app --port 8000 --reload
"""

from __future__ import annotations

import dataclasses
import json
import os
import pickle
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from math import exp, log, sqrt
from typing import Any, TypedDict, cast

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

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
from spdt.alerts import AlertEngine, greek_limit_alert
from spdt.core.types import Curve, year_fraction
from spdt.book.book import Trade as BookTrade
from spdt.data.ingest.xts import InstrumentRef, Quote
from spdt.execution import PaperBroker
from spdt.hedging.recommend import (
    HedgeInstrument,
    HedgeRecommendation,
    recommend_delta_hedge,
    recommend_delta_vega_hedge,
    vanilla_spot_greeks,
)
from spdt.analytics.barrier_radar import barrier_hit_probability, terminal_above_probability
from spdt.analytics.realized_vol import realized_vol
from spdt.data.curate.bs_inversion import bs_price
from spdt.dashboard.desk_data import build_desk_data
from spdt.greeks import bump_greeks
from spdt.pricing import BlackScholes, price_mc, price_worst_of
from spdt.pricing.models.bs_term import BlackScholesTermVol
from spdt.products import (
    Autocallable,
    BarrierReverseConvertible,
    CapitalProtectedNote,
    Product,
    ReverseConvertible,
    WorstOfAutocallable,
)
from spdt.reporting import terminal_scenarios
from spdt.outcomes import OutcomeTerms, hedge_comparison, issuance_study, outcome_profile
from spdt.stress import STANDARD_SCENARIOS
from spdt.structurer.levers import manufacture
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
# Which underlying the desk itself books and prices. The market *panel* has always served any
# registered underlying; the desk was hardwired to NIFTY, so a US note could be inspected but
# never structured. SPX matters beyond geography: it is the only chain here that quotes a
# reliable surface past a year, which is the tenor range structured notes actually live in.
_UNDERLYING = os.environ.get("SPDT_UNDERLYING", "NIFTY").upper()
# replay: serve a recorded session (tick tape + saved desk payload) instead of a broker feed —
# the public-deploy mode, since redistributing a live broker feed needs an exchange licence.
_REPLAY = _SOURCE == "replay"
_REPLAY_DIR = os.environ.get("SPDT_REPLAY_DIR", "data/replay")


def _feed() -> bool:
    """Whether the tick/quote endpoints have data to serve (evaluated per request, so
    tests can monkeypatch ``_LIVE``/``_SOURCE``)."""
    return (_LIVE and _SOURCE == "xts") or _SOURCE == "replay"
# Book notes at real face (₹ per note) so note NAV/greeks share units with hedge P&L.
_FACE_PER_NOTE = float(os.environ.get("SPDT_FACE_PER_NOTE", "50000000"))
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
_rebuild_thread: threading.Thread | None = None


def _build_payload() -> dict:
    if _REPLAY:  # a desk payload saved off a live build — no network, nothing to rebuild
        from spdt.dashboard.desk_data import DeskData

        return DeskData.load(os.path.join(_REPLAY_DIR, "desk.json")).payload
    return build_desk_data(
        live=_LIVE, source=_SOURCE, underlying=_UNDERLYING, face_per_note=_FACE_PER_NOTE,
    ).payload


def _rebuild_desk() -> None:
    with _cache_lock:  # only one builder; others wait then see the fresh result
        if _cache.payload is None or (time.time() - _cache.built_at) >= _DESK_TTL:
            _cache.payload = _build_payload()
            _cache.built_at = time.time()
            _record_desk_history(_cache.payload)


def _desk(force: bool = False) -> dict:
    """The desk payload — stale-while-revalidate.

    The first build (and an explicit ``force``) blocks; after that a stale cache is
    served immediately while one background thread re-marks, so no request ever waits
    out a live rebuild (~45s on the XTS feed).
    """
    global _rebuild_thread
    if _cache.payload is None or force:
        with _cache_lock:
            if force or _cache.payload is None:
                _cache.payload = _build_payload()
                _cache.built_at = time.time()
                _record_desk_history(_cache.payload)
        return _cache.payload
    if not _REPLAY and (time.time() - _cache.built_at) >= _DESK_TTL:
        if _rebuild_thread is None or not _rebuild_thread.is_alive():
            _rebuild_thread = threading.Thread(
                target=_rebuild_desk, daemon=True, name="spdt-desk-rebuild",
            )
            _rebuild_thread.start()
    return _cache.payload


# --- snapshot archiver: accumulate an owned intraday history while the desk is live --------
_ARCHIVE_INTERVAL_S = float(os.environ.get("SPDT_ARCHIVE_INTERVAL_S", "900"))  # 0 disables
_ARCHIVE_ROOT = os.environ.get("SPDT_ARCHIVE_ROOT", "dashboard_data")


def _in_nse_session(now: datetime) -> bool:
    """Mon–Fri 09:15–15:35 IST (5 minutes past close to catch the closing prints)."""
    return now.weekday() < 5 and (9, 15) <= (now.hour, now.minute) <= (15, 35)


def _archive_loop() -> None:  # pragma: no cover — thin network loop; the pieces are tested
    from zoneinfo import ZoneInfo

    from spdt.data.archive import archive_snapshot
    from spdt.data.live import fetch_live_raw
    from spdt.data.snapshot_builder import build_snapshot

    ist = ZoneInfo("Asia/Kolkata")
    while True:
        if _in_nse_session(datetime.now(ist)):
            try:
                snap = build_snapshot(fetch_live_raw(date.today(), source=_SOURCE))
                archive_snapshot(snap, _ARCHIVE_ROOT, captured_at=datetime.now())
            except Exception as exc:  # noqa: BLE001 — a failed capture must not kill the loop
                print(f"spdt-archiver: capture failed: {exc}")
        time.sleep(_ARCHIVE_INTERVAL_S)


if _LIVE and not _REPLAY and _ARCHIVE_INTERVAL_S > 0:
    threading.Thread(target=_archive_loop, daemon=True, name="spdt-archiver").start()


@app.get("/api/health")
def health() -> dict:
    built = _cache.built_at
    return {"status": "ok", "live": _LIVE, "desk_age_s": round(time.time() - built, 1) if built else None}


@app.get("/api/desk")
def desk() -> dict:
    """The whole desk payload: positions, greeks, P&L explain, reserves, stress, surface, …."""
    d = _desk()
    hedge_pnl = _paper_hedge_pnl(d)
    return {**d, "net_greeks": _hedged_net_greeks(d),
            "nav": d["nav"] + hedge_pnl["total"], "hedge_pnl": hedge_pnl}


# --- desk timeline: an owned history of the marked desk, one row per build/execution -------
_DESK_HISTORY_PATH = os.environ.get(
    "SPDT_DESK_HISTORY",
    # replay ships the recorded day's timeline read-only; live accrues its own
    os.path.join(_REPLAY_DIR, "desk_history.jsonl") if _REPLAY else "dashboard_data/desk_history.jsonl",
)


def _record_desk_history(d: dict) -> None:
    """Append the desk's marked state — the raw material for the intraday replay."""
    if _REPLAY:  # never write into the shipped recording
        return
    try:
        greeks = _hedged_net_greeks(d)
        hedge_pnl = _paper_hedge_pnl(d)
        row = {"t": datetime.now(timezone.utc).isoformat(), "spot": d["spot"],
               "atm_vol": d["model"]["atm_vol"], "nav": d["nav"] + hedge_pnl["total"],
               "delta": greeks["delta"], "gamma": greeks["gamma"], "vega": greeks["vega"],
               "hedge_pnl": hedge_pnl["total"]}
        os.makedirs(os.path.dirname(_DESK_HISTORY_PATH) or ".", exist_ok=True)
        with open(_DESK_HISTORY_PATH, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as exc:  # noqa: BLE001 — history is a bonus, never a failure path
        print(f"spdt: desk history append failed: {exc}")


@app.get("/api/desk/history")
def desk_history(limit: int = 500) -> dict:
    """The desk timeline: spot, vol, NAV and net greeks at every build and execution."""
    try:
        with open(_DESK_HISTORY_PATH) as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return {"rows": []}
    rows = [json.loads(line) for line in lines[-max(1, limit):] if line.strip()]
    return {"rows": rows}


@app.get("/api/desk/residual")
def taylor_residual(spot_mult: float = 1.008, dvol: float = 0.003, n_paths: int = 12_000) -> dict:
    """Model-risk check, live: full re-pricing of the booked notes at a shifted market
    versus the greeks' Taylor prediction. Same MC seed on both marks (common random
    numbers), so the difference is smooth. Worst-of notes are skipped — the Taylor side
    uses only the greeks of the notes actually repriced, so the comparison stays honest.
    """
    if not 0.5 <= spot_mult <= 2.0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "spot_mult out of range")
    d = _desk()
    spot0, m = d["spot"], d["model"]
    n_paths = max(2000, min(n_paths, 40_000))
    base = BlackScholes(spot=spot0, r=m["r"], q=m["q"], sigma=m["atm_vol"])
    moved = BlackScholes(spot=spot0 * spot_mult, r=m["r"], q=m["q"],
                         sigma=max(m["atm_vol"] + dvol, 1e-4))
    actual = delta = gamma = vega = 0.0
    n_notes = 0
    for p in d["positions"]:
        try:
            req = PriceRequest(product_type=p["product_type"], notional=p.get("notional", 100.0),
                               observation_times=p.get("observation_times"),
                               maturity=p.get("maturity"), params=p.get("params") or {})
            product = _build_product(req, p.get("initial_fixing") or spot0)
        except (ValueError, KeyError, TypeError):
            continue  # worst-of sub-book rows and other non-catalog shapes
        pv0 = price_mc(product, base, n_paths=n_paths, seed=7).price
        pv1 = price_mc(product, moved, n_paths=n_paths, seed=7).price
        direction = p.get("direction", 1)
        actual += direction * (pv1 - pv0)
        delta += p.get("delta", 0.0)
        gamma += p.get("gamma", 0.0)
        vega += p.get("vega", 0.0)
        n_notes += 1
    dS = spot0 * (spot_mult - 1.0)
    terms = {"delta": delta * dS, "gamma": 0.5 * gamma * dS * dS, "vega": vega * dvol}
    predicted = sum(terms.values())
    return {
        "n_notes": n_notes, "n_paths": n_paths, "dS": dS, "dvol": dvol,
        "predicted": predicted, "actual": actual, "residual": actual - predicted,
        "terms": terms,
        "note": "residual holds cross-greeks (vanna/volga) and everything beyond 2nd order",
    }


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
    # Early-redemption level as a fraction of the initial fixing. Below 1.0 is a step-down
    # autocall: the note calls away on a smaller rally, selling upside to buy coupon.
    autocall_level: float = Field(default=1.0, gt=0.5, le=1.5)
    # "coupon" (default) solves what the structure pays; "knock_in" holds the coupon at the
    # client's target and solves the barrier that funds it — the question income buyers
    # actually ask, which is "how much downside must I carry for 15%?"
    solve_for: str = "coupon"
    # Surrender the upside tail rather than cap it — unlocks the shark-fin family, which is
    # otherwise not offered at all.
    accept_knockout: bool = False


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
    solve_for: str  # "coupon" | "participation" | "knock_in"
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
    # The gap between what the client asked for and what the market affords, plus the single
    # term concessions that would close it. Empty when the ask is already met.
    coupon_shortfall: float | None
    manufacture_summary: str | None
    levers: list[dict]
    # Whether the note outlives the vol data behind it. The desk reads its pricing vol at the
    # longest expiry whose fit it trusts; a note maturing past that is priced on the surface's
    # extrapolation, not on quotes. That is not necessarily wrong, but it must never be silent
    # — a 1.5y note quoted off a 60-day slice looks identical in the response to one quoted off
    # a 2-year slice, and only this field distinguishes them.
    vol_tau: float | None
    vol_extrapolated: bool
    data_warning: str | None
    alternatives: list[StructureCandidate]  # every family, ranked best-first (incl. the active one)


_OBJECTIVES = {
    "income": ClientObjective.INCOME,
    "yield_enhanced": ClientObjective.YIELD_ENHANCED,
    "protection": ClientObjective.PROTECTION,
}
# n_paths kept modest so the live solve stays responsive; worst-of pays for 3 correlated assets.
# Log-moneyness half-width representing the region a live chain actually quotes; the
# default Durrleman grid runs to +/-1.5, which for a 2-week slice is pure extrapolation.
_ARB_DATA_K = 0.35
# A note may run a little past the last trusted expiry without the price being extrapolation
# in any meaningful sense; beyond this it is.
_VOL_TAU_SLACK = 0.10
_SOLVE_PATHS = {"worst_of": 6_000}
_DEFAULT_SOLVE_PATHS = 12_000
_CURVE_POINTS = 12


def _term_vol_model(spot: float, m: dict) -> BlackScholes | BlackScholesTermVol:
    """The desk's equity model: term-structure Black-Scholes when the surface has a curve.

    Falls back to the flat-vol model on a one-pillar surface, where the two coincide anyway,
    so callers never have to branch.
    """
    pillars = tuple(
        (float(t), float(v)) for t, v in (m.get("atm_term") or ()) if t > 0.0 and v > 0.0
    )
    if len(pillars) < 2:
        return BlackScholes(spot=spot, r=m["r"], q=m["q"], sigma=m["atm_vol"])
    return BlackScholesTermVol(spot=spot, r=m["r"], q=m["q"], pillars=pillars)


def _price_proposal(prop: Proposal, free: float, spot: float, m: dict, *, n_paths: int) -> float:
    """Model PV of a proposal with its single free parameter set to ``free``."""
    p = dict(prop.params)
    p[prop.free_param_key] = free
    # The coupon trigger is set equal to the knock-in by the proposer, so when the barrier is
    # the free parameter it must travel with it. Left unlinked, the solve would deepen the
    # capital barrier while the coupon kept paying off the original level — pricing a note
    # nobody offered.
    if prop.free_param_key == "knock_in" and "coupon_barrier" in p:
        p["coupon_barrier"] = free
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
    # Single-underlying notes price on the desk's ATM *term structure* where one is
    # available, falling back to a flat vol only when the surface offers a single pillar.
    model = _term_vol_model(spot, m)
    if prop.product_type == "autocallable":
        note: Product = Autocallable(
            100.0, obs, p["coupon_rate"], p["autocall_level"], p["coupon_barrier"],
            p["knock_in"], p["memory"], initial_fixing=spot,
        )
    elif prop.product_type == "brc":
        note = BarrierReverseConvertible(
            100.0, obs, p["coupon_rate"], p["strike"], p["knock_in"], initial_fixing=spot,
        )
    elif prop.product_type in ("capital_protected", "shark_fin"):
        note = CapitalProtectedNote(
            100.0, prop.maturity, p["protection"], p["participation"], p["strike"], p.get("cap"),
            initial_fixing=spot,
            knock_out=p.get("knock_out"),
            rebate=p.get("rebate", 0.0),
            ko_monitoring=tuple(p.get("ko_monitoring", ()) or ()),
        )
    else:
        raise ValueError(f"unknown product_type {prop.product_type!r}")
    return price_mc(note, model, n_paths=n_paths, seed=7).price


_LEVER_PATHS = 12_000  # nested solve: cheap paths, the negotiation dominates the precision


def _solve_coupon_only(prop: Proposal, spot: float, m: dict, fee: float) -> float | None:
    """Per-period coupon that prices ``prop`` to par, or None if unreachable in its bracket.

    Fewer paths than the headline solve: the lever sweep runs a nested root-find, so this is
    called tens of times per request and precision here moves the *concession* by far less
    than the negotiation itself will.
    """
    try:
        return solve_to_par(
            lambda c: _price_proposal(prop, c, spot, m, n_paths=_LEVER_PATHS),
            par_target(100.0, fee=fee),
            prop.bracket,
        ).param
    except ValueError:
        return None


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
    is_barrier = prop.solve_for == SolveFor.KNOCK_IN
    sweep_lo = lo if is_barrier else (hi / _CURVE_POINTS if is_coupon else 0.25)
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
        autocall_level=req.autocall_level,
        accept_knockout=req.accept_knockout,
        solve_for=SolveFor.KNOCK_IN if req.solve_for == "knock_in" else SolveFor.COUPON,
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
    elif prop.solve_for == SolveFor.KNOCK_IN:
        # The barrier solve answers "how much downside buys this coupon?", so it is reported as
        # the downside the client carries, not as a bare level — the number they must react to.
        display = f"barrier {free:.0%} ({1 - free:.0%} downside) for {req.target_coupon:.2%} p.a."
    else:
        display = f"{free:.2f}× upside"
    # Achievable = the client's coupon ask is met (income), or it priced to par at all (protection).
    achievable = bool(
        free is not None and (not is_coupon or (solved_annual or 0.0) >= req.target_coupon)
    )

    book_params = dict(prop.params)
    # On a failed solve the free parameter is blanked rather than left at its indicative seed.
    # Leaving the seed makes an unsolved structure look like a solved one — book_params is what
    # stages the trade, so a stale 0.70 barrier beside achievable=False is a trade waiting to be
    # booked on terms nobody priced.
    book_params[prop.free_param_key] = free

    # When the market affords less than the client asked for, the answer is not "no" — it is
    # "which term will you move?". Only run for coupon solves: a barrier solve has already
    # answered the question, and a capital-protected note has no coupon to manufacture.
    shortfall: float | None = None
    manufacture_summary: str | None = None
    lever_rows: list[dict] = []
    if is_coupon and solved_annual is not None:
        shortfall = round(req.target_coupon - solved_annual, 6)
        if shortfall > 1e-9:
            report = manufacture(
                prop,
                lambda pr: _solve_coupon_only(pr, spot, m, req.fee),
                req.target_coupon,
                req.obs_per_year,
            )
            manufacture_summary = report.summary()
            lever_rows = [
                {
                    "key": v.key, "label": v.label, "gives_up": v.gives_up,
                    "current": round(v.current, 4),
                    "required": round(v.required, 4) if v.required is not None else None,
                    "reachable": v.reachable,
                    "coupon_at_limit": (
                        round(v.coupon_at_limit, 6) if v.coupon_at_limit is not None else None
                    ),
                }
                for v in report.levers
            ]

    vol_tau = m.get("atm_vol_tau")
    extrapolated = vol_tau is not None and prop.maturity > vol_tau * (1.0 + _VOL_TAU_SLACK)
    warning = None
    if extrapolated and vol_tau:
        warning = (
            f"This note matures in {prop.maturity:.2f}y, but the volatility surface is only "
            f"trusted out to {vol_tau:.2f}y ({vol_tau * 365:.0f} days) on today's quotes. The "
            f"price beyond that is the surface extrapolating, not the market speaking — treat "
            f"it as indicative and re-solve when longer-dated quotes are available."
        )
    elif not m.get("atm_vol_reliable", True):
        warning = (
            "No expiry cleared the calibration tolerance today; the pricing volatility is taken "
            "from the longest slice available and is unsupported by a reliable fit."
        )

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
        x_label=(
        "annual coupon (%)" if is_coupon
        else "knock-in barrier (fraction of spot)" if prop.solve_for == SolveFor.KNOCK_IN
        else "participation (×)"
    ),
        pv_curve=curve,
        coupon_shortfall=shortfall,
        manufacture_summary=manufacture_summary,
        levers=lever_rows,
        vol_tau=round(vol_tau, 4) if vol_tau is not None else None,
        vol_extrapolated=extrapolated,
        data_warning=warning,
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


# --- live desk: snapshot info, hedge recommendations, paper execution, alerts (Phase 5) -----
# In-process desk state: one paper book and one alert engine per server. Fine for a
# single-user desk terminal; move to a store if the app ever goes multi-user.
_DELTA_LIMIT = float(os.environ.get("SPDT_DELTA_LIMIT", "1000000"))
_VEGA_LIMIT = float(os.environ.get("SPDT_VEGA_LIMIT", "500000"))
_QUOTE_MAX_AGE_S = float(os.environ.get("SPDT_QUOTE_MAX_AGE_S", "30"))
_QUOTE_MAX_FUTURE_SKEW = float(os.environ.get("SPDT_QUOTE_MAX_FUTURE_SKEW", "5"))
_RECOMMENDATION_TTL_S = float(os.environ.get("SPDT_RECOMMENDATION_TTL_S", "30"))

_paper = PaperBroker()
_alert_engine = AlertEngine()
_desk_state_lock = threading.RLock()


@dataclasses.dataclass
class _RecommendationState:
    recommendation: HedgeRecommendation
    quotes: dict[tuple[int, int], Quote]
    created_monotonic: float
    execution_state: str = "PROPOSED"
    execution_result: dict | None = None


_recommendations: dict[str, _RecommendationState] = {}

# Every instrument we have hedged with, keyed like paper positions. Futures carry their
# static per-unit greeks; options carry their terms so they can be re-marked off the desk
# model on every read (a frozen option delta goes stale as spot moves — that's gamma).
_hedge_specs: dict[tuple[int, int], dict] = {}

# The paper book must survive restarts — pickled atomically after every execution.
_PAPER_STATE_PATH = os.environ.get("SPDT_PAPER_STATE", "dashboard_data/paper_state.pkl")


def _save_paper_state() -> None:
    try:
        os.makedirs(os.path.dirname(_PAPER_STATE_PATH) or ".", exist_ok=True)
        tmp = _PAPER_STATE_PATH + ".tmp"
        with _desk_state_lock, open(tmp, "wb") as f:
            pickle.dump({"paper": _paper, "hedge_specs": dict(_hedge_specs)}, f)
        os.replace(tmp, _PAPER_STATE_PATH)
    except Exception as exc:  # noqa: BLE001 — persistence must never break an execution
        print(f"spdt: paper state save failed: {exc}")


def _load_paper_state() -> None:
    global _paper
    try:
        with open(_PAPER_STATE_PATH, "rb") as f:
            state = pickle.load(f)
    except FileNotFoundError:
        return
    except Exception as exc:  # noqa: BLE001 — a stale/incompatible file starts fresh
        print(f"spdt: paper state load failed (starting fresh): {exc}")
        return
    _paper = state["paper"]
    _hedge_specs.update(state["hedge_specs"])


_load_paper_state()


def _chain_vol(d: dict, strike: float, expiry: date, is_call: bool) -> float:
    """IV of the calibrated chain row nearest (expiry, strike) — ATM vol when none usable."""
    rows = [r for r in d.get("option_chain", [])
            if r["type"] == ("CE" if is_call else "PE") and r["iv"] is not None]
    if not rows:
        return d["model"]["atm_vol"]
    best = min(rows, key=lambda r: (abs(date.fromisoformat(r["expiry"]).toordinal() - expiry.toordinal()),
                                    abs(r["strike"] - strike)))
    return float(best["iv"])


def _option_greeks(d: dict, spec: dict) -> dict[str, float]:
    """Per-unit greeks of an option hedge spec, marked off the desk model + chain smile."""
    tau = max((spec["expiry"] - date.today()).days, 0) / 365.0
    vol = _chain_vol(d, spec["strike"], spec["expiry"], spec["is_call"])
    m = d["model"]
    return vanilla_spot_greeks(d["spot"], spec["strike"], tau, vol, m["r"], m["q"], spec["is_call"])


def _paper_hedge_greeks(d: dict) -> dict[str, float]:
    """Greeks carried by the paper hedge book (Σ position qty × per-unit greek)."""
    totals = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "vanna": 0.0, "volga": 0.0}
    with _desk_state_lock:
        positions = [(key, pos.qty) for key, pos in _paper.positions.items()]
        specs = dict(_hedge_specs)
    for key, qty in positions:
        spec = specs.get(key, {"delta": 1.0, "vega": 0.0})
        g = _option_greeks(d, spec) if spec.get("strike") is not None else \
            {"delta": spec["delta"], "vega": spec["vega"]}
        for name in totals:
            totals[name] += qty * g.get(name, 0.0)
    return totals


def _hedged_net_greeks(d: dict) -> dict:
    """The book's net greeks with executed paper hedges folded in — the desk's true risk."""
    greeks = dict(d["net_greeks"])
    for name, value in _paper_hedge_greeks(d).items():
        greeks[name] = greeks.get(name, 0.0) + value
    return greeks


def _hedge_mark(d: dict, spec: dict) -> float:
    """Model mark of one hedge unit: options priced on the chain smile, futures at carry."""
    spot, m = d["spot"], d["model"]
    if spec.get("strike") is not None:
        tau = max((spec["expiry"] - date.today()).days, 0) / 365.0
        vol = _chain_vol(d, spec["strike"], spec["expiry"], spec["is_call"])
        fwd = spot * exp((m["r"] - m["q"]) * tau)
        return bs_price(fwd, spec["strike"], tau, vol, exp(-m["r"] * tau), spec["is_call"])
    tau = max((spec["expiry"] - date.today()).days, 0) / 365.0 if spec.get("expiry") else 0.0
    return spot * exp((m["r"] - m["q"]) * tau)


def _paper_hedge_pnl(d: dict) -> dict[str, float]:
    """The paper hedge book's P&L, marked on the desk model — folded into the desk NAV."""
    realized = unrealized = fees = 0.0
    with _desk_state_lock:
        positions = [(key, pos.qty, pos.avg_price, pos.realized_pnl, pos.fees_paid)
                     for key, pos in _paper.positions.items()]
        specs = dict(_hedge_specs)
    for key, qty, avg_price, position_realized, position_fees in positions:
        realized += position_realized
        fees += position_fees
        if qty:
            unrealized += qty * (_hedge_mark(d, specs.get(key, {})) - avg_price)
    return {"realized": realized, "unrealized": unrealized, "fees": fees,
            "total": realized + unrealized - fees}


class InstrumentIn(BaseModel):
    """A tradable hedge instrument with its current quote and per-unit Greeks."""

    instrument_id: int = Field(gt=0)
    segment: int = Field(default=2, gt=0)  # NSEFO
    symbol: str = ""
    bid: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    ask: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    ltp: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    bid_qty: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    ask_qty: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    quote_timestamp: datetime
    lot_size: int = Field(default=1, gt=0)
    delta: float = Field(default=1.0, allow_inf_nan=False)
    vega: float = Field(default=0.0, allow_inf_nan=False)
    # Option terms — supply all three and the executed position is re-marked off the desk
    # model on every desk read instead of carrying its recommend-time greeks forever.
    strike: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    expiry: date | None = None
    option_type: str | None = Field(default=None, pattern="^(CE|PE)$")

    @model_validator(mode="after")
    def validate_market(self):
        if self.bid is None and self.ask is None and self.ltp is None:
            raise ValueError("instrument requires at least one positive price")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid must not exceed ask")
        if self.quote_timestamp.tzinfo is None:
            raise ValueError("quote_timestamp must include a timezone")
        # expiry alone is fine (futures carry-mark); option-ness needs all three terms
        if (self.strike is not None or self.option_type is not None) and \
                None in (self.strike, self.expiry, self.option_type):
            raise ValueError("strike, expiry and option_type must be given together")
        return self


class HedgeRequest(BaseModel):
    future: InstrumentIn
    option: InstrumentIn | None = None  # supplied → delta-vega hedge, else delta-only
    book_delta: float | None = Field(default=None, allow_inf_nan=False)
    book_vega: float | None = Field(default=None, allow_inf_nan=False)
    max_notional: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_hedge_ratios(self):
        if self.future.delta == 0:
            raise ValueError("future delta must be non-zero")
        if self.option is not None and self.option.vega == 0 and self.option.strike is None:
            # with option terms present the endpoint fills delta/vega from the desk model
            raise ValueError("option vega must be non-zero")
        return self


class ExecuteRequest(BaseModel):
    recommendation_id: str


def _hedge_instrument(spec: InstrumentIn) -> HedgeInstrument:
    ref = InstrumentRef(exchange_segment=spec.segment, exchange_instrument_id=spec.instrument_id,
                        symbol=spec.symbol)
    timestamp = spec.quote_timestamp.astimezone(timezone.utc)
    age_s = (datetime.now(timezone.utc) - timestamp).total_seconds()
    stale = age_s > _QUOTE_MAX_AGE_S or age_s < -_QUOTE_MAX_FUTURE_SKEW
    quote = Quote(instrument=ref, ltp=spec.ltp, bid=spec.bid, ask=spec.ask,
                  bid_qty=spec.bid_qty, ask_qty=spec.ask_qty, timestamp=timestamp, stale=stale,
                  source="manual")
    return HedgeInstrument(quote=quote, delta=spec.delta, vega=spec.vega, lot_size=spec.lot_size)


def _rec_json(rec: HedgeRecommendation, execution_state: str | None = None) -> dict:
    payload = {
        "recommendation_id": rec.recommendation_id,
        "created_at": rec.created_at.isoformat(),
        "objective": rec.objective,
        "current_greeks": rec.current_greeks,
        "expected_greeks": rec.expected_greeks,
        "orders": [
            {"instrument_id": o.instrument.exchange_instrument_id,
             "segment": o.instrument.exchange_segment, "symbol": o.instrument.symbol,
             "side": o.side.name, "qty": o.qty}
            for o in rec.orders
        ],
        "estimated_cost": rec.estimated_cost,
        "approval_state": rec.approval_state,
        "reason_codes": list(rec.reason_codes),
    }
    if execution_state is not None:
        payload["execution_state"] = execution_state
    return payload


def _alert_json(alert) -> dict:
    return {
        "id": alert.id, "severity": alert.severity, "category": alert.category,
        "message": alert.message, "metric": alert.metric, "value": alert.value,
        "threshold": alert.threshold, "trade_id": alert.trade_id, "status": alert.status,
        "timestamp": alert.timestamp.isoformat() if alert.timestamp else None,
    }


_EXPLORER_LEVELS = tuple(round(0.4 + 0.1 * i, 1) for i in range(13))  # 0.4 … 1.6


def _explorer_summary(req: PriceRequest, outcomes: dict) -> list[str]:
    """Plain-English lines a non-quant can read. Facts from the same engine as the price."""
    p = req.params
    obs = req.observation_times or []
    per_year = round(len(obs) / max(obs)) if obs else 0
    lines: list[str] = []
    if p.get("coupon_rate") and per_year:
        lines.append(
            f"Pays a {p['coupon_rate'] * per_year * 100:.1f}% p.a. coupon, "
            f"{per_year}× per year."
        )
    if p.get("knock_in"):
        lines.append(
            f"Your capital is protected unless the index falls below "
            f"{p['knock_in'] * 100:.0f}% of its starting level; beyond that you take the fall."
        )
    if p.get("autocall_level"):
        lines.append(
            f"Redeems early if the index is at or above {p['autocall_level'] * 100:.0f}% "
            f"of start on an observation date "
            f"(model-implied chance: {outcomes['prob_autocall_pct']:.0f}%)."
        )
    if p.get("protection"):
        lines.append(
            f"{p['protection'] * 100:.0f}% of your capital is protected at maturity; "
            f"upside participation is {p.get('participation', 1.0):.2f}×."
        )
    lines.append(
        f"Model-implied chance of losing money: {outcomes['prob_loss_pct']:.1f}%. "
        f"In the worst 5% of scenarios the return is {outcomes['p5_return_pct']:.1f}% or lower."
    )
    return lines


@app.post("/api/explorer", dependencies=[Depends(require_token)])
def payoff_explorer(req: PriceRequest) -> dict:
    """Client-facing view of a product: payoff sweep, outcome odds, coupon schedule, plain English."""
    d = _desk()
    spot, m = d["spot"], d["model"]
    model = BlackScholes(spot=spot, r=m["r"], q=m["q"], sigma=m["atm_vol"])
    product = _build_product(req, spot)
    pv = price_mc(product, model, n_paths=20_000, seed=7)
    outcomes = outcome_profile(product, model, n_paths=20_000, seed=7)
    coupon_rate = req.params.get("coupon_rate")
    return {
        "pv": pv.price,
        "notional": req.notional,
        "payoff": [
            {"terminal_level": s.terminal_level, "payment_pct": s.payment_pct,
             "ki_breached": s.ki_breached}
            for s in terminal_scenarios(product, _EXPLORER_LEVELS)
        ],
        "outcomes": outcomes,
        "coupon_schedule": [
            {"time": t, "amount_pct": coupon_rate * 100.0}
            for t in (req.observation_times or [])
        ] if coupon_rate else [],
        "summary": _explorer_summary(req, outcomes),
        "disclaimer": (
            "Probabilities are model-implied (risk-neutral Black-Scholes at the desk's "
            "current marks), not forecasts. Educational illustration — not investment advice."
        ),
    }


@app.get("/api/live/option-chain")
def live_option_chain() -> dict:
    """The chain the desk is calibrated on: nearest expiries, priced strikes, inverted IVs."""
    d = _desk()
    return {"as_of": d["as_of"], "data_source": d["data_source"],
            "underlying": d["underlying"], "spot": d["spot"],
            "rows": d.get("option_chain", [])}


_xts_quote_client = None
_xts_quote_lock = threading.Lock()
_replay_tape: tuple[dict, list[dict]] | None = None  # (meta, tick rows), loaded once


def _replay_state() -> tuple[dict, list[dict]]:
    global _replay_tape
    if _replay_tape is None:
        from spdt.data.replay import load_tape

        _replay_tape = load_tape(os.path.join(_REPLAY_DIR, "tick_tape.jsonl"))
    return _replay_tape


def _live_quote(symbol: str) -> dict:
    """Front-future touchline for ``symbol`` via the XTS market-data API (login cached)."""
    if _REPLAY:  # the recorded day's static quote, re-marked at the current tape prices
        from spdt.data.replay import replay_quote

        return replay_quote(*_replay_state(), now=datetime.now(timezone.utc))
    from spdt.data.ingest.xts import XTSMarketDataClient

    global _xts_quote_client
    with _xts_quote_lock:
        if _xts_quote_client is None:
            from tempfile import gettempdir
            _xts_quote_client = XTSMarketDataClient(timeout=300.0,
                                                    master_cache_dir=gettempdir())
        client = _xts_quote_client

        def fetch() -> dict:
            if not client.token:
                client.login()
            # Pair each ref with its expiry so the not-None filter is carried in the value
            # rather than re-derived: an undated contract must never reach min() or isoformat().
            dated = [
                (r.expiry, r) for r in client.instruments("NSEFO")
                if r.symbol == symbol and r.instrument_type == "FUTIDX"
                and r.expiry is not None and r.expiry >= date.today()
            ]
            if not dated:
                raise HTTPException(status.HTTP_404_NOT_FOUND,
                                    f"no live future found for {symbol!r}")
            front_expiry, front = min(dated, key=lambda pair: pair[0])
            now = datetime.now(timezone.utc)
            quotes = client.quotes([front], now=now, max_age_s=_QUOTE_MAX_AGE_S)
            if not quotes:
                raise HTTPException(status.HTTP_404_NOT_FOUND,
                                    f"broker returned no quote for {front.description}")
            q = quotes[0]
            age_s = (now - q.timestamp).total_seconds() if q.timestamp else None
            return {
                "segment": front.exchange_segment,
                "instrument_id": front.exchange_instrument_id,
                "symbol": front.symbol,
                "description": front.description,
                "expiry": front_expiry.isoformat(),
                "lot_size": front.lot_size,
                "ltp": q.ltp, "bid": q.bid, "ask": q.ask,
                "bid_qty": q.bid_qty, "ask_qty": q.ask_qty,
                "timestamp": q.timestamp.isoformat() if q.timestamp else None,
                "age_s": round(age_s, 1) if age_s is not None else None,
                "stale": q.stale,
            }

        try:
            return fetch()
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 — one re-login retry covers expired tokens
            client.token = None
            return fetch()


@app.get("/api/live/quote")
def live_quote(symbol: str = "NIFTY") -> dict:
    """Live front-future quote for the hedge ticket. Only meaningful on the XTS feed."""
    if not _feed():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "live quotes need SPDT_LIVE=1 and SPDT_SOURCE=xts (or =replay)")
    return _live_quote(symbol)


# --- live tick feed: spot + front future pushed to the browser over SSE --------------------
# ponytail: a 2s REST poll of two instruments, not the XTS socket.io stream — the socket
# needs a legacy socket.io client and can only be proven out during market hours; swap the
# body of _fetch_tick for a socket-fed cache if tick-level latency ever matters.
_TICK_INTERVAL_S = float(os.environ.get("SPDT_TICK_INTERVAL_S", "2"))
_latest_tick: dict | None = None
_tick_clients = 0
_ticker_running = False
_tick_lock = threading.Lock()
_tick_refs: tuple | None = None  # (resolved_on, index_ref, future_ref, atm_ce, atm_pe)
_iv_baseline: tuple | None = None  # (desk_built_at, straddle_iv at that mark)


def _resolve_tick_refs(client, underlying: str = "NIFTY"):
    """Index, front-future, and front-expiry ATM straddle refs.

    Re-resolved daily (expiry rolls) and whenever spot drifts >1% off the picked ATM
    strike (see :func:`_fetch_tick`).
    """
    global _tick_refs
    today = date.today()
    if _tick_refs is not None and _tick_refs[0] == today:
        return _tick_refs[1:]
    index_name = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK"}.get(underlying, underlying)
    index = next(r for r in client.indexes() if r.symbol == index_name)
    fo_master = [r for r in client.instruments("NSEFO") if r.symbol == underlying]
    future = min(
        (r for r in fo_master if r.instrument_type == "FUTIDX"
         and r.expiry is not None and r.expiry >= today),
        key=lambda r: r.expiry,
    )
    # ATM straddle on the nearest option expiry strictly after today (T>0 for inversion)
    spot_guess = (_cache.payload or {}).get("spot")
    if not spot_guess:
        spot_quotes = client.quotes([index], now=datetime.now(timezone.utc),
                                    max_age_s=_QUOTE_MAX_AGE_S)
        spot_guess = spot_quotes[0].ltp if spot_quotes and spot_quotes[0].ltp else None
    atm_ce = atm_pe = None
    if spot_guess:
        options = [r for r in fo_master if r.option_type and r.strike is not None
                   and r.expiry is not None and r.expiry > today]
        if options:
            front_exp = min(r.expiry for r in options)
            strikes = sorted({r.strike for r in options if r.expiry == front_exp})
            atm_strike = min(strikes, key=lambda k: abs(k - spot_guess))
            legs = {r.option_type: r for r in options
                    if r.expiry == front_exp and r.strike == atm_strike}
            atm_ce, atm_pe = legs.get("CE"), legs.get("PE")
    _tick_refs = (today, index, future, atm_ce, atm_pe)
    return index, future, atm_ce, atm_pe


def _straddle_iv(quotes: dict, atm_ce, atm_pe, spot: float) -> float | None:
    """Black-76 IV averaged over the invertible ATM legs; None when nothing inverts."""
    from math import exp as _exp

    from spdt.data.curate.bs_inversion import implied_vol
    from spdt.core.types import year_fraction

    model = (_cache.payload or {}).get("model", {})
    r, q = model.get("r", 0.065), model.get("q", 0.013)
    ivs = []
    for leg in (atm_ce, atm_pe):
        quote = quotes.get(leg.exchange_instrument_id) if leg is not None else None
        if quote is None:
            continue
        mid = ((quote.bid + quote.ask) / 2.0
               if quote.bid is not None and quote.ask is not None and quote.bid <= quote.ask
               else quote.ltp)
        if mid is None:
            continue
        tau = year_fraction(date.today(), leg.expiry)
        forward = spot * _exp((r - q) * tau)
        try:
            ivs.append(implied_vol(mid, forward, leg.strike, tau,
                                   _exp(-r * tau), leg.option_type == "CE"))
        except ValueError:
            continue  # stale/crossed print — skip the leg
    return sum(ivs) / len(ivs) if ivs else None


def _fetch_tick() -> dict:
    """One tick: index spot, front-future touchline, and live ATM straddle vol."""
    if _REPLAY:  # the recorded session's tick at this wall-clock position
        from spdt.data.replay import replay_tick

        return replay_tick(_replay_state()[1], datetime.now(timezone.utc))
    from spdt.data.ingest.xts import XTSMarketDataClient

    global _xts_quote_client, _tick_refs, _iv_baseline
    with _xts_quote_lock:
        if _xts_quote_client is None:
            from tempfile import gettempdir
            _xts_quote_client = XTSMarketDataClient(timeout=300.0,
                                                    master_cache_dir=gettempdir())
        client = _xts_quote_client
        if not client.token:
            client.login()
        index, future, atm_ce, atm_pe = _resolve_tick_refs(client)
        now = datetime.now(timezone.utc)
        wanted = [r for r in (index, future, atm_ce, atm_pe) if r is not None]
        quotes = {q.instrument.exchange_instrument_id: q
                  for q in client.quotes(wanted, now=now, max_age_s=_QUOTE_MAX_AGE_S)}
    spot_q = quotes.get(index.exchange_instrument_id)
    fut_q = quotes.get(future.exchange_instrument_id)
    spot = spot_q.ltp if spot_q else None

    atm_iv = dvol = None
    if spot is not None and atm_ce is not None:
        if abs(spot / atm_ce.strike - 1.0) > 0.01:
            _tick_refs = None  # spot drifted off the strike — re-pick ATM next tick
        atm_iv = _straddle_iv(quotes, atm_ce, atm_pe, spot)
        if atm_iv is not None:
            # vol move is measured against the straddle IV captured at the current desk
            # mark, so dvol resets to ~0 every time the desk re-marks (it absorbed the move)
            if _iv_baseline is None or _iv_baseline[0] != _cache.built_at:
                _iv_baseline = (_cache.built_at, atm_iv)
            dvol = atm_iv - _iv_baseline[1]

    ts = (fut_q.timestamp if fut_q and fut_q.timestamp else
          spot_q.timestamp if spot_q else None)
    return {
        "spot": spot,
        "future": {"description": future.description,
                   "ltp": fut_q.ltp if fut_q else None,
                   "bid": fut_q.bid if fut_q else None,
                   "ask": fut_q.ask if fut_q else None},
        "atm_iv": round(atm_iv, 6) if atm_iv is not None else None,
        "dvol": round(dvol, 6) if dvol is not None else None,
        "timestamp": ts.isoformat() if ts else None,
        "age_s": round((datetime.now(timezone.utc) - ts).total_seconds(), 1) if ts else None,
        "stale": spot_q.stale if spot_q else True,
    }


def _ticker_loop() -> None:  # pragma: no cover — thin poll loop; _fetch_tick is tested
    global _latest_tick, _ticker_running
    while True:
        with _tick_lock:
            if _tick_clients == 0:
                _ticker_running = False
                return
        try:
            _latest_tick = _fetch_tick()
            _record_tick(_latest_tick)
        except Exception as exc:  # noqa: BLE001 — a failed poll must not kill the feed
            print(f"spdt-ticker: poll failed: {exc}")
        time.sleep(_TICK_INTERVAL_S)


# Rolling tick history for the realized-vol tracker (~3h of 2s ticks).
# ponytail: accrues only while the app streams ticks — add a standalone session
# sampler if headless realized vol ever matters.
_tick_history: deque = deque(maxlen=int(os.environ.get("SPDT_VOL_HISTORY_MAX", "5400")))


def _record_tick(tick: dict) -> None:
    spot = tick.get("spot")
    if spot:
        _tick_history.append((time.time(), float(spot), tick.get("atm_iv")))


@app.get("/api/live/vol-tracker")
def vol_tracker() -> dict:
    """Realized (tick quadratic variation) vs implied (live ATM straddle) volatility.

    The spread is the desk's vol carry; with the book's gamma it prices what the
    short-gamma book earns or bleeds per day at the current gap.
    """
    if not _feed():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "the vol tracker needs SPDT_LIVE=1 and SPDT_SOURCE=xts (or =replay)")
    samples = list(_tick_history)
    spots = [(t, s) for t, s, _ in samples]
    now = time.time()
    rv_session = realized_vol(spots)
    rv_30m = realized_vol([x for x in spots if x[0] >= now - 1800])
    implied = next((iv for _, _, iv in reversed(samples) if iv is not None), None)
    out: dict = {
        "n_samples": len(samples),
        "window_minutes": round((spots[-1][0] - spots[0][0]) / 60.0, 1) if len(spots) > 1 else 0.0,
        "realized_vol": rv_session,
        "realized_vol_30m": rv_30m,
        "implied_atm_vol": implied,
        "spread": implied - rv_session if implied is not None and rv_session is not None else None,
    }
    if out["spread"] is not None and implied is not None and rv_session is not None:
        try:  # what the (hedged) book's gamma earns/bleeds per day at this vol gap
            d = _desk()
            gamma = _hedged_net_greeks(d)["gamma"]
            spot = spots[-1][1]
            out["gamma_carry_per_day"] = (
                0.5 * gamma * spot * spot * (implied**2 - rv_session**2) / 252.0)
        except Exception:  # noqa: BLE001 — carry is a bonus stat, never a 500
            out["gamma_carry_per_day"] = None
    # chart series, downsampled; each point carries its own trailing-30m realized vol
    step = max(1, -(-len(samples) // 240))  # ceil-divide so the series stays ≤240 points
    series = []
    for i in range(0, len(samples), step):
        t, s, iv = samples[i]
        trailing = [x for x in spots if t - 1800 <= x[0] <= t]
        series.append({"t": datetime.fromtimestamp(t, tz=timezone.utc).isoformat(),
                       "spot": s, "iv": iv, "rv": realized_vol(trailing)})
    out["series"] = series
    return out


@app.get("/api/live/ticks")
def live_ticks() -> StreamingResponse:
    """SSE stream of spot/front-future ticks. The poll loop runs only while someone listens."""
    if not _feed():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "live ticks need SPDT_LIVE=1 and SPDT_SOURCE=xts (or =replay)")

    def stream():
        global _tick_clients, _ticker_running
        import json as json_mod
        with _tick_lock:
            _tick_clients += 1
            if not _ticker_running:
                _ticker_running = True
                threading.Thread(target=_ticker_loop, daemon=True, name="spdt-ticker").start()
        try:
            while True:
                if _latest_tick is not None:
                    yield f"data: {json_mod.dumps(_latest_tick)}\n\n"
                time.sleep(_TICK_INTERVAL_S)
        finally:
            with _tick_lock:
                _tick_clients -= 1

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.get("/api/live/snapshot")
def live_snapshot() -> dict:
    """Provenance of the market data the desk is currently running on."""
    d = _desk()
    return {
        "as_of": d["as_of"], "data_date": d["data_date"], "data_source": d["data_source"],
        "underlying": d["underlying"], "spot": d["spot"],
        "desk_age_s": round(time.time() - _cache.built_at, 1),
    }


@app.get("/api/desk/radar")
def barrier_radar(spot: float | None = None) -> dict:
    """Barrier proximity radar: distance and model-implied touch odds per booked note.

    ``spot`` overrides the desk mark so the frontend can re-rank on live ticks. Vols come
    from the calibrated chain at each barrier's own strike; probabilities are continuous-
    monitoring GBM closed forms — conservative vs the notes' discrete observation dates.
    """
    d = _desk()
    s = spot if spot is not None and spot > 0 else d["spot"]
    m = d["model"]
    rows = []
    for p in d["positions"]:
        if p.get("maturity") is None:
            continue  # non-note rows (e.g. worst-of sub-book summaries) have no schedule
        fixing = p.get("initial_fixing") or d["spot"]
        elapsed = p.get("elapsed_years", 0.0)
        tau = max(p["maturity"] - elapsed, 0.0)
        row: dict = {"trade_id": p.get("trade_id"), "product_type": p.get("product_type"),
                     "direction": p.get("direction", "short"), "years_left": round(tau, 3)}
        if p.get("knock_in"):
            level = p["knock_in"] * fixing
            vol = _chain_vol(d, level, date.today() + timedelta(days=round(tau * 365)), False)
            hit = 1.0 if p.get("barrier_breached") else \
                barrier_hit_probability(s, level, tau, vol, m["r"], m["q"])
            row.update(
                ki_level=round(level, 1),
                ki_distance_pct=round((s - level) / s * 100.0, 2),
                ki_sigma_distance=round(log(s / level) / (vol * sqrt(tau)), 2)
                if tau > 0 and vol > 0 and s > level else 0.0,
                ki_hit_prob_pct=round(100.0 * hit, 1),
            )
        obs = [t - elapsed for t in (p.get("observation_times") or []) if t > elapsed]
        if p.get("autocall") and obs:
            level = p["autocall"] * fixing
            next_obs = min(obs)
            vol = _chain_vol(d, level, date.today() + timedelta(days=round(next_obs * 365)), True)
            row.update(
                autocall_level=round(level, 1),
                next_obs_days=round(next_obs * 365),
                autocall_prob_pct=round(
                    100.0 * terminal_above_probability(s, level, next_obs, vol, m["r"], m["q"]), 1),
            )
        if "ki_level" not in row and "autocall_level" not in row:
            continue
        hit_prob = row.get("ki_hit_prob_pct", 0.0)
        distance = row.get("ki_distance_pct")
        row["severity"] = ("CRITICAL" if hit_prob >= 50.0 or (distance is not None and distance < 5.0)
                           else "WARNING" if hit_prob >= 25.0 or (distance is not None and distance < 10.0)
                           else "INFO")
        rows.append(row)
    rows.sort(key=lambda r_: (-r_.get("ki_hit_prob_pct", 0.0), r_.get("ki_distance_pct", 1e9)))
    return {"as_of": d["as_of"], "spot": s, "rows": rows}


# --- auto-hedger: watch the hedged net delta, propose (never execute) when it drifts ------
# Paper-only and approval-gated by design: proposals land in the normal recommendation
# queue for a human to execute. SPDT_AUTOHEDGE=1 arms it at startup.
class _AutohedgeState(TypedDict):
    """Auto-hedger state, typed field by field.

    As a bare dict literal this infers as ``dict[str, float | bool | None]`` — the union of its
    five value types — so every read is that union and every use downstream fails: the threshold
    cannot be compared, the interval cannot be slept on, and the proposal cannot be indexed.
    Naming the fields keeps the dict syntax and gives each key back its own type.
    """

    enabled: bool
    delta_threshold: float
    interval_s: float
    last_proposal: dict[str, Any] | None
    last_error: str | None


_autohedge: _AutohedgeState = {
    "enabled": os.environ.get("SPDT_AUTOHEDGE", "").lower() in ("1", "true", "yes"),
    "delta_threshold": float(os.environ.get("SPDT_AUTOHEDGE_DELTA", "500")),
    "interval_s": float(os.environ.get("SPDT_AUTOHEDGE_INTERVAL_S", "30")),
    "last_proposal": None,
    "last_error": None,
}
_autohedge_thread: threading.Thread | None = None


def _autohedge_step() -> dict | None:
    """One watch cycle: propose a delta hedge if the hedged book has drifted past threshold."""
    d = _desk()
    delta = _hedged_net_greeks(d)["delta"]
    if abs(delta) < _autohedge["delta_threshold"]:
        return None
    last = _autohedge["last_proposal"]
    if last is not None:
        state = _recommendations.get(last["recommendation_id"])
        if (state is not None and state.execution_state == "PROPOSED"
                and time.monotonic() - state.created_monotonic <= _RECOMMENDATION_TTL_S):
            return None  # a live proposal is already waiting for approval
    q = _live_quote(d["underlying"])  # raises off the feed — caught by the loop
    future = _hedge_instrument(InstrumentIn(
        instrument_id=q["instrument_id"], segment=q["segment"], symbol=q["description"],
        bid=q["bid"], ask=q["ask"], ltp=q["ltp"],
        quote_timestamp=datetime.fromisoformat(q["timestamp"]),
        lot_size=q["lot_size"] or 1,
    ))
    rec = recommend_delta_hedge(delta, future)
    with _desk_state_lock:
        spec: dict = {"delta": 1.0, "vega": 0.0}
        if q.get("expiry"):
            spec["expiry"] = date.fromisoformat(q["expiry"])
        _hedge_specs[(q["segment"], q["instrument_id"])] = spec
        _recommendations[rec.recommendation_id] = _RecommendationState(
            recommendation=rec,
            quotes={(q["segment"], q["instrument_id"]): future.quote},
            created_monotonic=time.monotonic(),
        )
        _alert_engine.update([
            greek_limit_alert("delta", value=delta, limit=_autohedge["delta_threshold"]),
        ])
    proposal = {"recommendation_id": rec.recommendation_id, "book_delta": delta,
                "created_at": rec.created_at.isoformat(),
                "orders": [{"symbol": o.instrument.symbol, "side": o.side.name, "qty": o.qty}
                           for o in rec.orders]}
    _autohedge["last_proposal"] = proposal
    return proposal


def _autohedge_loop() -> None:  # pragma: no cover — thin timer; the step is tested
    while True:
        time.sleep(_autohedge["interval_s"])
        if not _autohedge["enabled"] or not (_LIVE and _SOURCE == "xts"):
            continue
        try:
            _autohedge_step()
            _autohedge["last_error"] = None
        except Exception as exc:  # noqa: BLE001 — the watcher must outlive feed hiccups
            _autohedge["last_error"] = str(exc)


def _ensure_autohedge_thread() -> None:
    global _autohedge_thread
    if _autohedge_thread is None or not _autohedge_thread.is_alive():
        _autohedge_thread = threading.Thread(target=_autohedge_loop, daemon=True,
                                             name="spdt-autohedge")
        _autohedge_thread.start()


if _autohedge["enabled"]:
    _ensure_autohedge_thread()


class AutohedgeIn(BaseModel):
    enabled: bool
    delta_threshold: float | None = Field(default=None, gt=0, allow_inf_nan=False)


@app.get("/api/autohedge")
def autohedge_status() -> dict:
    return {
        "enabled": _autohedge["enabled"],
        "delta_threshold": _autohedge["delta_threshold"],
        "interval_s": _autohedge["interval_s"],
        "last_proposal": _autohedge["last_proposal"],
        "last_error": _autohedge["last_error"],
    }


@app.post("/api/autohedge", dependencies=[Depends(require_token)])
def autohedge_configure(req: AutohedgeIn) -> dict:
    _autohedge["enabled"] = req.enabled
    if req.delta_threshold is not None:
        _autohedge["delta_threshold"] = req.delta_threshold
    if req.enabled:
        _ensure_autohedge_thread()
    return autohedge_status()


@app.post("/api/hedges/recommend", dependencies=[Depends(require_token)])
def hedge_recommend(req: HedgeRequest) -> dict:
    """Size a hedge for the book's (or the given) Greeks; also refreshes Greek-limit alerts."""
    d = _desk()
    greeks = _hedged_net_greeks(d)
    delta = req.book_delta if req.book_delta is not None else greeks["delta"]
    vega = req.book_vega if req.book_vega is not None else greeks["vega"]
    opt = req.option
    if opt is not None and opt.strike is not None and "vega" not in opt.model_fields_set:
        # terms given without explicit greeks → per-unit greeks from the desk's own model
        g = _option_greeks(d, {"strike": opt.strike, "expiry": opt.expiry,
                               "is_call": opt.option_type == "CE"})
        if g["vega"] == 0.0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "option has no vega at this strike/expiry — not a vega hedge")
        opt.delta, opt.vega = g["delta"], g["vega"]
    future = _hedge_instrument(req.future)
    instruments = [future]
    if req.option is not None:
        option = _hedge_instrument(req.option)
        instruments.append(option)
        rec = recommend_delta_vega_hedge(delta, vega, future, option,
                                         max_notional=req.max_notional)
    else:
        rec = recommend_delta_hedge(delta, future, max_notional=req.max_notional)
    with _desk_state_lock:
        for leg in (req.future, req.option):
            if leg is None:
                continue
            spec: dict = {"delta": leg.delta, "vega": leg.vega}
            if leg.strike is not None:
                spec.update(strike=leg.strike, expiry=leg.expiry, is_call=leg.option_type == "CE")
            elif leg.expiry is not None:
                spec["expiry"] = leg.expiry  # future: carry-adjust its mark to expiry
            _hedge_specs[(leg.segment, leg.instrument_id)] = spec
        _recommendations[rec.recommendation_id] = _RecommendationState(
            recommendation=rec,
            quotes={
                (i.quote.instrument.exchange_segment, i.quote.instrument.exchange_instrument_id): i.quote
                for i in instruments
            },
            created_monotonic=time.monotonic(),
        )
        _alert_engine.update([
            greek_limit_alert("delta", value=greeks["delta"], limit=_DELTA_LIMIT),
            greek_limit_alert("vega", value=greeks["vega"], limit=_VEGA_LIMIT),
        ])
    return _rec_json(rec)


@app.get("/api/hedges/recommendations")
def hedge_recommendations() -> list[dict]:
    with _desk_state_lock:
        return [
            _rec_json(state.recommendation, state.execution_state)
            for state in _recommendations.values()
        ]


@app.post("/api/execution/execute", dependencies=[Depends(require_token)])
def execute_recommendation(req: ExecuteRequest) -> dict:
    """Paper-execute a PROPOSED recommendation against the quotes it was sized on."""
    with _desk_state_lock:
        state = _recommendations.get(req.recommendation_id)
        if state is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown recommendation_id")
        if state.execution_state == "EXECUTED" and state.execution_result is not None:
            return state.execution_result
        rec = state.recommendation
        if rec.approval_state != "PROPOSED" or state.execution_state != "PROPOSED":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"recommendation is {state.execution_state}, not executable",
            )
        if time.monotonic() - state.created_monotonic > _RECOMMENDATION_TTL_S:
            state.execution_state = "EXPIRED"
            raise HTTPException(status.HTTP_409_CONFLICT, "recommendation has expired")
        now = datetime.now(timezone.utc)
        for quote in state.quotes.values():
            if quote.timestamp is None:
                state.execution_state = "EXPIRED"
                raise HTTPException(status.HTTP_409_CONFLICT, "recommendation quote has no timestamp")
            timestamp = quote.timestamp.astimezone(timezone.utc)
            age_s = (now - timestamp).total_seconds()
            if age_s > _QUOTE_MAX_AGE_S or age_s < -_QUOTE_MAX_FUTURE_SKEW:
                state.execution_state = "EXPIRED"
                raise HTTPException(status.HTTP_409_CONFLICT, "recommendation quote is stale")
        state.execution_state = "EXECUTING"
        try:
            results = []
            for intent in rec.orders:
                quote = state.quotes[
                    (intent.instrument.exchange_segment, intent.instrument.exchange_instrument_id)
                ]
                order = _paper.submit(intent, quote)
                results.append({"order_id": order.order_id, "status": order.status.value,
                                "filled_qty": order.filled_qty})
            response = {"recommendation_id": rec.recommendation_id, "orders": results}
            state.execution_result = response
            state.execution_state = "EXECUTED"
            _save_paper_state()
            if _cache.payload is not None:  # timeline row: the hedge moved the desk
                _record_desk_history(_cache.payload)
            return response
        except Exception:
            state.execution_state = "FAILED"
            raise


@app.get("/api/execution/blotter")
def execution_blotter() -> dict:
    """Paper orders, fills, and positions — the desk's execution state."""
    with _desk_state_lock:
        return {
        "orders": [
            {"order_id": o.order_id, "instrument_id": o.intent.instrument.exchange_instrument_id,
             "symbol": o.intent.instrument.symbol, "side": o.intent.side.name,
             "qty": o.intent.qty, "status": o.status.value, "filled_qty": o.filled_qty}
            for o in _paper.orders
        ],
        "fills": [
            {"order_id": f.order_id, "instrument_id": f.instrument.exchange_instrument_id,
             "side": f.side.name, "qty": f.qty, "price": f.price, "fees": f.fees,
             "timestamp": f.timestamp.isoformat()}
            for f in _paper.fills
        ],
        "positions": {
            f"{segment}:{instrument_id}": {
                "segment": segment,
                "instrument_id": instrument_id,
                "symbol": _paper.position_instruments[(segment, instrument_id)].symbol,
                "qty": p.qty, "avg_price": p.avg_price,
                "realized_pnl": p.realized_pnl, "fees_paid": p.fees_paid,
            }
            for (segment, instrument_id), p in _paper.positions.items()
        },
        }


class AttributionRequest(BaseModel):
    marks: dict[str, float] = {}  # "segment:instrument_id" → mark price


@app.post("/api/execution/attribution")
def execution_attribution_report(req: AttributionRequest) -> dict:
    """Split the paper book's P&L into realized / unrealized / fees / spread cost."""
    from spdt.execution.attribution import execution_attribution

    marks: dict[tuple[int, int], float] = {}
    for key, price in req.marks.items():
        segment, _, instrument_id = key.partition(":")
        marks[(int(segment), int(instrument_id))] = price
    return execution_attribution(_paper, marks=marks)


def _broker_client():
    """Factory seam so tests can stub the broker; real client reads SPDT_XTS_INTERACTIVE_*."""
    from spdt.execution.xts import XTSExecutionClient

    return XTSExecutionClient()


@app.get("/api/broker/state")
def broker_state() -> dict:
    """Read-only broker state + paper-vs-broker position reconciliation.

    Never 500s the dashboard: without credentials (or on any broker error) it reports
    ``connected: false`` with a reason, and the tab shows a clean not-connected state.
    """
    broker = _broker_client()
    if not broker.app_key or not broker.secret:
        return {"connected": False,
                "reason": "XTS interactive credentials not configured (SPDT_XTS_INTERACTIVE_*)"}
    try:
        if not broker.token:
            broker.login()
        orders = broker.orders()
        trades = broker.trades()
        positions = broker.positions()
        margins = broker.margins()
    except Exception as exc:  # noqa: BLE001 — surface the reason, keep the desk up
        return {"connected": False, "reason": str(exc)}

    broker_by_id = {p.exchange_instrument_id: p for p in positions}
    paper_by_id = {iid: (key, pos) for (seg, iid), pos in _paper.positions.items()
                   for key in [(seg, iid)]}
    reconciliation = []
    for instrument_id in sorted(set(broker_by_id) | set(paper_by_id)):
        b = broker_by_id.get(instrument_id)
        paper_entry = paper_by_id.get(instrument_id)
        p_qty = paper_entry[1].qty if paper_entry else 0.0
        b_qty = b.qty if b else 0.0
        if b is not None:
            symbol = b.symbol
        else:
            symbol = _paper.position_instruments[paper_entry[0]].symbol if paper_entry else ""
        reconciliation.append({
            "instrument_id": instrument_id,
            "symbol": symbol,
            "paper_qty": p_qty,
            "broker_qty": b_qty,
            "difference": b_qty - p_qty,
        })
    return {
        "connected": True,
        "orders": [dataclasses.asdict(o) for o in orders],
        "trades": [dataclasses.asdict(t) for t in trades],
        "positions": [dataclasses.asdict(p) for p in positions],
        "margins": dataclasses.asdict(margins),
        "reconciliation": reconciliation,
    }


@app.get("/api/alerts")
def alerts() -> dict:
    with _desk_state_lock:
        return {"open": [_alert_json(a) for a in _alert_engine.open_alerts],
                "history": [_alert_json(a) for a in _alert_engine.history]}


@app.post("/api/alerts/{alert_id}/ack", dependencies=[Depends(require_token)])
def acknowledge_alert(alert_id: str) -> dict:
    with _desk_state_lock:
        _alert_engine.acknowledge(alert_id)
    return {"status": "ok"}


# --- static front end -----------------------------------------------------------------------
# In production a single process serves the built React app (webapp/frontend/dist) at "/", so
# the SPA and its relative /api/* calls are same-origin (no CORS, no token needed). Mounted
# LAST so every /api/* route declared above still takes precedence over this catch-all. A no-op
# in dev, where there is no dist and Vite serves the UI on :5173 and proxies /api back here.

# --- cross-market surface: any underlying, any source -------------------------------------
# Deliberately separate from /api/desk. That endpoint builds a whole *book* — positions, NAV,
# P&L explain — denominated in one market; pointing it at SPX would fabricate an SPX book rather
# than show US data. This serves the market itself (spot, chain, calibrated surface with its fit
# quality) for any underlying, and touches none of the desk's cache, replay or history paths.

_MARKET_TTL = float(os.environ.get("SPDT_MARKET_TTL", "900"))
_market_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_market_lock = threading.Lock()

# Which engine serves which market. CBOE is delayed and current-only, so it can never answer a
# historical as_of; the Indian source is whatever the deployment is configured for.
#
# The fixed entries are the *index* underlyings. Single names are deliberately NOT enumerated
# here: which single stocks matter is not a matter of taste, it is whatever the US shelf is
# currently issuing against. Roughly two thirds of that shelf is worst-of on single stocks, and
# each leg needs its own vol before the note can be priced or its implied correlation backed
# out — so the single-name list is derived from the filings themselves (see ``_market_index``),
# with these as the fallback when EDGAR has not been fetched yet.
_INDEX_MARKETS: dict[str, dict[str, str]] = {
    "NIFTY": {"label": "NIFTY 50", "region": "India", "source": _SOURCE, "ccy": "INR"},
    "SPX": {"label": "S&P 500", "region": "US", "source": "cboe", "ccy": "USD"},
    "SPY": {"label": "SPDR S&P 500 ETF", "region": "US", "source": "cboe", "ccy": "USD"},
    "NDX": {"label": "Nasdaq 100", "region": "US", "source": "cboe", "ccy": "USD"},
}
_FALLBACK_NAMES = ("TSLA", "NVDA", "AAPL")


def _market_index() -> dict[str, dict[str, str]]:
    """Index markets plus the single names the current US shelf actually references.

    Reading the names off the shelf rather than hardcoding a guess means the selector tracks
    what is being issued: if dealers rotate from the AI complex into something else, the
    underlyings follow without a code change, and the list is evidence rather than opinion.
    """
    out = dict(_INDEX_MARKETS)
    shelf: list[str] = []
    if _filings_cache:  # only if the shelf has already been fetched — never block on EDGAR here
        shelf = [n["symbol"] for n in _shelf_stats(_filings_cache[1]).get("names", [])]
    for symbol in (shelf or _FALLBACK_NAMES)[:8]:
        if symbol not in out:
            out[symbol] = {
                "label": symbol, "region": "US", "source": "cboe", "ccy": "USD",
                "why": "referenced by the current US note shelf" if shelf else "example single name",
            }
    return out


@app.get("/api/markets")
def markets() -> dict:
    """The underlyings this deployment can serve, and which engine serves each."""
    return {"markets": [{"symbol": k, **v} for k, v in _market_index().items()]}


def _spread_expiries(points: list, as_of, *, max_expiries: int = 12, min_strikes: int = 8) -> list:
    """Keep populated expiries spread across the whole term structure, not just the nearest ones.

    The desk's own selector takes the *nearest* six expiries, which is right for a NIFTY book
    whose risk sits in the front months. Applied to SPX it is exactly wrong: with 55 listed
    expiries the nearest six span 17 days, discarding the five-year coverage that is the entire
    reason for using US data. Sampling evenly in tenor keeps the long end, which is what a
    three-year note needs to be priceable.
    """
    from spdt.core.types import year_fraction as _yf

    by_expiry: dict = {}
    for p in points:
        if _yf(as_of, p.expiry) >= 10.0 / 365.0:  # same-day expiries are numerically unstable
            by_expiry.setdefault(p.expiry, []).append(p)
    populated = sorted(e for e, v in by_expiry.items() if len(v) >= min_strikes)
    if not populated:
        return []
    if len(populated) <= max_expiries:
        keep = populated
    else:
        step = (len(populated) - 1) / (max_expiries - 1)
        keep = [populated[round(i * step)] for i in range(max_expiries)]
    return [p for e in keep for p in by_expiry[e]]


def _build_market(underlying: str, source: str) -> dict:
    """Fetch, invert and calibrate one market, and report the fit honestly.

    ``fit`` is the point of this endpoint as much as the surface is: it carries the per-slice
    RMSE and the share of slices good enough to price against, so the UI can show *how much the
    surface is worth trusting* rather than drawing a smooth sheet over quotes that never traded.
    """
    from datetime import date as _date

    from spdt.data import build_snapshot
    from spdt.data.curate import invert_chain
    from spdt.data.live import fetch_live_raw
    from spdt.dashboard.desk_data import _LIVE_MAX_RELATIVE_SPREAD
    from spdt.vol.arbitrage import check_butterfly
    from spdt.vol.surface import VolSurface

    raw = fetch_live_raw(_date.today(), underlying, source=source)
    snap = build_snapshot(raw)

    has_liquidity = any(
        q.contracts_traded > 0.0 or q.open_interest > 0.0 for q in raw.option_chain
    )
    inverted = invert_chain(
        raw, snap.ois_curve,
        moneyness_band=1.0, iv_bounds=(0.03, 3.0), otm_only=True,
        min_contracts=1.0 if has_liquidity else None,
        min_open_interest=1.0 if has_liquidity else None,
        # Same substitution the desk makes: where a feed publishes no volume, a two-sided
        # touchline with a sane spread is the only liquidity evidence there is.
        require_two_sided=not has_liquidity,
        max_relative_spread=None if has_liquidity else _LIVE_MAX_RELATIVE_SPREAD,
    )
    points = _spread_expiries(inverted, raw.date)
    # SSVI, matching the desk. Independent per-slice SVI fits are unconstrained across strikes
    # and tenors and guarantee nothing: this panel was reporting butterfly and calendar
    # violations for a surface the desk never prices on, while the desk's own SSVI surface was
    # clean. A diagnostic that describes a different surface from the one in use is worse than
    # no diagnostic.
    surface = VolSurface.calibrate(
        points, underlying, param_model="SSVI", min_points_per_slice=8
    )
    fit = surface.fit_status

    ordered = sorted(surface.slices, key=lambda e: surface.taus[e])
    smile = [
        {
            "tau": round(surface.taus[e], 4),
            "expiry": e.isoformat(),
            "atm_vol": round(surface.implied_vol_kt(0.0, surface.taus[e]), 4),
            "points": [
                {"k": round(k, 3), "vol": round(surface.implied_vol_kt(k, surface.taus[e]), 4)}
                for k in (-0.30, -0.20, -0.10, 0.0, 0.10, 0.20, 0.30)
            ],
        }
        for e in ordered
    ]
    reliable = [s for s in (fit.slices if fit else ()) if s.rmse_bps <= 200.0]

    return {
        "underlying": underlying,
        "source": source,
        "meta": _market_index().get(underlying, {}),
        "as_of": raw.date.isoformat(),
        "spot": round(raw.spot, 4),
        "contracts": len(raw.option_chain),
        "traded_today": sum(1 for q in raw.option_chain if q.contracts_traded > 0),
        "with_open_interest": sum(1 for q in raw.option_chain if q.open_interest > 0),
        "two_sided": sum(1 for q in raw.option_chain if q.bid is not None and q.ask is not None),
        "calibrated_on": fit.n_points if fit else len(points),
        "smile": smile,
        "fit": {
            "rmse_bps": round(fit.rmse_bps, 1) if fit and fit.n_points else None,
            "slices": len(surface.slices),
            "reliable_pct": round(100.0 * fit.reliable_fraction(200.0), 0) if fit else None,
            "max_reliable_tenor": round(max((s.tau for s in reliable), default=0.0), 3),
            "arbitrage_clean": surface.arb_status.is_clean,
            # Which condition fails matters: a butterfly breach is a bad *slice* (negative
            # density, so a call spread prices negative), a calendar breach is a bad *pair*
            # of slices (total variance falling with maturity). They have different fixes.
            "butterfly_ok": surface.arb_status.butterfly_ok,
            "calendar_ok": surface.arb_status.calendar_ok,
            "min_g": round(surface.arb_status.min_g, 6),
            "per_slice_arb": [
                {
                    "tau": round(surface.taus[e], 4),
                    "ok": check_butterfly(surface.slices[e])[0],
                    "min_g": round(check_butterfly(surface.slices[e])[1], 6),
                    "min_g_in_data": round(
                        check_butterfly(
                            surface.slices[e],
                            k_grid=np.linspace(-_ARB_DATA_K, _ARB_DATA_K, 121, dtype=np.float64),
                        )[1],
                        6,
                    ),
                }
                for e in ordered
            ],
            "per_slice": [
                {"tau": round(s.tau, 4), "n": s.n_points, "rmse_bps": round(s.rmse_bps, 1)}
                for s in (fit.slices if fit else ())
            ],
        },
    }


@app.get("/api/market")
def market(underlying: str = "NIFTY", source: str | None = None) -> dict:
    """Spot, chain statistics and the calibrated surface for one underlying."""
    underlying = underlying.upper()
    index = _market_index()
    if underlying not in index:
        raise HTTPException(
            status_code=404,
            detail=f"unknown market {underlying!r}; see /api/markets",
        )
    source = source or index[underlying]["source"]
    key = (underlying, source)
    now = time.time()
    with _market_lock:
        hit = _market_cache.get(key)
        if hit and (now - hit[0]) < _MARKET_TTL:
            return hit[1]
    try:
        payload = _build_market(underlying, source)
    except Exception as exc:  # noqa: BLE001 - surface the reason rather than a bare 500
        raise HTTPException(
            status_code=502, detail=f"{underlying} via {source}: {type(exc).__name__}: {exc}"
        ) from exc
    with _market_lock:
        _market_cache[key] = (now, payload)
    return payload



# --- US structured-note shelf: real filed products and the issuer's own valuation ----------
# SEC 424B2 pricing supplements carry the complete terms *and* the issuer's disclosed initial
# estimated value. That value is the only external price benchmark in the project: everything
# else here is the model checked against itself.

_FILINGS_TTL = float(os.environ.get("SPDT_FILINGS_TTL", "21600"))  # 6h; the shelf moves daily
_filings_cache: tuple[float, list[dict]] | None = None
_filings_lock = threading.Lock()


def _filing_rows(days: int, limit: int) -> list[dict]:
    from datetime import date as _date, timedelta as _td

    from spdt.data.ingest.edgar import fetch_filing_text, parse_filing, search_filings

    today = _date.today()
    refs = search_filings(start=today - _td(days=days), end=today, limit=limit)
    rows: list[dict] = []
    seen: set = set()
    for ref in refs:
        try:
            f = parse_filing(fetch_filing_text(ref), issuer=ref.issuer, url=ref.url, filed=ref.filed)
        except Exception:  # noqa: BLE001 - one unreadable document must not sink the shelf
            continue
        if not f.is_benchmarkable:
            continue
        key = (f.cusip, tuple(sorted(t for t, _ in f.starting_values)), f.estimated_value,
               f.coupon_per_period, f.maturity_date)
        if key in seen:  # EDGAR returns the same supplement under several hits
            continue
        seen.add(key)
        names = [t for t, _ in f.starting_values] or list(f.underlyings)
        rows.append({
            "issuer": f.issuer.split("(")[0].strip(),
            "url": f.url,
            "filed": f.filed.isoformat(),
            "pricing_date": f.pricing_date.isoformat() if f.pricing_date else None,
            "maturity": f.maturity_date.isoformat() if f.maturity_date else None,
            "tenor_years": round(f.tenor_years, 2) if f.tenor_years else None,
            # Three kinds, not two. A basket note ("Linked to a Basket of Three Stocks") pays on
            # a weighted average and is *long* diversification; a worst-of pays on the least
            # performer and is short it. They carry opposite correlation exposure, so collapsing
            # both into "multi-asset" — or worse, calling a basket "single" because it lacks the
            # worst-of wording — would invert the sign of the risk being described.
            "kind": (
                "worst-of" if f.is_worst_of
                else "basket" if len(names) > 1
                else "single"
            ),
            "underlyings": names,
            "coupon_per_period_pct": round(100.0 * (f.coupon_per_period or 0.0) / f.denomination, 3),
            "periods_per_year": f.periods_per_year,
            "coupon_barrier": f.coupon_barrier,
            "knock_in": f.knock_in,
            "call_level": f.call_level,
            "memory": f.memory,
            # The number that makes this an external benchmark rather than a term-sheet viewer.
            "estimated_value_pct": round(f.estimated_value_pct, 2) if f.estimated_value_pct else None,
            "disclosed_load_pct": round(f.disclosed_load_pct, 2) if f.disclosed_load_pct else None,
            "staleness_days": (today - f.pricing_date).days if f.pricing_date else None,
        })
    return rows


@app.get("/api/us/filings")
def us_filings(days: int = 120, limit: int = 300) -> dict:
    """Recently priced US structured notes, with the terms and the issuer's own valuation.

    Cached hard: each call is a full-text search plus one document fetch per hit, rate-limited
    to stay inside SEC's published ceiling, so an uncached request takes minutes rather than
    seconds.
    """
    global _filings_cache
    now = time.time()
    with _filings_lock:
        if _filings_cache and (now - _filings_cache[0]) < _FILINGS_TTL:
            rows = _filings_cache[1]
            return {"filings": rows, "cached": True, **_shelf_stats(rows)}
    try:
        rows = _filing_rows(days, limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"EDGAR: {type(exc).__name__}: {exc}") from exc
    with _filings_lock:
        _filings_cache = (now, rows)
    return {"filings": rows, "cached": False, **_shelf_stats(rows)}


def _shelf_stats(rows: list[dict]) -> dict:
    """Shape of the shelf — which is the finding, not a summary statistic.

    Two thirds of current US issuance is worst-of on single stocks, which is why correlation
    (an input with no liquid market) is the binding unknown for benchmarking this shelf at all.
    """
    if not rows:
        return {"stats": {}, "names": []}
    worst_of = sum(1 for r in rows if r["kind"] == "worst-of")
    baskets = sum(1 for r in rows if r["kind"] == "basket")
    loads = [r["disclosed_load_pct"] for r in rows if r["disclosed_load_pct"] is not None]
    names: dict[str, int] = {}
    for r in rows:
        for t in r["underlyings"]:
            names[t] = names.get(t, 0) + 1
    return {
        "stats": {
            "n": len(rows),
            "worst_of": worst_of,
            "worst_of_pct": round(100.0 * worst_of / len(rows)),
            "basket": baskets,
            "single": len(rows) - worst_of - baskets,
            "mean_load_pct": round(sum(loads) / len(loads), 2) if loads else None,
            "mean_tenor": round(
                sum(r["tenor_years"] or 0 for r in rows) / len(rows), 2
            ),
        },
        "names": [
            {"symbol": k, "notes": v}
            for k, v in sorted(names.items(), key=lambda kv: -kv[1])[:20]
        ],
    }


from pathlib import Path  # noqa: E402

from fastapi.staticfiles import StaticFiles  # noqa: E402

_DIST = Path(__file__).resolve().parent / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="spa")
