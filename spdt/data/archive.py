"""Snapshot archiver: accumulate an owned intraday history of market snapshots.

The store is already content-addressed (same content → same file), so archiving is cheap
and idempotent; what it adds is an append-only ``archive_index.jsonl`` recording *when*
each capture happened. Run repeatedly through a live session (cron/loop) and the desk
builds its own point-in-time dataset — the one input money can't buy retroactively.

CLI (network):  python3 -m spdt.data.archive [root]
    Fetches live raw data (``SPDT_SOURCE``: bhavcopy | dhan | xts), builds the snapshot,
    and archives it under ``root`` (default ``dashboard_data``).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from spdt.core.snapshot import MarketSnapshot
from spdt.data.store import save_snapshot

_INDEX = "archive_index.jsonl"


def archive_snapshot(snap: MarketSnapshot, root: Path | str, *, captured_at: datetime) -> Path:
    """Save ``snap`` (content-addressed) and append a capture record to the index."""
    root = Path(root)
    path = save_snapshot(snap, root)
    index = root / "snapshots" / _INDEX
    row = {
        "captured_at": captured_at.isoformat(),
        "date": snap.date.isoformat(),
        "path": str(path.relative_to(root)),
        "spot": {u: s for u, s in snap.spots.items()}.get("NIFTY", next(iter(snap.spots.values()))),
    }
    with index.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return path


def load_archive_index(root: Path | str) -> list[dict]:
    """All capture records, oldest first. Empty list for a fresh root."""
    index = Path(root) / "snapshots" / _INDEX
    if not index.exists():
        return []
    return [json.loads(line) for line in index.read_text().splitlines() if line.strip()]


if __name__ == "__main__":  # pragma: no cover — network entry point
    import os
    import sys
    from datetime import date

    from spdt.data import build_snapshot
    from spdt.data.live import fetch_live_raw

    root = sys.argv[1] if len(sys.argv) > 1 else "dashboard_data"
    source = os.environ.get("SPDT_SOURCE", "bhavcopy")
    snap = build_snapshot(fetch_live_raw(date.today(), source=source))
    saved = archive_snapshot(snap, root, captured_at=datetime.now())
    print(f"archived {source} snapshot → {saved}")
