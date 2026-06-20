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

from spdt.backtest import aggregate, generate_realized_series, roll_issuance
from spdt.book import generate_mixed_book, mark_book
from spdt.data import build_snapshot
from spdt.data.curate import invert_chain
from spdt.data.ingest.synthetic import SyntheticSource
from spdt.hedging import simulate_delta_hedge
from spdt.modelrisk import model_gap_reserve, vol_bid_offer_reserve
from spdt.pnl import attribute
from spdt.pricing import BlackScholes, Discounter, price_mc
from spdt.pricing.models import LocalVolModel, LSVModel, local_vol_from_surface
from spdt.products import (
    Autocallable,
    BarrierReverseConvertible,
    CapitalProtectedNote,
    EuropeanOption,
    Leg,
    Product,
    ReverseConvertible,
)
from spdt.stress import STANDARD_SCENARIOS, stress_book
from spdt.vol import VolSurface

# A fixed reproducible "as of" for the synthetic desk when no date is supplied to a build that
# wants determinism (the synthetic source is date-agnostic; this only labels the snapshot).
DEFAULT_SYNTHETIC_AS_OF = date(2024, 6, 17)
_DT = 1.0 / 252.0


def _fetch_raw(as_of: date, *, live: bool):
    """Raw market data for ``as_of`` — live NSE/FBIL when ``live``, else the synthetic source."""
    if live:
        from spdt.data import fetch_live_raw

        return fetch_live_raw(as_of, "NIFTY")
    return SyntheticSource().fetch(as_of, "NIFTY")


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


def _position_record(product: Product) -> dict[str, Any]:
    """Economic terms of a note as a product-type-tagged record the UI can render uniformly."""
    if isinstance(product, Autocallable):
        return {
            "product_type": "autocallable",
            "observation_times": list(product.observation_times),
            "maturity": round(product.observation_times[-1], 2),
            "params": {"coupon_rate": product.coupon_rate, "autocall_level": product.autocall_level,
                       "coupon_barrier": product.coupon_barrier, "knock_in": product.knock_in,
                       "memory": product.memory},
        }
    if isinstance(product, BarrierReverseConvertible):
        return {
            "product_type": "brc",
            "observation_times": list(product.observation_times),
            "maturity": round(product.observation_times[-1], 2),
            "params": {"coupon_rate": product.coupon_rate, "strike": product.strike,
                       "knock_in": product.knock_in},
        }
    if isinstance(product, ReverseConvertible):
        return {
            "product_type": "reverse_convertible",
            "observation_times": list(product.observation_times),
            "maturity": round(product.observation_times[-1], 2),
            "params": {"coupon_rate": product.coupon_rate, "strike": product.strike},
        }
    if isinstance(product, CapitalProtectedNote):
        return {
            "product_type": "capital_protected",
            "observation_times": None,
            "maturity": round(product.maturity, 2),
            "params": {"protection": product.protection, "participation": product.participation,
                       "strike": product.strike, "cap": product.cap},
        }
    raise TypeError(f"no position record for {type(product).__name__}")


def _flat_total_variance(sigma: float):
    """A flat total-variance surface ``w(k, t) = σ²·t`` for the model-risk LV/LSV models."""

    def w(k, t):  # noqa: ANN001 - numpy duck-typed
        return sigma * sigma * np.asarray(t, dtype=float) * np.ones_like(np.asarray(k, dtype=float))

    return w


def _hedging_convergence(model: BlackScholes, *, n_paths: int, seed: int) -> list[dict[str, Any]]:
    """Dynamic delta-hedge P&L vs rebalance frequency (the √Δt replication-error story, L9)."""
    option = EuropeanOption(strike=model.spot, expiry=1.0, is_call=True)
    rows: list[dict[str, Any]] = []
    for n_steps in (5, 10, 21, 50, 126, 252):
        clean = simulate_delta_hedge(model, option, n_steps=n_steps, n_paths=n_paths, seed=seed)
        slip = simulate_delta_hedge(
            model, option, n_steps=n_steps, n_paths=n_paths, seed=seed, slippage_bps=2.0
        )
        rows.append({
            "n_steps": n_steps,
            "std_pnl": clean.std_pnl,
            "mean_pnl": clean.mean_pnl,
            "mean_pnl_slippage": slip.mean_pnl,
            "slippage_cost": slip.mean_slippage_cost,
        })
    return rows


