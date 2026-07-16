"""Tests for the snapshot archiver — capture-time index over the content-addressed store.

Snapshots are already saved content-addressed (same content → same file); the archiver adds
an append-only index of *when* each capture happened, so intraday history accumulates and
replays in order.
"""

from datetime import date, datetime

from spdt.data import build_snapshot, load_snapshot
from spdt.data.archive import archive_snapshot, load_archive_index
from spdt.data.ingest.synthetic import SyntheticSource

_AS_OF = date(2026, 7, 10)


def _snap():
    return build_snapshot(SyntheticSource().fetch(_AS_OF, "NIFTY"))


def test_archive_writes_snapshot_and_index_row(tmp_path):
    snap = _snap()
    path = archive_snapshot(snap, tmp_path, captured_at=datetime(2026, 7, 10, 11, 30, 0))
    assert path.exists()
    assert load_snapshot(path).short_hash == snap.short_hash  # store round-trip intact

    (row,) = load_archive_index(tmp_path)
    assert row["captured_at"] == "2026-07-10T11:30:00"
    assert row["date"] == "2026-07-10"
    assert row["spot"] == snap.spots["NIFTY"]
    assert (tmp_path / row["path"]).exists()


def test_repeat_captures_share_the_file_but_keep_every_index_row(tmp_path):
    snap = _snap()
    p1 = archive_snapshot(snap, tmp_path, captured_at=datetime(2026, 7, 10, 11, 30, 0))
    p2 = archive_snapshot(snap, tmp_path, captured_at=datetime(2026, 7, 10, 11, 35, 0))
    assert p1 == p2  # content-addressed: unchanged market → one file
    rows = load_archive_index(tmp_path)
    assert [r["captured_at"] for r in rows] == ["2026-07-10T11:30:00", "2026-07-10T11:35:00"]


def test_index_is_empty_for_fresh_root(tmp_path):
    assert load_archive_index(tmp_path) == []
