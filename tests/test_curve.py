"""Curve discounting: OIS bootstrap shape + funding-as-spread-over-OIS (ADR-0002)."""

from datetime import date
from math import exp, log

import pytest

from spdt.core.types import Curve, InterpMethod, year_fraction

ANCHOR = date(2024, 1, 1)


def _flat_ois(rate: float) -> Curve:
    """OIS curve with a constant continuously-compounded zero rate."""
    pillars = (date(2024, 12, 31), date(2025, 12, 31), date(2026, 12, 31))
    dfs = {d: exp(-rate * year_fraction(ANCHOR, d)) for d in pillars}
    return Curve(anchor=ANCHOR, pillars=pillars, discount_factors=dfs)


def test_discount_factor_is_one_at_anchor():
    assert _flat_ois(0.06).discount_factor(ANCHOR) == 1.0


def test_flat_curve_recovers_its_zero_rate_between_pillars():
    curve = _flat_ois(0.06)
    # Log-linear interpolation of a constant zero rate is exact at an off-pillar date.
    assert curve.zero_rate(date(2025, 6, 30)) == pytest.approx(0.06, abs=1e-12)


def test_zero_rate_extrapolates_flat_beyond_last_pillar():
    curve = _flat_ois(0.06)
    assert curve.zero_rate(date(2030, 1, 1)) == pytest.approx(0.06, abs=1e-12)


def test_forward_rate_of_flat_curve_equals_zero_rate():
    curve = _flat_ois(0.06)
    fwd = curve.forward_rate(date(2024, 12, 31), date(2025, 12, 31))
    assert fwd == pytest.approx(0.06, abs=1e-12)


def test_discount_factors_decrease_with_maturity():
    curve = _flat_ois(0.06)
    assert curve.discount_factor(date(2025, 1, 1)) > curve.discount_factor(date(2026, 1, 1))


def test_funding_curve_is_ois_discounted_by_the_spread():
    ois = _flat_ois(0.06)
    spread = 0.0125
    funding = Curve(
        anchor=ANCHOR,
        spread_over=ois,
        spread_knots={date(2025, 1, 1): spread, date(2027, 1, 1): spread},
    )
    target = date(2025, 7, 1)
    tau = year_fraction(ANCHOR, target)
    expected = ois.discount_factor(target) * exp(-spread * tau)
    assert funding.discount_factor(target) == pytest.approx(expected, rel=1e-12)
    # Funding zero rate sits a constant spread above OIS.
    assert funding.zero_rate(target) - ois.zero_rate(target) == pytest.approx(spread, abs=1e-12)


def test_ois_curve_requires_discount_factors():
    with pytest.raises(ValueError, match="discount_factors"):
        Curve(anchor=ANCHOR)


def test_funding_curve_requires_spread_knots():
    with pytest.raises(ValueError, match="spread_knots"):
        Curve(anchor=ANCHOR, spread_over=_flat_ois(0.06))


def test_unsupported_interp_is_rejected():
    with pytest.raises(NotImplementedError):
        Curve(
            anchor=ANCHOR,
            discount_factors={date(2025, 1, 1): 0.95},
            interp=InterpMethod.MONOTONE_CONVEX,
        )
