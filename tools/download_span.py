"""Backfill NSE's daily SPAN risk-parameter files to local disk.

    python3 -m tools.download_span              # 2019-01-01 -> today, resumable
    python3 -m tools.download_span 2015-01-01   # deeper start if the archive allows

Why: margin for the options backtest (SPAN scan risk) comes from the exchange's own
``nsccl.YYYYMMDD.s.zip`` files, publicly archived — verified reachable back through the
March-2020 crash. NSE has pruned old archives before, so the history is copied down once
and kept. Skips files already on disk, so re-running only fetches what's missing (including
new days — safe to run any time).

404 is expected on holidays; anything else is logged. Files land in
``data/span_archive/`` (gitignored — several GB).
"""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ARCHIVE = "https://nsearchives.nseindia.com/archives/nsccl/span"
DEST = Path("data/span_archive")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
PAUSE_S = 0.4  # polite spacing between requests


def fetch_day(d: date) -> str:
    """Download one day's EOD file. Returns 'ok' | 'have' | 'holiday' | an error string."""
    name = f"nsccl.{d:%Y%m%d}.s.zip"
    out = DEST / name
    if out.exists() and out.stat().st_size > 0:
        return "have"
    request = urllib.request.Request(f"{ARCHIVE}/{name}", headers=UA)
    for attempt in (1, 2):  # a long run WILL hit mid-stream resets; one retry, then move on
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                data = response.read()
        except urllib.error.HTTPError as exc:
            return "holiday" if exc.code == 404 else f"http {exc.code}"
        except Exception as exc:  # noqa: BLE001 — URLError, IncompleteRead, resets: skip, not crash
            if attempt == 2:
                return f"error {type(exc).__name__}: {exc}"
            time.sleep(3.0)
            continue
        out.write_bytes(data)  # only after a complete read — no partial files on disk
        return "ok"
    return "error unreachable"


def main() -> None:
    start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2019, 1, 1)
    DEST.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    d, today = start, date.today()
    while d <= today:
        if d.weekday() < 5:  # exchange files exist for trading days only
            status = fetch_day(d)
            counts[status] = counts.get(status, 0) + 1
            if status not in ("ok", "have", "holiday"):
                print(f"{d}: {status}", flush=True)
            if status == "ok":
                time.sleep(PAUSE_S)
        d += timedelta(days=1)
    total_mb = sum(p.stat().st_size for p in DEST.glob("*.zip")) / 1e6
    print(f"done: {counts} — {len(list(DEST.glob('*.zip')))} files, {total_mb:.0f} MB")


if __name__ == "__main__":
    main()
