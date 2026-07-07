"""Analytics engine to track and attribute historical replication error."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Sequence


@dataclass(frozen=True)
class DailyTrackingError:
    """A record of the daily P&L difference between a product and its hedge."""
    date: date
    product_pnl: float
    hedge_pnl: float
    unexplained_pnl: float    # product_pnl - hedge_pnl
    primary_driver: str       # e.g., "cross_gamma", "jump_to_default", "gap_risk"


class ReplicationAnalyticsEngine:
    """Stores and analyzes the historical tracking error of the hedge portfolio."""

    def __init__(self):
        self._history: list[DailyTrackingError] = []

    def record_daily_pnl(self, record: DailyTrackingError):
        """Append a daily tracking error record to the history."""
        self._history.append(record)

    def get_history(self) -> Sequence[DailyTrackingError]:
        """Return the sorted history of daily tracking errors."""
        return sorted(self._history, key=lambda r: r.date)

    def compute_ytd_tracking_error(self) -> float:
        """Sum the unexplained P&L over the stored history."""
        return sum(record.unexplained_pnl for record in self._history)

    def compute_tracking_error_volatility(self) -> float:
        """Compute the standard deviation of the unexplained P&L."""
        if len(self._history) < 2:
            return 0.0

        mean_unexplained = self.compute_ytd_tracking_error() / len(self._history)
        variance = sum((r.unexplained_pnl - mean_unexplained) ** 2 for r in self._history) / (len(self._history) - 1)
        return math.sqrt(variance)

    def attribute_variance(self) -> dict[str, float]:
        """Return the percentage contribution of each primary driver to the total absolute unexplained P&L."""
        if not self._history:
            return {}

        total_abs_unexplained = sum(abs(record.unexplained_pnl) for record in self._history)
        if total_abs_unexplained == 0.0:
            return {}

        contributions: dict[str, float] = {}
        for record in self._history:
            driver = record.primary_driver
            contributions[driver] = contributions.get(driver, 0.0) + abs(record.unexplained_pnl)

        return {driver: (amount / total_abs_unexplained) for driver, amount in contributions.items()}
