"""Expiry calendar built from observed data, never from an assumed weekday.

NSE has moved the index-option expiry weekday during the window any multi-year backtest
covers (Thursday historically; NIFTY weeklies expire Tuesdays as of 2026). A weekday rule is
therefore silently wrong for part of the sample; the only safe calendar is the set of expiry
dates that actually appear in the historical bhavcopy files.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class ExpiryCalendar:
    """Observed expiry dates per underlying."""

    _expiries: Mapping[str, tuple[date, ...]]

    @classmethod
    def from_observed(cls, observed: Mapping[str, set[date]]) -> ExpiryCalendar:
        """Build from expiry dates seen in historical data (bhavcopy or instrument master)."""
        return cls(MappingProxyType({u: tuple(sorted(d)) for u, d in observed.items()}))

    def expiries_for(self, underlying: str, on: date) -> list[date]:
        """Every known expiry on or after ``on``."""
        return [e for e in self._expiries.get(underlying, ()) if e >= on]

    def is_expiry(self, underlying: str, d: date) -> bool:
        return d in self._expiries.get(underlying, ())

    def nearest_expiry(self, underlying: str, on: date, *, min_dte: int) -> date:
        """The soonest expiry at least ``min_dte`` calendar days after ``on``."""
        for e in self.expiries_for(underlying, on):
            if (e - on).days >= min_dte:
                return e
        raise LookupError(f"no expiry for {underlying!r} at least {min_dte} days after {on}")
