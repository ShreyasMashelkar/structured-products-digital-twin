"""Two-curve discounting: the funding leg discounts on the issuer curve, the option leg on OIS.

This is the wiring that makes the bootstrapped funding spread (ADR-0002) a *priced* quantity
rather than a flat-rate approximation. A capital-protected note splits cleanly into a bond leg
(the protected principal ⇒ funding curve) and a participation call (⇒ OIS curve); the
two-curve price must equal funding·principal + the OIS-discounted call exactly.
"""

from datetime import date
from math import exp

import pytest

from spdt.core.types import Curve, year_fraction
from spdt.pricing import BlackScholes, Discounter, price_mc
from spdt.products import BarrierReverseConvertible, CapitalProtectedNote, EuropeanOption

ANCHOR = date(2024, 1, 1)
R = 0.06
MODEL = BlackScholes(spot=100.0, r=R, q=0.0, sigma=0.2)


def _ois(rate: float = R) -> Curve:
    pillars = (date(2024, 12, 31), date(2025, 12, 31), date(2026, 12, 31))
    return Curve(
        anchor=ANCHOR,
        pillars=pillars,
        discount_factors={d: exp(-rate * year_fraction(ANCHOR, d)) for d in pillars},
    )


def _funding(spread: float) -> Curve:
    return Curve(
        anchor=ANCHOR,
        spread_over=_ois(),
        spread_knots={date(2025, 1, 1): spread, date(2027, 1, 1): spread},
    )


def test_cpn_two_curve_price_equals_funding_bond_plus_ois_call():
    spread = 0.02
    disc = Discounter(ois=_ois().df, funding=_funding(spread).df)
    cpn = CapitalProtectedNote(notional=100.0, maturity=1.0, protection=1.0, participation=1.0)

    seed = 3
    pv = price_mc(cpn, MODEL, n_paths=200_000, seed=seed, discount=disc).price

    # Option leg = an ATM call discounted on OIS (= the model's flat r): same paths, same seed.
    call = EuropeanOption(strike=100.0, expiry=1.0, is_call=True)
    call_pv = price_mc(call, MODEL, n_paths=200_000, seed=seed).price
    bond_pv = 100.0 * _funding(spread).df(1.0)

    assert pv == pytest.approx(bond_pv + call_pv, abs=1e-6)


def test_zero_funding_spread_matches_single_ois_curve():
    """With no spread the two-curve discounter collapses to plain OIS discounting."""
    ois = _ois()
    two_curve = Discounter(ois=ois.df, funding=_funding(0.0).df)
    cpn = CapitalProtectedNote(notional=100.0, maturity=1.0, protection=1.0, participation=1.0)

    pv_two = price_mc(cpn, MODEL, n_paths=100_000, seed=7, discount=two_curve).price
    pv_one = price_mc(cpn, MODEL, n_paths=100_000, seed=7, discount=ois.df).price
    assert pv_two == pytest.approx(pv_one, abs=1e-9)


def test_wider_funding_spread_lowers_the_note_value():
    """A wider issuer spread cheapens the bond legs ⇒ the note's PV falls."""
    brc = BarrierReverseConvertible(
        notional=100.0, observation_times=(0.5, 1.0), coupon_rate=0.04, knock_in=0.7
    )
    tight = Discounter(ois=_ois().df, funding=_funding(0.005).df)
    wide = Discounter(ois=_ois().df, funding=_funding(0.05).df)
    pv_tight = price_mc(brc, MODEL, n_paths=100_000, seed=4, discount=tight).price
    pv_wide = price_mc(brc, MODEL, n_paths=100_000, seed=4, discount=wide).price
    assert pv_wide < pv_tight
