"""Tests for the intraday alert engine — pure rules + a stateful engine with ack/resolve.

Rules are pure functions from market/book numbers to an alert (or None); the engine dedups
repeated conditions, stamps ids/timestamps, tracks acknowledgement, and resolves alerts
whose condition has cleared. No data-source coupling: callers feed values in.
"""

from datetime import date, datetime

from spdt.alerts import (
    AlertEngine,
    barrier_distance_alert,
    drawdown_alert,
    greek_limit_alert,
    observation_approaching_alert,
    stale_data_alert,
)

_NOW = datetime(2026, 7, 10, 11, 30, 0)


# --- rules --------------------------------------------------------------------


def test_barrier_distance_severity_scales_with_proximity():
    assert barrier_distance_alert(spot=24000, barrier=18000, trade_id="T1") is None  # 25% away
    warning = barrier_distance_alert(spot=24000, barrier=22000, trade_id="T1")  # ~8.3% away
    assert warning.severity == "WARNING" and warning.trade_id == "T1"
    critical = barrier_distance_alert(spot=24000, barrier=23500, trade_id="T1")  # ~2.1% away
    assert critical.severity == "CRITICAL"
    assert critical.metric == "barrier_distance_pct" and critical.value < critical.threshold


def test_greek_limit_alert_fires_on_breach_only():
    assert greek_limit_alert("delta", value=500.0, limit=1000.0) is None
    alert = greek_limit_alert("delta", value=-1500.0, limit=1000.0)
    assert alert.severity == "CRITICAL" and alert.category == "greek_limit"
    assert alert.value == 1500.0 and alert.threshold == 1000.0  # magnitude vs limit


def test_stale_data_alert_from_quote_age():
    fresh = datetime(2026, 7, 10, 11, 29, 0)
    assert stale_data_alert("NIFTY", last_update=fresh, now=_NOW, max_age_s=300) is None
    old = datetime(2026, 7, 10, 10, 0, 0)
    alert = stale_data_alert("NIFTY", last_update=old, now=_NOW, max_age_s=300)
    assert alert.severity == "WARNING" and alert.category == "stale_data"


def test_observation_approaching_alert():
    assert observation_approaching_alert(date(2026, 9, 1), as_of=date(2026, 7, 10),
                                         trade_id="T2") is None
    alert = observation_approaching_alert(date(2026, 7, 14), as_of=date(2026, 7, 10),
                                          trade_id="T2", within_days=5)
    assert alert.severity == "INFO" and alert.value == 4


def test_drawdown_alert_from_peak():
    assert drawdown_alert(pnl=-500.0, peak_pnl=0.0, limit=1000.0) is None
    alert = drawdown_alert(pnl=-1500.0, peak_pnl=500.0, limit=1000.0)
    assert alert.severity == "CRITICAL" and alert.value == 2000.0  # peak-to-trough


# --- engine ---------------------------------------------------------------------


def _breach(value=1500.0):
    return greek_limit_alert("delta", value=value, limit=1000.0, trade_id="T1")


def test_engine_stamps_and_dedups_repeated_conditions():
    engine = AlertEngine(clock=lambda: _NOW)
    engine.update([_breach()])
    engine.update([_breach(value=1600.0)])  # same condition, refreshed value
    assert len(engine.open_alerts) == 1
    alert = engine.open_alerts[0]
    assert alert.id and alert.timestamp == _NOW and alert.status == "OPEN"
    assert alert.value == 1600.0  # latest reading


def test_engine_acknowledge_keeps_alert_open_but_marked():
    engine = AlertEngine(clock=lambda: _NOW)
    engine.update([_breach()])
    engine.acknowledge(engine.open_alerts[0].id)
    assert engine.open_alerts[0].status == "ACKNOWLEDGED"
    engine.update([_breach()])  # re-firing must not reset the acknowledgement
    assert engine.open_alerts[0].status == "ACKNOWLEDGED"


def test_engine_resolves_cleared_conditions_and_keeps_history():
    engine = AlertEngine(clock=lambda: _NOW)
    engine.update([_breach()])
    engine.update([])  # condition cleared
    assert not engine.open_alerts
    assert len(engine.history) == 1 and engine.history[0].status == "RESOLVED"


def test_distinct_trades_raise_distinct_alerts():
    engine = AlertEngine(clock=lambda: _NOW)
    engine.update([
        greek_limit_alert("delta", value=2000.0, limit=1000.0, trade_id="T1"),
        greek_limit_alert("delta", value=3000.0, limit=1000.0, trade_id="T2"),
    ])
    assert len(engine.open_alerts) == 2
    assert {a.trade_id for a in engine.open_alerts} == {"T1", "T2"}
