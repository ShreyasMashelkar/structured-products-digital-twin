"""Assemble the desk dataset that powers the dashboard (L14 data layer).

Runs the full stack once — snapshot → arbitrage-free surface → a generated book → marks,
netted Greeks, daily P&L explain, stress, and reserves — and packs the results into a single
JSON-serialisable structure the Streamlit app reads. Keeping all computation here means the UI
layer is pure presentation, and the dataset can be persisted to / replayed from the store.

Uses the deterministic synthetic source so the desk view is reproducible and offline; the same
assembly runs on a live snapshot (``spdt.data.build_live_snapshot``) unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from spdt.book import generate_autocallable_book, mark_book
from spdt.data import build_snapshot
from spdt.data.curate import invert_chain
from spdt.data.ingest.synthetic import SyntheticSource
from spdt.modelrisk import vol_bid_offer_reserve
from spdt.pnl import attribute
from spdt.pricing import BlackScholes
from spdt.stress import STANDARD_SCENARIOS, stress_book
from spdt.vol import VolSurface

AS_OF = date(2024, 6, 17)
_DT = 1.0 / 252.0


@dataclass(frozen=True)
class DeskData:
    """Everything the dashboard renders, already computed."""

    payload: dict[str, Any]

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.payload, indent=2))
        return path

    @classmethod
    def load(cls, path: str | Path) -> "DeskData":
        return cls(json.loads(Path(path).read_text()))


def build_desk_data(
    *, n_notes: int = 12, seed: int = 7, n_paths: int = 20_000
) -> DeskData:
    """Compute the full desk snapshot for the dashboard."""
    # L1/L2 — market and arbitrage-free surface.
    raw = SyntheticSource().fetch(AS_OF, "NIFTY")
    snap = build_snapshot(raw)
    surface = VolSurface.calibrate(invert_chain(raw, snap.ois_curve), "NIFTY")
    spot = snap.spots["NIFTY"]
    longest = max(surface.taus, key=lambda e: surface.taus[e])
    atm_vol = surface.implied_vol_kt(0.0, surface.taus[longest])
    r = snap.ois_curve.zero_rate(longest)
    q = snap.dividends["NIFTY"].continuous_yield

    # Today's market (D-1) and a small overnight move (D) for the P&L explain.
    model0 = BlackScholes(spot=spot, r=r, q=q, sigma=atm_vol)
    model1 = BlackScholes(spot=spot * 1.008, r=r, q=q, sigma=atm_vol + 0.003)

    # L8 — generate and mark the book.
    trades = generate_autocallable_book(n_notes, initial_fixing=spot, seed=seed)
    book = mark_book(trades, model0, n_paths=n_paths, seed=seed)
    marks = {p.trade_id: p for p in book.positions}

    positions: list[dict[str, Any]] = []
    pnl_by_trade: list[dict[str, Any]] = []
    reserves: list[dict[str, Any]] = []
    book_pnl = {k: 0.0 for k in
                ("delta_pnl", "gamma_pnl", "theta_pnl", "vega_pnl", "volga_pnl",
                 "vanna_pnl", "rho_pnl", "residual", "total")}

    for trade in trades:
        note = trade.product
        mark = marks[trade.trade_id]
        explain = attribute(note, model0, model1, _DT, n_paths=n_paths, seed=seed)
        reserve = vol_bid_offer_reserve(note, model0, 0.01, n_paths=n_paths, seed=seed)

        positions.append({
            "trade_id": trade.trade_id,
            "underlying": trade.underlying,
            "notional": note.notional,
            "observation_times": list(note.observation_times),
            "maturity": round(note.observation_times[-1], 2),
            "coupon": note.coupon_rate,
            "autocall": note.autocall_level,
            "coupon_barrier": note.coupon_barrier,
            "knock_in": note.knock_in,
            "memory": note.memory,
            "pv": mark.pv,
            "delta": mark.greeks.delta,
            "gamma": mark.greeks.gamma,
            "vega": mark.greeks.vega,
            "rho": mark.greeks.rho,
            "day_pnl": explain.total,
        })
        pnl_by_trade.append({"trade_id": trade.trade_id, "total": explain.total,
                             "residual": explain.residual})
        reserves.append({"trade_id": trade.trade_id, "bid_offer": reserve})
        for key in book_pnl:
            book_pnl[key] += getattr(explain, key)

    # L12 — coherent stress scenarios across the book.
    stress = [
        {"scenario": res.scenario, "pnl": res.pnl, "pct": 100.0 * res.pnl / book.total_pv}
        for res in (stress_book(trades, model0, sc, n_paths=n_paths, seed=seed)
                    for sc in STANDARD_SCENARIOS)
    ]

    # Risk aggregations: vega by maturity bucket, gamma concentration.
    vega_ladder: dict[str, float] = {}
    for p in positions:
        bucket = f"{p['maturity']:.1f}y"
        vega_ladder[bucket] = vega_ladder.get(bucket, 0.0) + p["vega"]

    # L2 — surface grid for the heatmap.
    ks = np.linspace(-0.35, 0.35, 25)
    taus = sorted(surface.taus.values())
    surface_grid = {
        "log_moneyness": ks.tolist(),
        "tenors": [round(t, 3) for t in taus],
        "iv": [[round(surface.implied_vol_kt(float(k), t) * 100, 3) for k in ks] for t in taus],
    }

    payload = {
        "as_of": AS_OF.isoformat(),
        "underlying": "NIFTY",
        "spot": spot,
        "model": {"r": r, "q": q, "atm_vol": atm_vol},
        "market_move": {"spot_bp": 80, "vol_pt": 0.3, "horizon_days": 1},
        "nav": book.total_pv,
        "day_pnl": book_pnl["total"],
        "net_greeks": {
            "delta": book.net_greeks.delta, "gamma": book.net_greeks.gamma,
            "vega": book.net_greeks.vega, "rho": book.net_greeks.rho,
        },
        "total_reserve": sum(r_["bid_offer"] for r_ in reserves),
        "positions": positions,
        "pnl_explain": book_pnl,
        "pnl_by_trade": pnl_by_trade,
        "stress": stress,
        "reserves": reserves,
        "vega_ladder": vega_ladder,
        "surface": surface_grid,
        "arb_clean": surface.arb_status.is_clean,
    }
    return DeskData(payload)


def load_or_build(path: str | Path = "dashboard_data/desk.json", **kwargs: Any) -> DeskData:
    """Load the cached desk dataset, building and persisting it on first use."""
    path = Path(path)
    if path.exists():
        return DeskData.load(path)
    data = build_desk_data(**kwargs)
    data.save(path)
    return data
