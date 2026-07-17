"""Session replay: a recorded tick tape served as if the market were live.

Record a tape during a live XTS session (``python3 -m tools.record_tape``), save the desk
payload alongside it (``--desk``), and run the server with ``SPDT_SOURCE=replay`` — the
tick/quote endpoints then replay the recorded session mapped onto the wall clock. A public
demo (e.g. Hugging Face Spaces) shows real market behaviour without redistributing live
market data, which brokers' API terms and the exchanges' display licences prohibit.

Tape format (jsonl): an optional first meta row ``{"type": "meta", "date": …, "quote": {…}}``
carrying the day's static front-future quote (lot size, expiry — for ``/api/live/quote``),
then one row per tick exactly as the live poller returned it, each stamped with ``rec_t``
(epoch seconds at capture).
"""

from __future__ import annotations

import json
from bisect import bisect_right
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def load_tape(path: str | Path) -> tuple[dict, list[dict]]:
    """Parse a tape file → ``(meta, tick_rows)``. Raises on a tape with no ticks."""
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    meta = rows.pop(0) if rows and rows[0].get("type") == "meta" else {}
    rows = [r for r in rows if r.get("rec_t") is not None]
    if not rows:
        raise ValueError(f"tick tape has no ticks: {path}")
    return meta, rows


def _seconds_of_day(dt: datetime) -> float:
    dt = dt.astimezone(IST)
    return dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1e6


def tape_index(rows: list[dict], now: datetime) -> int:
    """Map the wall clock onto the tape.

    Aligned by IST time-of-day, so 14:05 today plays the 14:05 tick of the recorded
    session; outside the recorded window the position wraps modulo the tape's duration,
    so the replay keeps ticking overnight and on weekends instead of freezing.
    """
    t0 = rows[0]["rec_t"]
    duration = (rows[-1]["rec_t"] - t0) or 1.0
    pos = (_seconds_of_day(now) - _seconds_of_day(datetime.fromtimestamp(t0, IST))) % duration
    return max(0, bisect_right([r["rec_t"] - t0 for r in rows], pos) - 1)


def replay_tick(rows: list[dict], now: datetime) -> dict:
    """The tape row for ``now``, flagged so the UI can label the feed as a replay."""
    row = dict(rows[tape_index(rows, now)])
    row.pop("rec_t", None)
    row["replay"] = True
    return row


def replay_quote(meta: dict, rows: list[dict], now: datetime) -> dict:
    """The day's static quote (lot size, expiry, …) re-marked at the current tape prices."""
    row = rows[tape_index(rows, now)]
    fut = row.get("future") or {}
    return {**(meta.get("quote") or {}),
            "ltp": fut.get("ltp"), "bid": fut.get("bid"), "ask": fut.get("ask"),
            "timestamp": row.get("timestamp"), "age_s": row.get("age_s"),
            "stale": bool(row.get("stale")), "replay": True}
