"""Building a note from contracts that actually quote.

The web app solved participation continuously, off a model price, funded on the wholesale
curve. All three are wrong for a number handed to a client. These tests pin the executable
build against the figures in the term-sheet pack, which were derived independently by hand.
"""

from datetime import date, timedelta

import pytest

from spdt.structurer.executable import (
    ListedCall,
    build_participation_note,
    calls_from_chain,
)

AS_OF = date(2026, 8, 28)
SPOT = 24175.7
# The four NIFTY legs the pack was priced on, at the live ask, 28 Aug 2026.
LIVE = [
    ListedCall(date(2026, 12, 29), 24000.0, 1045.00, 65, bid=1040.00),
    ListedCall(date(2027, 3, 30), 24000.0, 1510.00, 65, bid=1494.90),
    ListedCall(date(2027, 12, 28), 24000.0, 2862.50, 65, bid=2811.00),
    ListedCall(date(2028, 12, 26), 24000.0, 4762.50, 65, bid=4511.00),
]


def _note(maturity, floor):
    return build_participation_note(
        spot=SPOT, as_of=AS_OF, maturity_years=maturity, floor=floor,
        chain=LIVE, fd_rate=0.075, notional=1e7, fee=0.01,
    )


@pytest.mark.parametrize("maturity,floor,lots,participation", [
    (123/365, 1.00,  2, 0.31),
    (123/365, 0.95,  9, 1.41),
    (123/365, 0.90, 16, 2.51),
    (487/365, 1.00,  4, 0.63),
    (487/365, 0.90,  9, 1.41),
    (851/365, 1.00,  4, 0.63),
    (851/365, 0.90,  7, 1.10),
])
def test_reproduces_the_published_term_sheet(maturity, floor, lots, participation):
    """The acceptance test: the engine must produce the numbers already sent to a client."""
    n = _note(maturity, floor)
    assert n.lots == lots
    assert n.participation(SPOT) == pytest.approx(participation, abs=0.005)


def test_full_protection_never_loses_capital():
    for maturity in (123/365, 487/365, 851/365):
        n = _note(maturity, 1.00)
        assert n.capital_protected
        assert n.worst_case >= 0.0
        assert n.breakeven() is None          # no level returns less than the mandate
        assert n.value_at(0.0) >= n.notional  # a total wipeout still repays


def test_a_buffered_note_loses_exactly_its_floor_and_no_more():
    n = _note(123/365, 0.90)
    assert n.worst_case == pytest.approx(-0.0969, abs=0.001)
    assert n.value_at(0.0) == pytest.approx(n.value_at(n.leg.strike))  # flat below the strike
    be = n.breakeven()
    assert be is not None and be == pytest.approx(24932, abs=5)
    assert n.value_at(be) == pytest.approx(n.notional, abs=1.0)


def test_the_ask_is_used_not_the_mid():
    """Paying the mid would flatter every figure. The client is buying, so it is the ask."""
    n = _note(123/365, 0.90)
    assert n.option_cost == pytest.approx(n.lots * 1045.00 * 65)
    mid = 0.5 * (1040.00 + 1045.00)
    assert n.option_cost > n.lots * mid * 65


def test_whole_lots_only_with_the_remainder_carried():
    n = _note(123/365, 0.90)
    budget = n.notional - n.fd_invested - n.notional * n.fee
    assert n.units % 65 == 0
    assert 0 <= n.residual < n.leg.cost_per_lot          # could not afford one more
    assert n.option_cost + n.residual == pytest.approx(budget)
    assert n.residual_matures > n.residual               # it sits in the deposit and earns


def test_the_clients_own_deposit_funds_the_floor():
    """A 7.5% deposit discounts harder than a 5.3% curve, so it leaves a bigger option budget
    and buys more upside. The web app, funding on the curve, understated this."""
    rich = build_participation_note(spot=SPOT, as_of=AS_OF, maturity_years=851/365, floor=1.00,
                                    chain=LIVE, fd_rate=0.075)
    poor = build_participation_note(spot=SPOT, as_of=AS_OF, maturity_years=851/365, floor=1.00,
                                    chain=LIVE, fd_rate=0.053)
    assert rich.fd_invested < poor.fd_invested
    assert rich.lots >= poor.lots


def test_refuses_rather_than_reporting_a_fractional_lot():
    """A 4-month fully-protected note at a 2% fee has no budget left. Reporting 0.4 lots would
    be a number nobody can transact at."""
    with pytest.raises(ValueError, match="cannot buy one lot"):
        build_participation_note(spot=SPOT, as_of=AS_OF, maturity_years=123/365, floor=1.00,
                                 chain=LIVE, fd_rate=0.075, fee=0.02)


def test_refuses_an_unknown_lot_size():
    with pytest.raises(ValueError, match="lot size unknown"):
        ListedCall(date(2026, 12, 29), 24000.0, 1045.00, 0)