def _backtest(spot: float, atm_vol: float, *, seed: int) -> dict[str, Any]:
    """Roll a monthly Phoenix over a 10y realised path; aggregate the outcome distribution (L7)."""
    series = generate_realized_series(252 * 10, s0=spot, mu=0.08, sigma=atm_vol, seed=seed)
    note = Autocallable(
        notional=100.0, observation_times=(0.25, 0.5, 0.75, 1.0), coupon_rate=0.02,
        autocall_level=1.0, coupon_barrier=0.7, knock_in=0.6, memory=True, initial_fixing=spot,
    )
    outcomes = roll_issuance(series, note, issuance_step_days=21)
    stats = aggregate(outcomes, 100.0)
    return {
        "n_issuances": stats.n_issuances,
        "autocall_rate": stats.autocall_rate,
        "mean_total_return": stats.mean_total_return,
        "loss_rate": stats.loss_rate,
        "mean_capital_loss": stats.mean_capital_loss,
        "worst_5pct_return": stats.worst_5pct_return,
        "returns": [round(o.total_payoff / 100.0, 4) for o in outcomes],
        "series": [round(float(x), 2) for x in series[:: 252 // 12]],  # monthly thinned path
    }


def _lsv_lv_reserves(
    notes: list[Product], spot: float, r: float, q: float, atm_vol: float, *, seed: int
) -> list[dict[str, Any]]:
    """LSV − LV model reserve per note: same vanilla marginals, different exotic dynamics (L11)."""
    lv_fn = local_vol_from_surface(_flat_total_variance(atm_vol), r=r, q=q, spot0=spot)
    lsv = LSVModel(spot, r, q, v0=atm_vol**2, kappa=1.5, theta=atm_vol**2, xi=0.6, rho=-0.5,
                   local_vol=lv_fn, seed=seed)
    lv = LocalVolModel(spot, r, q, lv_fn)
    out: list[dict[str, Any]] = []
    for note in notes:
        lsv_pv = price_mc(note, lsv, n_paths=8_000, seed=seed, steps_per_year=24).price
        lv_pv = price_mc(note, lv, n_paths=8_000, seed=seed, steps_per_year=24).price
        out.append({
            "lsv_pv": lsv_pv, "lv_pv": lv_pv, "lsv_minus_lv": model_gap_reserve(lsv_pv, lv_pv)
        })
    return out


def _catalog_with_funding(
    spot: float, r: float, q: float, atm_vol: float, snap, *, seed: int
) -> list[dict[str, Any]]:
    """Price the income/protection notes under two-curve discounting + cost decomposition (L4)."""
    model = BlackScholes(spot=spot, r=r, q=q, sigma=atm_vol)
    disc = Discounter.from_snapshot(snap)
    obs = (0.5, 1.0)
    notes = {
        "Barrier reverse convertible": BarrierReverseConvertible(
            100.0, obs, coupon_rate=0.06, strike=1.0, knock_in=0.7, initial_fixing=spot),
        "Reverse convertible": ReverseConvertible(
            100.0, obs, coupon_rate=0.08, strike=1.0, initial_fixing=spot),
        "Capital-protected note": CapitalProtectedNote(
            100.0, maturity=1.0, protection=1.0, participation=1.0, strike=1.0),
    }
    rows: list[dict[str, Any]] = []
    for name, note in notes.items():
        two_curve = price_mc(note, model, n_paths=40_000, seed=seed, discount=disc).price
        ois_only = price_mc(note, model, n_paths=40_000, seed=seed, discount=snap.ois_curve.df).price
        # Funding-leg PV (the bond) vs option-leg PV, both on their own curve.
        grid = note.monitoring_times()
        cfs = note.cashflows(_one_path(note, spot, r, q, atm_vol, grid, seed))
        rows.append({
            "name": name,
            "pv_two_curve": two_curve,
            "pv_ois_only": ois_only,
            "funding_impact": two_curve - ois_only,
            "has_funding_leg": any(cf.leg is Leg.FUNDING for cf in cfs),
        })
    return rows


def _one_path(note, spot, r, q, sigma, grid, seed):  # noqa: ANN001 - small helper
    """A single MC path set just to introspect a note's leg structure."""
    from spdt.pricing.mc.rng import standard_normals
    from spdt.products import PathSet

    times = np.array([0.0, *grid])
    z = standard_normals(2, times.size - 1, seed=seed)
    model = BlackScholes(spot=spot, r=r, q=q, sigma=sigma)
    return PathSet(times=times, spots=model.simulate(times, z))


def _structuring_example(spot: float, r: float, q: float, atm_vol: float, *, seed: int) -> dict:
    """A worked client → proposer → solve-to-par origination (L6), shown as the default view."""
    from spdt.structurer import ClientBrief, par_target, propose_autocallable, solve_to_par

    brief = ClientBrief(target_coupon=0.12, max_downside=0.30, maturity_years=1.0,
                        observations_per_year=4)
    ts = propose_autocallable(brief)
    model = BlackScholes(spot=spot, r=r, q=q, sigma=atm_vol)

    def pv_of_coupon(c: float) -> float:
        note = Autocallable.from_termsheet(ts, initial_fixing=spot)
        note = _replace_coupon(note, c)
        return price_mc(note, model, n_paths=20_000, seed=seed).price

    coupons = [0.005 * i for i in range(1, 11)]
    pv_curve = [{"coupon": c, "pv": pv_of_coupon(c)} for c in coupons]
    solved = solve_to_par(pv_of_coupon, par_target(100.0, fee=1.0), (0.0, 0.06))
    return {
        "brief": {"target_coupon": brief.target_coupon, "max_downside": brief.max_downside,
                  "maturity": brief.maturity_years, "obs_per_year": brief.observations_per_year},
        "proposed": dict(ts.params, knock_in=ts.params["knock_in"]),
        "indicative_coupon": ts.params["coupon_rate"],
        "solved_coupon": solved.param,
        "solved_annual_coupon": solved.param * brief.observations_per_year,
        "achieved_pv": solved.achieved_pv,
        "target_pv": solved.target,
        "pv_curve": pv_curve,
    }


def _replace_coupon(note: Autocallable, coupon: float) -> Autocallable:
    import dataclasses

    return dataclasses.replace(note, coupon_rate=coupon)


def build_desk_data(
    *,
    n_notes: int = 12,
    seed: int = 7,
    n_paths: int = 20_000,
    as_of: date | None = None,
    live: bool = False,
) -> DeskData:
    """Compute the full desk snapshot for the dashboard.

    ``as_of`` defaults to today (synthetic data is date-agnostic, so this only labels the
    snapshot — but it stops the dashboard from showing one frozen historical date forever).
    Pass ``live=True`` to build from live NSE options + FBIL rates (network; not for CI).
    """
    as_of = as_of or date.today()
    # L1/L2 — market and arbitrage-free surface.
    raw = _fetch_raw(as_of, live=live)
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

    # L8 — generate and mark a mixed book (autocallables + BRC / reverse-conv / capital-protected).
    trades = generate_mixed_book(n_notes, initial_fixing=spot, seed=seed)
    book = mark_book(trades, model0, n_paths=n_paths, seed=seed)
    marks = {p.trade_id: p for p in book.positions}

    positions: list[dict[str, Any]] = []
    pnl_by_trade: list[dict[str, Any]] = []
    reserves: list[dict[str, Any]] = []
    notes_list: list[Product] = []
    book_pnl = {k: 0.0 for k in
                ("delta_pnl", "gamma_pnl", "theta_pnl", "vega_pnl", "volga_pnl",
                 "vanna_pnl", "rho_pnl", "residual", "total")}

    for trade in trades:
        note = trade.product
        notes_list.append(note)
        mark = marks[trade.trade_id]
        explain = attribute(note, model0, model1, _DT, n_paths=n_paths, seed=seed)
        reserve = vol_bid_offer_reserve(note, model0, 0.01, n_paths=n_paths, seed=seed)

        rec = _position_record(note)
        p = rec["params"]
        positions.append({
            "trade_id": trade.trade_id,
            "underlying": trade.underlying,
            "product_type": rec["product_type"],
            "notional": getattr(note, "notional", 100.0),
            "observation_times": rec["observation_times"],
            "maturity": rec["maturity"],
            "params": p,
            # back-compat autocallable-ish columns (None where not applicable)
            "coupon": p.get("coupon_rate", 0.0),
            "autocall": p.get("autocall_level"),
            "coupon_barrier": p.get("coupon_barrier"),
            "knock_in": p.get("knock_in"),
            "memory": p.get("memory", False),
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

    # L12 — coherent stress scenarios across the book, with a per-trade decomposition.
    stress_results = [
        stress_book(trades, model0, sc, n_paths=n_paths, seed=seed) for sc in STANDARD_SCENARIOS
    ]
    stress = [
        {"scenario": r.scenario, "pnl": r.pnl, "pct": 100.0 * r.pnl / book.total_pv}
        for r in stress_results
    ]
    stress_by_trade = {r.scenario: r.per_trade_pnl for r in stress_results}

    # Risk aggregations: vega by maturity bucket, gamma concentration.
    vega_ladder: dict[str, float] = {}
    for p in positions:
        bucket = f"{p['maturity']:.1f}y"
        vega_ladder[bucket] = vega_ladder.get(bucket, 0.0) + p["vega"]

    # L11 — model reserve: LSV − LV per note (merged into the per-trade reserve rows).
    lsv_lv = _lsv_lv_reserves(notes_list, spot, r, q, atm_vol, seed=seed)
    for row, gap in zip(reserves, lsv_lv):
        row.update(gap)

    # L9 — dynamic delta-hedge convergence; L7 — rolling-issuance backtest; L6 — origination;
    # L4 — income/protection catalog under two-curve discounting.
    hedging = _hedging_convergence(model0, n_paths=min(n_paths, 20_000), seed=seed)
    backtest = _backtest(spot, atm_vol, seed=seed)
    structuring = _structuring_example(spot, r, q, atm_vol, seed=seed)
    catalog = _catalog_with_funding(spot, r, q, atm_vol, snap, seed=seed)
    funding_spread_bp = round(
        (snap.funding_curve.zero_rate(longest) - snap.ois_curve.zero_rate(longest)) * 1e4, 1
    )

    # L2 — surface grid for the heatmap.
    ks = np.linspace(-0.35, 0.35, 25)
    taus = sorted(surface.taus.values())
    surface_grid = {
        "log_moneyness": ks.tolist(),
        "tenors": [round(t, 3) for t in taus],
        "iv": [[round(surface.implied_vol_kt(float(k), t) * 100, 3) for k in ks] for t in taus],
    }

    payload = {
        "as_of": as_of.isoformat(),
        "data_source": "live" if live else "synthetic",
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
        "total_model_reserve": sum(r_.get("lsv_minus_lv", 0.0) for r_ in reserves),
        "funding_spread_bp": funding_spread_bp,
        "positions": positions,
        "pnl_explain": book_pnl,
        "pnl_by_trade": pnl_by_trade,
        "stress": stress,
        "stress_by_trade": stress_by_trade,
        "reserves": reserves,
        "vega_ladder": vega_ladder,
        "surface": surface_grid,
        "arb_clean": surface.arb_status.is_clean,
        "hedging": hedging,
        "backtest": backtest,
        "structuring": structuring,
        "catalog": catalog,
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
