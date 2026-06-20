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

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from spdt.dashboard.desk_data import build_desk_data
from spdt.greeks import bump_greeks
from spdt.pricing import BlackScholes, price_mc
from spdt.products import (
    Autocallable,
    BarrierReverseConvertible,
    CapitalProtectedNote,
    Product,
    ReverseConvertible,
)
from spdt.reporting import terminal_scenarios
from spdt.stress import STANDARD_SCENARIOS
from spdt.structurer import ClientBrief, par_target, propose_autocallable, solve_to_par

# --- configuration (all env-driven so the same image runs locally and deployed) -----------
_CORS = os.environ.get("SPDT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
_DESK_TTL = float(os.environ.get("SPDT_DESK_TTL", "3600"))  # seconds before a rebuild
_LIVE = os.environ.get("SPDT_LIVE", "").lower() in ("1", "true", "yes")
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
_cache: dict[str, object] = {"payload": None, "built_at": 0.0}
_cache_lock = threading.Lock()


def _desk(force: bool = False) -> dict:
    """The desk payload, rebuilt when stale (older than the TTL) or on ``force``."""
    now = time.time()
    fresh = _cache["payload"] is not None and (now - float(_cache["built_at"])) < _DESK_TTL
    if fresh and not force:
        return _cache["payload"]  # type: ignore[return-value]
    with _cache_lock:  # only one builder; others wait then see the fresh result
        if force or _cache["payload"] is None or (time.time() - float(_cache["built_at"])) >= _DESK_TTL:
            _cache["payload"] = build_desk_data(live=_LIVE).payload
            _cache["built_at"] = time.time()
    return _cache["payload"]  # type: ignore[return-value]


@app.get("/api/health")
def health() -> dict:
    built = float(_cache["built_at"])
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


class StructureResponse(BaseModel):
    knock_in: float
    indicative_annual_coupon: float
    solved_annual_coupon: float | None
    achieved_pv: float | None
    target_pv: float
    pv_curve: list[dict]
    achievable: bool


@app.post("/api/structure", response_model=StructureResponse, dependencies=[Depends(require_token)])
def structure(req: StructureRequest) -> StructureResponse:
    """Client brief → proposed Phoenix → solve the coupon to par (live L6 origination)."""
    d = _desk()
    spot, m = d["spot"], d["model"]
    brief = ClientBrief(req.target_coupon, req.max_downside, req.maturity, req.obs_per_year)
    ts = propose_autocallable(brief)
    model = BlackScholes(spot=spot, r=m["r"], q=m["q"], sigma=m["atm_vol"])

    def pv_of_coupon(c: float) -> float:
        note = dataclasses.replace(
            Autocallable.from_termsheet(ts, initial_fixing=spot), coupon_rate=c
        )
        return price_mc(note, model, n_paths=15_000, seed=7).price

    curve = [
        {"annual_coupon": round(c * req.obs_per_year * 100, 3), "pv": round(pv_of_coupon(c), 4)}
        for c in [0.0025 * i for i in range(1, 19)]
    ]
    target = par_target(100.0, fee=req.fee)
    try:
        solved = solve_to_par(pv_of_coupon, target, (0.0, 0.06))
        solved_annual: float | None = solved.param * req.obs_per_year
        achieved_pv: float | None = solved.achieved_pv
    except ValueError:
        solved_annual, achieved_pv = None, None

    indic = ts.params["coupon_rate"] * req.obs_per_year
    return StructureResponse(
        knock_in=ts.params["knock_in"],
        indicative_annual_coupon=indic,
        solved_annual_coupon=solved_annual,
        achieved_pv=achieved_pv,
        target_pv=target,
        pv_curve=curve,
        achievable=bool(solved_annual is not None and solved_annual >= req.target_coupon),
    )


# --- generic term-sheet pricer (so the blotter can price arbitrary / staged trades) --------

class PriceRequest(BaseModel):
    product_type: str  # autocallable | brc | reverse_convertible | capital_protected
    notional: float = 100.0
    observation_times: list[float] | None = None
    maturity: float | None = None
    params: dict = {}


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
        return BarrierReverseConvertible(
            req.notional, obs, p.get("coupon_rate", 0.06), p.get("strike", 1.0),
            p.get("knock_in", 0.7), initial_fixing=spot,
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
            p.get("cap"),
        )
    raise ValueError(f"unknown product_type {kind!r}")


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
