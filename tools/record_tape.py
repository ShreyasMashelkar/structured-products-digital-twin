"""Cut a session tick tape + desk payload for replay mode (``SPDT_SOURCE=replay``).

During market hours, on the live feed (XTS creds in the env):

    SPDT_SOURCE=xts python3 -m tools.record_tape           # appends data/replay/tick_tape.jsonl

Near or after the close, save the desk payload the replay will serve (and the day's
desk-history timeline, so the replay's intraday charts aren't empty):

    SPDT_SOURCE=xts python3 -m tools.record_tape --desk    # writes data/replay/desk.json

Ship ``data/replay/`` with the image (the Dockerfile copies it) and set
``SPDT_SOURCE=replay`` on the deployment — the demo then replays the recorded session on
the wall clock, so no live market data is ever redistributed.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPLAY_DIR = Path(os.environ.get("SPDT_REPLAY_DIR", "data/replay"))
IST = ZoneInfo("Asia/Kolkata")


def record(interval: float) -> None:
    from webapp.server import _REPLAY, _fetch_tick, _in_nse_session, _live_quote

    if _REPLAY:
        sys.exit("recording needs a live source — run with SPDT_SOURCE=xts, not replay")
    tape = REPLAY_DIR / "tick_tape.jsonl"
    tape.parent.mkdir(parents=True, exist_ok=True)
    if tape.exists() and tape.stat().st_size:  # one tape = one session: rotate stale days
        try:
            tape_date = json.loads(tape.read_text().splitlines()[0]).get("date")
        except ValueError:
            tape_date = None
        if tape_date != date.today().isoformat():
            tape.rename(tape.with_name(f"tick_tape.{tape_date or 'old'}.jsonl"))
    in_session = _in_nse_session(datetime.now(IST))
    if not in_session:
        print("note: outside NSE session hours — recording until Ctrl-C")
    n = 0
    with tape.open("a") as f:
        if f.tell() == 0:  # the day's static front-future quote (lot size, expiry) for replay
            f.write(json.dumps({"type": "meta", "date": date.today().isoformat(),
                                "quote": _live_quote("NIFTY")}) + "\n")
            f.flush()
        while True:
            if in_session and not _in_nse_session(datetime.now(IST)):
                print(f"session over — {n} ticks on tape at {tape}")
                return
            try:
                row = _fetch_tick()
                row["rec_t"] = time.time()
                f.write(json.dumps(row) + "\n")
                f.flush()
                n += 1
            except Exception as exc:  # noqa: BLE001 — a failed poll must not end the tape
                print(f"tick failed: {exc}")
            time.sleep(interval)


def desk() -> None:
    from spdt.dashboard.desk_data import build_desk_data

    source = os.environ.get("SPDT_SOURCE", "xts")
    face = float(os.environ.get("SPDT_FACE_PER_NOTE", "50000000"))
    print(f"building live desk payload ({source}) — takes ~a minute on XTS…")
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    build_desk_data(live=True, source=source, face_per_note=face).save(REPLAY_DIR / "desk.json")
    history = Path("dashboard_data/desk_history.jsonl")
    if history.exists():
        (REPLAY_DIR / "desk_history.jsonl").write_bytes(history.read_bytes())
    print(f"replay bundle ready in {REPLAY_DIR}/")


if __name__ == "__main__":
    if "--desk" in sys.argv:
        desk()
    else:
        record(float(os.environ.get("SPDT_TICK_INTERVAL_S", "2")))
