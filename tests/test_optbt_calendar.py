"""Expiry calendar: observed dates only — a weekday rule is silently wrong across history."""

from __future__ import annotations

from datetime import date

import pytest

from spdt.optbt.calendar import ExpiryCalendar


def _cal() -> ExpiryCalendar:
    return ExpiryCalendar.from_observed({
        "NIFTY": {date(2026, 8, 27), date(2026, 9, 24), date(2026, 10, 29)},
    })


def test_expiries_come_from_the_data_not_a_weekday_rule() -> None:
    assert _cal().expiries_for("NIFTY", date(2026, 8, 1)) == [
        date(2026, 8, 27), date(2026, 9, 24), date(2026, 10, 29),
    ]


def test_expiries_before_the_as_of_date_are_excluded() -> None:
    assert _cal().expiries_for("NIFTY", date(2026, 9, 1)) == [
        date(2026, 9, 24), date(2026, 10, 29),
    ]


def test_is_expiry() -> None:
    cal = _cal()
    assert cal.is_expiry("NIFTY", date(2026, 8, 27))
    assert not cal.is_expiry("NIFTY", date(2026, 8, 26))
    assert not cal.is_expiry("BANKNIFTY", date(2026, 8, 27))


def test_nearest_expiry_respects_minimum_days_to_expiry() -> None:
    # 2026-08-25 is 2 days before the Aug expiry; min_dte=7 must skip to September.
    assert _cal().nearest_expiry("NIFTY", date(2026, 8, 25), min_dte=7) == date(2026, 9, 24)


def test_nearest_expiry_raises_when_nothing_qualifies() -> None:
    cal = ExpiryCalendar.from_observed({"NIFTY": {date(2026, 8, 27)}})
    with pytest.raises(LookupError, match="no expiry"):
        cal.nearest_expiry("NIFTY", date(2026, 8, 26), min_dte=30)


def test_unknown_underlying_has_no_expiries() -> None:
    assert _cal().expiries_for("BANKNIFTY", date(2026, 8, 1)) == []
