"""Smoke test for the Phase 10 end-to-end desk demo — the full workflow must run offline."""

import pytest

import webapp.server as server
from tools.demo_desk_workflow import main


@pytest.fixture(autouse=True)
def _small_desk(monkeypatch):
    original = server.build_desk_data
    monkeypatch.setattr(server, "build_desk_data",
                        lambda **kw: original(n_notes=4, n_paths=4000, **kw))
    server._cache.payload = None
    server._cache.built_at = 0.0


def test_demo_runs_end_to_end_offline():
    result = main(verbose=False, n_paths=4000)
    assert result["pv"] > 0
    assert result["decision"] in ("APPROVED", "REJECTED", "MANUAL_REVIEW")
    assert result["term_sheet"].startswith("#") or len(result["term_sheet"]) > 200
    assert result["recommendation"]["approval_state"] in ("PROPOSED", "REJECTED_LIMIT",
                                                          "REJECTED_STALE_DATA")
    assert "totals" in result["attribution"]
