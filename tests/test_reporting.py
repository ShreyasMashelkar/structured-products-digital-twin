"""L13 documentation engine: term sheet and scenario table from the same objects."""

import pytest

from spdt.products import Autocallable, TermSheet
from spdt.reporting import PricingSummary, maturity_scenarios, render_term_sheet

TS = TermSheet(
    product_type="autocallable",
    underlyings=("NIFTY",),
    notional=100.0,
    observation_times=(0.25, 0.5, 0.75, 1.0),
    params={"coupon_rate": 0.03, "autocall_level": 1.0, "coupon_barrier": 0.7, "knock_in": 0.6},
)
NOTE = Autocallable.from_termsheet(TS, initial_fixing=100.0)


def test_term_sheet_contains_the_economic_terms():
    md = render_term_sheet(TS)
    assert "Autocallable" in md
    assert "NIFTY" in md
    assert "0.03" in md  # coupon
    assert "0.6" in md  # knock-in


def test_pv_on_document_is_the_object_passed_in():
    # The document shows exactly the PV it was given — it cannot drift from the price.
    md = render_term_sheet(TS, summary=PricingSummary(pv=101.2345, std_error=0.0066))
    assert "101.2345" in md
    assert "0.0066" in md


def test_scenario_below_knock_in_pays_the_spot_return():
    # Final at 50% of initial, below the 60% knock-in: no coupon (below 70% barrier),
    # principal takes the spot return ⇒ ~50% of notional.
    [row] = maturity_scenarios(NOTE, (0.5,))
    assert row.ki_breached is True
    assert row.payment_pct == pytest.approx(50.0, abs=1e-6)


def test_scenario_at_par_returns_principal_plus_coupon():
    # Final at 100%: above knock-in and above coupon barrier ⇒ par + one 3% coupon.
    [row] = maturity_scenarios(NOTE, (1.0,))
    assert row.ki_breached is False
    assert row.payment_pct == pytest.approx(103.0, abs=1e-6)


def test_scenario_payment_is_monotone_in_terminal_level():
    rows = maturity_scenarios(NOTE, (0.4, 0.6, 0.8, 1.0, 1.2))
    payments = [r.payment_pct for r in rows]
    assert payments == sorted(payments)


def test_rendered_scenarios_appear_in_the_table():
    rows = maturity_scenarios(NOTE, (0.5, 1.0))
    md = render_term_sheet(TS, scenarios=rows)
    assert "Scenario at maturity" in md
    assert "Knock-in breached" in md
    assert "50%" in md and "100%" in md
