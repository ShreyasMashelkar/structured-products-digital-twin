"""Forward smile extraction and smile-stickiness regimes (L2)."""

import math

import pytest

from spdt.vol import (
    StickyRegime,
    atm_vol_under_move,
    forward_atm_vol,
    forward_total_variance,
    skew_delta_adjustment,
)


def _flat(sigma):
    return lambda k, t: sigma  # noqa: ARG005 - flat surface


def _skew(atm=0.20, slope=-0.10):
    # Equity put-skew: vol falls with log-moneyness k = ln(K/F).
    return lambda k, t: atm + slope * k


# --- forward smile -----------------------------------------------------------------------

def test_forward_vol_of_flat_surface_equals_the_flat_vol():
    iv = _flat(0.2)
    assert forward_atm_vol(iv, 0.5, 1.0) == pytest.approx(0.2, abs=1e-12)


def test_forward_variance_is_additive():
    iv = _flat(0.25)
    # w(0,1) = w(0,0.4) + forward variance over (0.4, 1].
    total = 0.25**2 * 1.0
    split = 0.25**2 * 0.4 + forward_total_variance(iv, 0.0, 0.4, 1.0)
    assert split == pytest.approx(total, abs=1e-12)


def test_forward_variance_requires_increasing_tenor():
    with pytest.raises(ValueError, match="t2 > t1"):
        forward_total_variance(_flat(0.2), 0.0, 1.0, 0.5)


# --- stickiness --------------------------------------------------------------------------

def test_sticky_moneyness_leaves_atm_vol_unchanged():
    iv = _skew()
    base = iv(0.0, 1.0)
    down = atm_vol_under_move(iv, 1.0, math.log(0.95), StickyRegime.MONEYNESS)
    assert down == pytest.approx(base, abs=1e-12)


def test_sticky_strike_raises_atm_vol_on_a_down_move_for_a_put_skew():
    iv = _skew(atm=0.20, slope=-0.10)
    base = iv(0.0, 1.0)
    down = atm_vol_under_move(iv, 1.0, math.log(0.90), StickyRegime.STRIKE)  # spot −10%
    up = atm_vol_under_move(iv, 1.0, math.log(1.10), StickyRegime.STRIKE)    # spot +10%
    assert down > base > up  # leverage effect: spot down ⇒ ATM vol up


def test_skew_delta_adjustment_is_zero_for_a_flat_surface():
    assert skew_delta_adjustment(_flat(0.2), 1.0, 100.0, vega=30.0) == pytest.approx(0.0, abs=1e-9)


def test_skew_delta_adjustment_is_negative_for_a_put_skew():
    # Put-skew (∂σ/∂k < 0) ⇒ sticky-strike lowers a long-vega option's realised delta vs BS.
    adj = skew_delta_adjustment(_skew(slope=-0.10), 1.0, 100.0, vega=30.0)
    assert adj < 0.0
