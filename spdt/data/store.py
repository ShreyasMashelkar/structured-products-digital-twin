"""Curated store: persist snapshots and IV points reproducibly (design doc §2.5, §7).

Snapshots are written as **content-addressed** JSON —
``snapshots/date=<D>/snapshot-<short_hash>.json`` — so re-running a date produces a file
whose name carries the hash of its contents; reloading and re-hashing must reproduce that
hash (reproducible risk / "official close"). IV points are tabular, so they go to parquet
under ``curated/iv_points/`` per the storage layout.

We persist snapshots as JSON rather than parquet at this stage because a snapshot is a
small nested object (two curves + a handful of SVI slices), not a table, and JSON
round-trips its floats losslessly via ``repr``. Each calibrated surface serialises itself
via :meth:`VolSurface.to_dict`, so the store needs no knowledge of the SVI/SSVI internals.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from spdt.core.provenance import Provenance
from spdt.core.snapshot import MarketSnapshot
from spdt.core.types import CorrelationMatrix, Curve, DividendSchedule, InterpMethod, SourceTag
from spdt.data.curate.bs_inversion import IVPoint
from spdt.vol.surface import VolSurface


# --- curve (de)serialisation ----------------------------------------------------------

def _curve_to_dict(c: Curve) -> dict[str, Any]:
    return {
        "anchor": c.anchor.isoformat(),
        "pillars": [d.isoformat() for d in c.pillars],
        "discount_factors": (
            None
            if c.discount_factors is None
            else [[d.isoformat(), df] for d, df in c.discount_factors.items()]
        ),
        "interp": c.interp.value,
        "spread_over": None if c.spread_over is None else _curve_to_dict(c.spread_over),
        "spread_knots": (
            None
            if c.spread_knots is None
            else [[d.isoformat(), s] for d, s in c.spread_knots.items()]
        ),
    }


def _curve_from_dict(d: dict[str, Any]) -> Curve:
    return Curve(
        anchor=date.fromisoformat(d["anchor"]),
        pillars=tuple(date.fromisoformat(x) for x in d["pillars"]),
        discount_factors=(
            None
            if d["discount_factors"] is None
            else {date.fromisoformat(k): v for k, v in d["discount_factors"]}
        ),
        interp=InterpMethod(d["interp"]),
        spread_over=None if d["spread_over"] is None else _curve_from_dict(d["spread_over"]),
        spread_knots=(
            None
            if d["spread_knots"] is None
            else {date.fromisoformat(k): v for k, v in d["spread_knots"]}
        ),
    )


# --- snapshot persistence -------------------------------------------------------------

def _snapshot_to_dict(snap: MarketSnapshot) -> dict[str, Any]:
    return {
        "date": snap.date.isoformat(),
        "spots": dict(snap.spots),
        "ois_curve": _curve_to_dict(snap.ois_curve),
        "funding_curve": _curve_to_dict(snap.funding_curve),
        "surfaces": {u: s.to_dict() for u, s in snap.surfaces.items()},
        "dividends": {
            u: {
                "continuous_yield": d.continuous_yield,
                "cash_dividends": [[dt.isoformat(), amt] for dt, amt in d.cash_dividends],
            }
            for u, d in snap.dividends.items()
        },
        "provenance": {k: v.value for k, v in snap.provenance.tags.items()},
        "correlation": (
            None
            if snap.correlation is None
            else {
                "labels": list(snap.correlation.labels),
                "matrix": [list(row) for row in snap.correlation.matrix],
            }
        ),
    }


def _snapshot_from_dict(d: dict[str, Any]) -> MarketSnapshot:
    correlation = (
        None
        if d["correlation"] is None
        else CorrelationMatrix(
            labels=tuple(d["correlation"]["labels"]),
            matrix=tuple(tuple(row) for row in d["correlation"]["matrix"]),
        )
    )
    return MarketSnapshot(
        date=date.fromisoformat(d["date"]),
        spots=dict(d["spots"]),
        ois_curve=_curve_from_dict(d["ois_curve"]),
        funding_curve=_curve_from_dict(d["funding_curve"]),
        surfaces={u: VolSurface.from_dict(s) for u, s in d.get("surfaces", {}).items()},
        dividends={
            u: DividendSchedule(
                continuous_yield=v["continuous_yield"],
                cash_dividends=tuple(
                    (date.fromisoformat(dt), amt) for dt, amt in v["cash_dividends"]
                ),
            )
            for u, v in d["dividends"].items()
        },
        provenance=Provenance({k: SourceTag(v) for k, v in d["provenance"].items()}),
        correlation=correlation,
    )


def snapshot_path(snap: MarketSnapshot, root: Path | str) -> Path:
    """Content-addressed path for ``snap`` under ``root``."""
    root = Path(root)
    return root / "snapshots" / f"date={snap.date.isoformat()}" / f"snapshot-{snap.short_hash}.json"


def save_snapshot(snap: MarketSnapshot, root: Path | str) -> Path:
    """Write ``snap`` to its content-addressed path and return it."""
    path = snapshot_path(snap, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_snapshot_to_dict(snap), indent=2))
    return path


def load_snapshot(path: Path | str) -> MarketSnapshot:
    """Load a snapshot and verify its content hash matches the one in the filename."""
    path = Path(path)
    snap = _snapshot_from_dict(json.loads(path.read_text()))
    expected = path.stem.removeprefix("snapshot-")
    if snap.short_hash != expected:
        raise ValueError(
            f"content hash mismatch on load: file claims {expected}, recomputed {snap.short_hash}"
        )
    return snap


# --- IV points persistence ------------------------------------------------------------

def iv_points_path(underlying: str, as_of: date, root: Path | str) -> Path:
    root = Path(root)
    return (
        root / "curated" / "iv_points" / f"underlying={underlying}" / f"date={as_of.isoformat()}"
        / "points.parquet"
    )


def save_iv_points(
    points: list[IVPoint], underlying: str, as_of: date, root: Path | str
) -> Path:
    """Write inverted IV points to a partitioned parquet file."""
    path = iv_points_path(underlying, as_of, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "expiry": [p.expiry for p in points],
            "strike": [p.strike for p in points],
            "is_call": [p.is_call for p in points],
            "log_moneyness": [p.log_moneyness for p in points],
            "tau": [p.tau for p in points],
            "implied_vol": [p.implied_vol for p in points],
        }
    )
    frame.to_parquet(path, index=False)
    return path


def load_iv_points(path: Path | str) -> list[IVPoint]:
    frame = pd.read_parquet(path)
    return [
        IVPoint(
            expiry=row.expiry,
            strike=row.strike,
            is_call=bool(row.is_call),
            log_moneyness=row.log_moneyness,
            tau=row.tau,
            implied_vol=row.implied_vol,
        )
        for row in frame.itertuples(index=False)
    ]
