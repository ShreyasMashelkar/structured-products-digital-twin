"""Intraday risk alert engine (Phase 12): pure rules + stateful ack/resolve tracking.

Rules are pure functions from market/book numbers to an :class:`Alert` (or ``None`` when
within limits) — no data-source coupling, callers feed values in from snapshots, the book,
or the paper broker. The :class:`AlertEngine` dedups repeated conditions (one open alert per
condition, refreshed with the latest reading), stamps ids/timestamps, and moves alerts
through ``OPEN → ACKNOWLEDGED → RESOLVED``. History is append-only for the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

Severity = Literal["INFO", "WARNING", "CRITICAL"]
Status = Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"]


@dataclass
class Alert:
    severity: Severity
    category: str
    message: str
    metric: str
    value: float
    threshold: float
    trade_id: str | None = None
    id: str = ""          # stamped by the engine
    timestamp: datetime | None = None
    status: Status = "OPEN"

    @property
    def key(self) -> tuple[str, str, str | None]:
        """Identity of the underlying condition — one open alert per key."""
        return (self.category, self.metric, self.trade_id)


# --- rules (pure) ---------------------------------------------------------------


def barrier_distance_alert(
    *, spot: float, barrier: float, trade_id: str | None = None,
    warning_pct: float = 10.0, critical_pct: float = 5.0,
) -> Alert | None:
    """Spot approaching a (down-)barrier: WARNING inside ``warning_pct``, CRITICAL inside ``critical_pct``."""
    distance_pct = (spot - barrier) / spot * 100.0
    if distance_pct > warning_pct:
        return None
    critical = distance_pct <= critical_pct
    return Alert(
        severity="CRITICAL" if critical else "WARNING",
        category="barrier",
        message=f"spot {spot:,.0f} is {distance_pct:.1f}% from barrier {barrier:,.0f}",
        metric="barrier_distance_pct",
        value=distance_pct,
        threshold=critical_pct if critical else warning_pct,
        trade_id=trade_id,
    )


def greek_limit_alert(
    name: str, *, value: float, limit: float, trade_id: str | None = None,
) -> Alert | None:
    """Net Greek magnitude beyond its desk limit."""
    magnitude = abs(value)
    if magnitude <= limit:
        return None
    return Alert(
        severity="CRITICAL",
        category="greek_limit",
        message=f"net {name} {value:,.0f} breaches limit {limit:,.0f}",
        metric=name,
        value=magnitude,
        threshold=limit,
        trade_id=trade_id,
    )


def stale_data_alert(
    what: str, *, last_update: datetime, now: datetime, max_age_s: float = 300.0,
) -> Alert | None:
    """Market data older than ``max_age_s`` — risk numbers are running blind."""
    age_s = (now - last_update).total_seconds()
    if age_s <= max_age_s:
        return None
    return Alert(
        severity="WARNING",
        category="stale_data",
        message=f"{what} data is {age_s:.0f}s old (limit {max_age_s:.0f}s)",
        metric=f"age_s.{what}",
        value=age_s,
        threshold=max_age_s,
    )


def observation_approaching_alert(
    observation_date: date, *, as_of: date, trade_id: str | None = None, within_days: int = 7,
) -> Alert | None:
    """An autocall/coupon observation date is near — pin/observation risk window."""
    days = (observation_date - as_of).days
    if days > within_days or days < 0:
        return None
    return Alert(
        severity="INFO",
        category="observation",
        message=f"observation date {observation_date.isoformat()} in {days} day(s)",
        metric="days_to_observation",
        value=float(days),
        threshold=float(within_days),
        trade_id=trade_id,
    )


def drawdown_alert(
    *, pnl: float, peak_pnl: float, limit: float, trade_id: str | None = None,
) -> Alert | None:
    """Peak-to-trough P&L drawdown beyond the limit."""
    drawdown = peak_pnl - pnl
    if drawdown <= limit:
        return None
    return Alert(
        severity="CRITICAL",
        category="drawdown",
        message=f"P&L drawdown {drawdown:,.0f} exceeds limit {limit:,.0f}",
        metric="drawdown",
        value=drawdown,
        threshold=limit,
        trade_id=trade_id,
    )


# --- engine ---------------------------------------------------------------------


class AlertEngine:
    """Tracks alert lifecycle across evaluation rounds.

    Feed :meth:`update` the list of currently-firing conditions each round: new conditions
    open alerts, repeated ones refresh the reading (preserving acknowledgement), and
    conditions that stop firing are RESOLVED.
    """

    def __init__(self, *, clock=datetime.now) -> None:
        self.clock = clock
        self.history: list[Alert] = []
        self._open: dict[tuple, Alert] = {}
        self._seq = 0

    @property
    def open_alerts(self) -> list[Alert]:
        return list(self._open.values())

    def update(self, conditions: list[Alert | None]) -> list[Alert]:
        """Reconcile currently-firing conditions; returns the open alerts."""
        firing = {c.key: c for c in conditions if c is not None}
        for key, condition in firing.items():
            existing = self._open.get(key)
            if existing is not None:  # refresh the reading, keep id/status/timestamp
                existing.value = condition.value
                existing.severity = condition.severity
                existing.message = condition.message
            else:
                self._seq += 1
                condition.id = f"A{self._seq}"
                condition.timestamp = self.clock()
                condition.status = "OPEN"
                self._open[key] = condition
                self.history.append(condition)
        for key in [k for k in self._open if k not in firing]:
            self._open.pop(key).status = "RESOLVED"
        return self.open_alerts

    def acknowledge(self, alert_id: str) -> None:
        for alert in self._open.values():
            if alert.id == alert_id:
                alert.status = "ACKNOWLEDGED"


__all__ = [
    "Alert", "AlertEngine", "barrier_distance_alert", "drawdown_alert",
    "greek_limit_alert", "observation_approaching_alert", "stale_data_alert",
]
