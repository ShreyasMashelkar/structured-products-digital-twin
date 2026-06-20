"""Generic factsheet + scenario-at-maturity table for the income/protection notes (L13).

The scenario table is replayed through each product's own ``cashflows``, so the document can
never disagree with the pricer — checked here for a BRC and a capital-protected note.
"""

from spdt.reporting import PricingSummary, render_factsheet, terminal_scenarios
from spdt.products import BarrierReverseConvertible, CapitalProtectedNote, TermSheet

LEVELS = (0.5, 0.7, 0.9, 1.0, 1.2)


def test_brc_scenarios_lose_capital_below_the_barrier():
    brc = BarrierReverseConvertible(
        notional=100.0, observation_times=(0.5, 1.0), coupon_rate=0.04, strike=1.0, knock_in=0.7
    )
    rows = {r.terminal_level: r for r in terminal_scenarios(brc, LEVELS)}
    # Below the 70% knock-in and below par: principal is cut (payment < 100% of notional).
    assert rows[0.5].payment_pct < 100.0
    assert rows[0.5].ki_breached
    # At or above par the principal is whole.
    assert rows[1.2].payment_pct >= 100.0
    assert not rows[1.0].ki_breached


def test_cpn_scenarios_never_below_protection():
    cpn = CapitalProtectedNote(notional=100.0, maturity=1.0, protection=1.0, participation=1.0)
    rows = terminal_scenarios(cpn, LEVELS)
    # 100% protected ⇒ maturity payment is never below par, and rises with the upside.
    assert all(r.payment_pct >= 100.0 - 1e-9 for r in rows)
    assert rows[-1].payment_pct > rows[0].payment_pct


def test_factsheet_renders_terms_and_disclosures():
    ts = TermSheet(
        product_type="barrier_reverse_convertible",
        underlyings=("NIFTY",),
        notional=100.0,
        observation_times=(0.5, 1.0),
        params={"coupon_rate": 0.04, "knock_in": 0.7, "strike": 1.0},
    )
    md = render_factsheet(ts, summary=PricingSummary(pv=99.1, std_error=0.05))
    assert "Indicative Factsheet" in md
    assert "Risk disclosures" in md
    assert "Capital is at risk" in md
    assert "99.1" in md
