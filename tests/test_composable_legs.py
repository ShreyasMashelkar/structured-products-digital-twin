"""The composable DSL: a note wired from leg primitives equals the monolithic catalog one.

This is the design doc's "a structured note is a portfolio of optionality" made literal —
``brc_from_legs`` sums a zero-coupon bond, a fixed-coupon leg and a short down-and-in put, and
must price identically (same paths) to :class:`BarrierReverseConvertible`.
"""

import pytest

from spdt.pricing import BlackScholes, price_mc
from spdt.products import (
    BarrierReverseConvertible,
    CapitalProtectedNote,
    brc_from_legs,
    capital_protected_from_legs,
)

MODEL = BlackScholes(spot=100.0, r=0.03, q=0.0, sigma=0.25)
OBS = (0.25, 0.5, 0.75, 1.0)


def _price(p, seed=11):
    return price_mc(p, MODEL, n_paths=200_000, seed=seed).price


def test_composed_brc_equals_monolithic_brc():
    mono = BarrierReverseConvertible(
        notional=100.0, observation_times=OBS, coupon_rate=0.04, strike=1.0, knock_in=0.7
    )
    composed = brc_from_legs(100.0, OBS, 0.04, strike=1.0, knock_in=0.7)
    assert _price(composed) == pytest.approx(_price(mono), abs=1e-9)


def test_composed_cpn_equals_monolithic_cpn():
    mono = CapitalProtectedNote(
        notional=100.0, maturity=1.0, protection=1.0, participation=0.8, strike=1.0, cap=1.3
    )
    composed = capital_protected_from_legs(
        100.0, 1.0, protection=1.0, participation=0.8, strike=1.0, cap=1.3
    )
    assert _price(composed) == pytest.approx(_price(mono), abs=1e-9)


def test_composite_monitoring_is_the_union_of_its_legs():
    composed = brc_from_legs(100.0, OBS, 0.04)
    assert composed.monitoring_times() == OBS