def test_picks_the_expiry_closest_to_the_requested_maturity():
    assert _note(0.35, 0.90).leg.expiry == date(2026, 12, 29)
    assert _note(1.30, 0.90).leg.expiry == date(2027, 12, 28)
    assert _note(2.30, 0.90).leg.expiry == date(2028, 12, 26)


def test_chain_filter_drops_what_cannot_be_ordered():
    from spdt.data.ingest import RawOptionQuote

    e = AS_OF + timedelta(days=120)
    rows = (
        RawOptionQuote(e, 24000.0, True, 1000.0, ask=1045.0, bid=1040.0, lot_size=65),
        RawOptionQuote(e, 24000.0, False, 900.0, ask=905.0, bid=900.0, lot_size=65),  # a put
        RawOptionQuote(e, 25000.0, True, 500.0, ask=None, bid=None, lot_size=65),     # no ask
        RawOptionQuote(e, 26000.0, True, 200.0, ask=205.0, bid=200.0, lot_size=0),    # no lot
    )
    calls = calls_from_chain(rows)
    assert [c.strike for c in calls] == [24000.0]


def test_refuses_to_substitute_a_different_tenor():
    """A 2.3y request against a chain reaching 1.3y is a different product, not a rounding.
    The desk's own chain has exactly this gap, so the guard is not hypothetical."""
    short_chain = LIVE[:3]  # out to 487 days only
    with pytest.raises(ValueError, match="no contract quotes at that tenor"):
        build_participation_note(spot=SPOT, as_of=AS_OF, maturity_years=851/365, floor=0.90,
                                 chain=short_chain, fd_rate=0.075)
    # ...but it can be accepted deliberately
    n = build_participation_note(spot=SPOT, as_of=AS_OF, maturity_years=851/365, floor=0.90,
                                 chain=short_chain, fd_rate=0.075, max_tenor_mismatch=0.60)
    assert n.leg.expiry == date(2027, 12, 28)


# --- the inverse solve: client names the upside, the floor is what it costs ----------------


@pytest.mark.parametrize("target", [0.5, 1.0, 1.5, 2.0, 2.5])
def test_floor_for_participation_meets_the_target(target):
    from spdt.structurer.executable import floor_for_participation

    n = floor_for_participation(spot=SPOT, as_of=AS_OF, maturity_years=123/365,
                                target_participation=target, chain=LIVE, fd_rate=0.075)
    assert n.participation(SPOT) >= target - 1e-9        # met, never missed
    assert n.participation(SPOT) < target + (65 * SPOT / n.notional)  # by under one lot
    assert 0.0 < n.floor <= 1.0


def test_more_upside_costs_more_capital():
    from spdt.structurer.executable import floor_for_participation

    floors = [
        floor_for_participation(spot=SPOT, as_of=AS_OF, maturity_years=123/365,
                                target_participation=t, chain=LIVE).floor
        for t in (0.5, 1.0, 1.5, 2.0, 2.5)
    ]
    assert floors == sorted(floors, reverse=True)        # strictly cheaper upside ⇒ higher floor


def test_a_cheap_target_returns_full_protection_not_a_worse_floor():
    """Asking for less than the interest budget buys should hand back 100% protection and
    the extra upside, not a floor above par."""
    from spdt.structurer.executable import floor_for_participation

    n = floor_for_participation(spot=SPOT, as_of=AS_OF, maturity_years=851/365,
                                target_participation=0.05, chain=LIVE)
    assert n.floor == pytest.approx(1.0)
    assert n.capital_protected


def test_an_unaffordable_target_is_refused():
    from spdt.structurer.executable import floor_for_participation

    with pytest.raises(ValueError, match="more than the mandate"):
        floor_for_participation(spot=SPOT, as_of=AS_OF, maturity_years=123/365,
                                target_participation=25.0, chain=LIVE)


def test_refuses_a_strike_too_far_from_spot_to_be_participation():
    """Live, the 850-day NIFTY expiry quoted exactly one strike: 30,000, 24% out of the money.
    The builder took it and reported 4.56x 'participation' — on a call that pays nothing until
    the index rises 24%. The word does not mean that."""
    far = [ListedCall(date(2028, 12, 26), 30000.0, 1190.00, 65, bid=1082.00)]
    with pytest.raises(ValueError, match="too far to call the payoff participation"):
        build_participation_note(spot=SPOT, as_of=AS_OF, maturity_years=851/365, floor=0.90,
                                 chain=far, fd_rate=0.075)
    # the inverse solve shares the hazard and the guard
    from spdt.structurer.executable import floor_for_participation
    with pytest.raises(ValueError, match="too far to call the payoff participation"):
        floor_for_participation(spot=SPOT, as_of=AS_OF, maturity_years=851/365,
                                target_participation=1.5, chain=far, fd_rate=0.075)


def test_a_near_strike_is_still_accepted():
    """The pack's own legs sit within a percent or two of spot and must keep working."""
    n = build_participation_note(spot=SPOT, as_of=AS_OF, maturity_years=123/365, floor=0.90,
                                 chain=LIVE, fd_rate=0.075)
    assert abs(n.leg.strike / SPOT - 1) < 0.05
    assert n.lots == 16
