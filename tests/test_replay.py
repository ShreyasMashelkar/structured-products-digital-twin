"""Replay mode: tape parsing, wall-clock → tape mapping, and quote re-marking."""

import json
from datetime import datetime

from spdt.data.replay import IST, load_tape, replay_quote, replay_tick, tape_index

# a 5-tick tape recorded 10:00:00–10:00:08 IST on 2026-07-16, 2s cadence
T0 = datetime(2026, 7, 16, 10, 0, 0, tzinfo=IST).timestamp()


def _tape(tmp_path):
    rows = [{"type": "meta", "date": "2026-07-16",
             "quote": {"symbol": "NIFTY", "description": "NIFTY26JULFUT", "lot_size": 75}}]
    rows += [{"spot": 25000.0 + i,
              "future": {"description": "NIFTY26JULFUT", "ltp": 25010.0 + i,
                         "bid": 25009.0 + i, "ask": 25011.0 + i},
              "atm_iv": 0.12, "dvol": 0.0, "timestamp": None, "age_s": 0.5,
              "stale": False, "rec_t": T0 + 2 * i}
             for i in range(5)]
    path = tmp_path / "tick_tape.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    return path


def test_replay_tape(tmp_path):
    meta, rows = load_tape(_tape(tmp_path))
    assert meta["quote"]["lot_size"] == 75
    assert len(rows) == 5

    # same IST time-of-day on a later date lands on the same tick (+5s → the 4s row)
    in_session = datetime(2026, 7, 17, 10, 0, 5, tzinfo=IST)
    assert tape_index(rows, in_session) == 2

    # outside the recorded window the position wraps modulo the 8s duration:
    # 20:00:01 is 36001s past 10:00:00 → 36001 % 8 = 1 → still inside tick 0
    overnight = datetime(2026, 7, 17, 20, 0, 1, tzinfo=IST)
    assert tape_index(rows, overnight) == 0

    tick = replay_tick(rows, in_session)
    assert tick["replay"] is True
    assert tick["spot"] == 25002.0
    assert "rec_t" not in tick

    # static day-quote re-marked at the current tape prices
    quote = replay_quote(meta, rows, in_session)
    assert quote["lot_size"] == 75
    assert quote["ltp"] == 25012.0
    assert quote["replay"] is True
