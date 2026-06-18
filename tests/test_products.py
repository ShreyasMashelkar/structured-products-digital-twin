"""Barrier in/out parity and autocallable economics — the DSL composition checks."""

import pytest

from spdt.pricing import BlackScholes, bs_vanilla, price_mc
from spdt.products import Autocallable, DownBarrierPut, TermSheet

MODEL = BlackScholes(spot=100.0, r=0.03, q=0.0, sigma=0.25)
MONITORING = (0.25, 0.5, 0.75, 1.0)


def test_down_in_plus_down_out_equals_vanilla_put():
    """down-and-in + down-and-out = vanilla put, by construction on every path."""
    di = DownBarrierPut(
        strike=100.0, barrier=80.0, expiry=1.0, monitoring=MONITORING, knock_in=True
    )
    do = DownBarrierPut(
        strike=100.0, barrier=80.0, expiry=1.0, monitoring=MONITORING, knock_in=False
    )
    p_di = price_mc(di, MODEL, n_paths=200_000, seed=7).price
    p_do = price_mc(do, MODEL, n_paths=200_000, seed=7).price
    vanilla = bs_vanilla(100.0, 100.0, 1.0, 0.03, 0.0, 0.25, is_call=False)
    assert p_di + p_do == pytest.approx(vanilla, abs=0.15)


def _autocall(coupon_rate=0.02, knock_in=0.6, memory=False):
    return Autocallable(
        notional=100.0,
        observation_times=MONITORING,
        coupon_rate=coupon_rate,
        autocall_level=1.0,
        coupon_barrier=0.7,
        knock_in=knock_in,
        memory=memory,
    )


def _price(product):
    return price_mc(product, MODEL, n_paths=100_000, seed=11).price


def test_autocallable_prices_positive_and_bounded():
    pv = _price(_autocall())
    assert 0.0 < pv < 130.0  # below par + all coupons, undiscounted upper bound


def test_value_increases_with_coupon():
    assert _price(_autocall(coupon_rate=0.04)) > _price(_autocall(coupon_rate=0.01))


def test_value_increases_with_more_downside_protection():
    # A lower knock-in barrier means principal is protected over a wider range ⇒ worth more.
    assert _price(_autocall(knock_in=0.5)) > _price(_autocall(knock_in=0.8))


def test_memory_coupon_adds_value():
    assert _price(_autocall(memory=True)) >= _price(_autocall(memory=False))


def test_from_termsheet_matches_direct_construction():
    ts = TermSheet(
        product_type="autocallable",
        underlyings=("NIFTY",),
        notional=100.0,
        observation_times=MONITORING,
        params={"coupon_rate": 0.02, "coupon_barrier": 0.7, "knock_in": 0.6},
    )
    assert _price(Autocallable.from_termsheet(ts)) == _price(_autocall())
