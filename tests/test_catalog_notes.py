"""BRC and capital-protected-note economics and their primitive decompositions.

These are the catalog's income/protection notes (design doc §3). The headline checks are the
*decompositions*: a BRC is a coupon bond short a down-and-in put, and a capital-protected note
is a zero-coupon bond long a participation call — priced on the same paths, the composite note
must equal the sum of its legs to Monte-Carlo precision.
"""

import pytest

from spdt.pricing import BlackScholes, price_mc
from spdt.products import (
    BarrierReverseConvertible,
    CapitalProtectedNote,
    DownBarrierPut,
    EuropeanOption,
    ReverseConvertible,
    TermSheet,
)

MODEL = BlackScholes(spot=100.0, r=0.03, q=0.0, sigma=0.25)
OBS = (0.25, 0.5, 0.75, 1.0)


def _price(product, seed=11):
    return price_mc(product, MODEL, n_paths=200_000, seed=seed).price


# --- Barrier reverse convertible --------------------------------------------------------

def _brc(coupon_rate=0.03, knock_in=0.7, strike=1.0):
    return BarrierReverseConvertible(
        notional=100.0,
        observation_times=OBS,
        coupon_rate=coupon_rate,
        strike=strike,
        knock_in=knock_in,
    )


def test_brc_decomposes_into_bond_minus_down_in_put():
    """BRC = Σ coupons + par·ZCB − down-and-in put, on identical paths."""
    seed = 5
    brc = _brc(coupon_rate=0.03, knock_in=0.7, strike=1.0)
    brc_pv = _price(brc, seed=seed)

    disc = MODEL.discount
    coupons = sum(disc(t) * 0.03 * 100.0 for t in OBS)
    par_leg = disc(1.0) * 100.0
    di_put = DownBarrierPut(
        strike=100.0, barrier=70.0, expiry=1.0, monitoring=OBS, knock_in=True
    )
    di_put_pv = _price(di_put, seed=seed)

    assert brc_pv == pytest.approx(coupons + par_leg - di_put_pv, abs=1e-6)


def test_brc_value_falls_as_knock_in_rises():
    # A higher knock-in is breached more often ⇒ the short put bites more ⇒ note worth less.
    assert _price(_brc(knock_in=0.6)) > _price(_brc(knock_in=0.85))


def test_brc_value_rises_with_coupon():
    assert _price(_brc(coupon_rate=0.05)) > _price(_brc(coupon_rate=0.01))


def test_brc_barrier_monitoring_is_distinct_from_coupon_dates():
    """Denser barrier monitoring (vs only at the single coupon date) catches more breaches,
    so the investor's short down-and-in put bites more and the note is worth less — i.e. the
    barrier schedule is genuinely decoupled from the coupon schedule, not conflated."""
    # One coupon at maturity, but the barrier is watched quarterly along the way.
    dense = BarrierReverseConvertible(
        notional=100.0, observation_times=(1.0,), coupon_rate=0.06, strike=1.0, knock_in=0.8,
        barrier_monitoring=(0.25, 0.5, 0.75, 1.0),
    )
    # Same note but the barrier is only checked at maturity (default).
    sparse = BarrierReverseConvertible(
        notional=100.0, observation_times=(1.0,), coupon_rate=0.06, strike=1.0, knock_in=0.8,
    )
    assert dense.monitoring_times() == (0.25, 0.5, 0.75, 1.0)
    assert sparse.monitoring_times() == (1.0,)
    assert _price(dense, seed=4) < _price(sparse, seed=4)


def test_brc_from_termsheet_matches_direct():
    ts = TermSheet(
        product_type="brc",
        underlyings=("NIFTY",),
        notional=100.0,
        observation_times=OBS,
        params={"coupon_rate": 0.03, "knock_in": 0.7, "strike": 1.0},
    )
    assert _price(BarrierReverseConvertible.from_termsheet(ts)) == _price(_brc())


# --- Reverse convertible ----------------------------------------------------------------

def test_reverse_convertible_decomposes_into_bond_minus_vanilla_put():
    """RC = Σ coupons + par·ZCB − vanilla put, on identical paths."""
    seed = 6
    rc = ReverseConvertible(
        notional=100.0, observation_times=OBS, coupon_rate=0.04, strike=1.0
    )
    rc_pv = _price(rc, seed=seed)

    disc = MODEL.discount
    coupons = sum(disc(t) * 0.04 * 100.0 for t in OBS)
    par_leg = disc(1.0) * 100.0
    # An always-breaching down-and-in put = a vanilla put, but priced on the RC's own grid
    # (the intermediate observation dates) so the comparison shares identical paths.
    put = DownBarrierPut(strike=100.0, barrier=1e12, expiry=1.0, monitoring=OBS, knock_in=True)
    put_pv = _price(put, seed=seed)
    assert rc_pv == pytest.approx(coupons + par_leg - put_pv, abs=1e-6)


def test_reverse_convertible_worth_less_than_barrier_version():
    # The RC's put is always live; the BRC's only knocks in below the barrier ⇒ RC worth less.
    rc = ReverseConvertible(notional=100.0, observation_times=OBS, coupon_rate=0.04, strike=1.0)
    brc = BarrierReverseConvertible(
        notional=100.0, observation_times=OBS, coupon_rate=0.04, strike=1.0, knock_in=0.7
    )
    assert _price(rc) < _price(brc)


# --- Capital-protected note -------------------------------------------------------------

def _cpn(protection=1.0, participation=1.0, cap=None):
    return CapitalProtectedNote(
        notional=100.0, maturity=1.0, protection=protection, participation=participation, cap=cap
    )


def test_cpn_decomposes_into_zcb_plus_participation_call():
    """CPN = protection·ZCB + participation·call(strike=par), on identical paths."""
    seed = 9
    cpn = _cpn(protection=1.0, participation=1.0)
    cpn_pv = _price(cpn, seed=seed)

    zcb = MODEL.discount(1.0) * 100.0
    call = EuropeanOption(strike=100.0, expiry=1.0, is_call=True)
    call_pv = _price(call, seed=seed)  # 1 unit notional per index point; S₀=100 ⇒ scales 1:1

    assert cpn_pv == pytest.approx(zcb + call_pv, abs=1e-6)


def test_cpn_is_floored_at_protected_principal():
    # 100% protection ⇒ PV ≥ the discounted protected principal, whatever the upside.
    assert _price(_cpn(protection=1.0, participation=0.0)) == pytest.approx(
        MODEL.discount(1.0) * 100.0, abs=1e-6
    )


def test_cpn_cap_reduces_value():
    assert _price(_cpn(cap=1.2)) < _price(_cpn(cap=None))


def test_cpn_more_participation_is_worth_more():
    assert _price(_cpn(participation=1.5)) > _price(_cpn(participation=0.5))
