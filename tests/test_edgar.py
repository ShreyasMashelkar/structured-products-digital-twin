"""EDGAR pricing-supplement parsing (network-free).

Fixtures reproduce the three house styles actually in use, because the parser's history is a
history of silently dropping a whole issuer's shelf when only one style was handled.
"""

from datetime import date

import pytest

from spdt.data.ingest.edgar import NoteFiling, _to_text, parse_filing

BOFA = (
    "Autocallable Contingent Coupon (with Memory) Notes Linked to a Basket of Three Stocks "
    "$10 principal amount per unit CUSIP No. 13608T402 "
    "Pricing Date* Settlement Date* Maturity Date* April 11, 2025 April 21, 2025 April 19, 2028 "
    "Call Feature: Autocallable Notes Coupon Feature: Contingent Coupon Payments (with Memory) "
    "Applicable Coupon Barrier: 80.00 (80% of the Starting Value) "
    "Threshold Value: 80.00 (80% of the Starting Value) "
    "Call Value: 100.00 (100% of the Starting Value) "
    "The Contingent Coupon Payment (with Memory) applicable to a single Coupon Payment Date "
    "is $0.285 per unit on each quarterly Coupon Observation Date. "
    "The initial estimated value of the notes as of the pricing date is $9.583 per unit."
)

GOLDMAN = (
    "Autocallable Contingent Coupon (with Memory) Barrier Notes $10 principal amount per unit "
    "Pricing Date Settlement Date Maturity Date August 11, 2025 August 14, 2025 August 18, 2026 "
    "Coupon Barrier: 60.00, which is 60% of the Starting Value "
    "Threshold Value: 60.00, which is 60% of the Starting Value "
    "Call Value: 100.00, which is 100% of the Starting Value "
    "The Contingent Coupon Payment (with Memory) is $0.439 per unit "
    "on each quarterly Coupon Observation Date. "
    "The initial estimated value of the notes as of the pricing date is $9.76 per unit."
)

GOLDMAN_PROSE = (  # levels only in the summary prose, never as labelled table rows
    "Autocallable Contingent Coupon (with Memory) Notes $10 principal amount per unit "
    "Pricing Date Settlement Date Maturity Date August 11, 2025 August 14, 2025 August 18, 2026 "
    "A Contingent Coupon Payment payable if the Observation Value on the applicable quarterly "
    "Coupon Observation Date is greater than or equal to 60% of the Starting Value. "
    "If not called, at maturity, if the value of the Market Measure has decreased by more than "
    "40%, 1-to-1 downside exposure to decreases in the Market Measure. "
    "Automatically callable if the Observation Value on any quarterly Call Observation Date is "
    "at or above the Starting Value. "
    "The Contingent Coupon Payment (with Memory) is $0.51 per unit. "
    "The initial estimated value of the notes as of the pricing date is $9.74 per unit."
)

PRELIMINARY = (
    "Autocallable Contingent Coupon Notes $10 principal amount per unit "
    "Pricing Date* Settlement Date* Maturity Date* July , 2025 August , 2025 August , 2027 "
    "Applicable Coupon Barrier: 80.00 (80% of the Starting Value) "
    "Threshold Value: 80.00 (80% of the Starting Value) "
    "Call Value: 100.00 (100% of the Starting Value) "
    "The Contingent Coupon Payment applicable to a single Coupon Payment Date is $0.225 per unit "
    "on each quarterly Coupon Observation Date. "
    "The initial estimated value of your notes at the time the terms are set on the pricing date "
    "is expected to be between $9.20 and $9.50 per unit."
)


def test_bofa_style_levels_in_parentheses():
    f = parse_filing(BOFA, issuer="BofA Finance LLC")
    assert f.is_final and f.is_benchmarkable
    assert (f.coupon_barrier, f.knock_in, f.call_level) == (0.8, 0.8, 1.0)
    assert f.estimated_value == pytest.approx(9.583)
    assert f.coupon_per_period == pytest.approx(0.285)
    assert f.periods_per_year == 4
    assert f.memory
    assert f.cusip == "13608T402"
    assert f.pricing_date == date(2025, 4, 11)
    assert f.maturity_date == date(2028, 4, 19)


def test_goldman_style_levels_after_which_is():
    """An earlier parser matched only the parenthesised form and dropped this whole shelf."""
    f = parse_filing(GOLDMAN, issuer="GS Finance Corp.")
    assert f.is_benchmarkable
    assert (f.coupon_barrier, f.knock_in, f.call_level) == (0.6, 0.6, 1.0)
    assert f.estimated_value == pytest.approx(9.76)


def test_levels_stated_only_in_prose_are_still_recovered():
    """Single-stock notes state a permitted *fall*, not a level: 'decreased by more than 40%'."""
    f = parse_filing(GOLDMAN_PROSE, issuer="GS Finance Corp.")
    assert f.coupon_barrier == pytest.approx(0.6)
    assert f.knock_in == pytest.approx(0.6)  # 1 − 40%
    assert f.call_level == pytest.approx(1.0)  # "at or above the Starting Value"
    assert f.is_benchmarkable


def test_preliminary_filings_are_refused_as_benchmarks():
    """A range is not a number and blank dates are not terms; averaging them invents data."""
    f = parse_filing(PRELIMINARY, issuer="BofA Finance LLC")
    assert not f.is_final
    assert not f.is_benchmarkable


def test_estimated_value_converts_to_percent_of_par_and_a_load():
    f = parse_filing(BOFA)
    assert f.estimated_value_pct == pytest.approx(95.83)
    assert f.disclosed_load_pct == pytest.approx(4.17, abs=1e-9)


def test_missing_fields_stay_none_rather_than_defaulting():
    """A silently defaulted barrier would corrupt the benchmark while looking healthy."""
    f = parse_filing("Autocallable Contingent Coupon Notes with no terms at all.")
    assert f.coupon_barrier is None and f.knock_in is None and f.call_level is None
    assert f.estimated_value is None
    assert not f.is_benchmarkable


def test_observation_schedule_matches_tenor_and_frequency():
    f = parse_filing(BOFA)
    obs = f.observation_times()
    assert len(obs) == 12  # 3.02y quarterly
    assert obs[0] == pytest.approx(0.25)
    assert obs[-1] == pytest.approx(3.0)


def test_term_sheet_and_product_carry_the_filed_terms():
    f = parse_filing(BOFA, issuer="BofA Finance LLC")
    ts = f.to_term_sheet()
    assert ts.product_type == "Autocallable"
    assert ts.params["coupon_barrier"] == 0.8
    assert ts.params["estimated_value_pct"] == pytest.approx(95.83)

    note = f.to_autocallable(initial_fixing=100.0)
    assert note.coupon_rate == pytest.approx(0.0285)  # $0.285 on a $10 unit
    assert note.knock_in == 0.8 and note.autocall_level == 1.0
    assert note.memory


def test_hex_entities_are_decoded():
    """The Goldman shelf emits hex entities exclusively; leaving them in splits the key phrases."""
    text = _to_text("<p>Coupon&#x00a0;Barrier: 60.00, which is 60% of the Starting Value</p>")
    assert "&#x" not in text
    assert parse_filing(text).coupon_barrier == pytest.approx(0.6)


def test_issuers_and_exchanges_are_not_mistaken_for_underlyings():
    text = BOFA + ' Bank of America Corporation ("BAC") and the NYSE ("NYSE") and ("FINRA") ("PWR")'
    assert parse_filing(text).underlyings == ("PWR",)


def test_load_is_none_when_no_estimated_value_was_disclosed():
    assert NoteFiling(issuer="x", url="", filed=date.today(), is_final=False).disclosed_load_pct is None


# --- worst-of ------------------------------------------------------------------------------

WORST_OF = (
    "Autocallable Contingent Coupon (with Memory) Barrier Notes Linked to the Worst-Performing "
    "of the Class A Common Stock of Meta Platforms, Inc., the Common Stock of Apple Inc. and "
    "the Common Stock of Tesla, Inc. $10 principal amount per unit "
    "Pricing Date Settlement Date Maturity Date August 12, 2026 August 19, 2026 August 21, 2028 "
    "Contingent Coupon Payments payable if the Observation Value of the Worst-Performing Market "
    "Measure on the applicable quarterly Coupon Observation Date is greater than or equal to "
    "its Coupon Barrier. "
    "With respect to each Underlying Stock: "
    "Coupon Barrier: META: $347.31 (60.00% of its Starting Value). "
    "AAPL: $181.35 (60.00% of its Starting Value). "
    "TSLA: $196.51 (60.00% of its Starting Value). "
    "Threshold Value: META: $347.31 (60.00% of its Starting Value). "
    "AAPL: $181.35 (60.00% of its Starting Value). "
    "TSLA: $196.51 (60.00% of its Starting Value). "
    "Call Value: META: $578.85 (100.00% of its Starting Value). "
    "AAPL: $302.25 (100.00% of its Starting Value). "
    "TSLA: $327.51 (100.00% of its Starting Value). "
    "The Contingent Coupon Payment (with Memory) is $0.4875 per unit. "
    "The initial estimated value of the notes as of the pricing date is $9.62 per unit."
)


def test_worst_of_is_detected_and_its_constituents_recovered():
    """Worst-of is ~two thirds of the US shelf; missing it excludes most of the market."""
    f = parse_filing(WORST_OF, issuer="BofA Finance LLC")
    assert f.is_worst_of
    assert f.underlyings == ("META", "AAPL", "TSLA")
    assert f.is_benchmarkable


def test_per_name_levels_are_read_from_the_right_table():
    """An unbounded window reads on into the next label and returns its percentages."""
    f = parse_filing(WORST_OF)
    assert f.coupon_barrier == pytest.approx(0.60)
    assert f.knock_in == pytest.approx(0.60)
    assert f.call_level == pytest.approx(1.00)  # not 0.60, and not read off the barrier table


def test_starting_values_are_recovered_as_per_name_strikes():
    f = parse_filing(WORST_OF)
    starts = dict(f.starting_values)
    assert starts["META"] == pytest.approx(578.85)
    assert starts["AAPL"] == pytest.approx(302.25)
    assert starts["TSLA"] == pytest.approx(327.51)
    # The 60% barrier divided back out must reproduce the same strike.
    assert 347.31 / 0.60 == pytest.approx(starts["META"], rel=1e-3)


def test_differing_per_name_barriers_are_not_collapsed_to_the_first():
    """Equal percentages are a convention, not a rule; disagreement must not be silently hidden."""
    from spdt.data.ingest.edgar import _common_fraction

    assert _common_fraction({"A": (60.0, 0.6), "B": (50.0, 0.6)}) == pytest.approx(0.6)
    assert _common_fraction({"A": (60.0, 0.6), "B": (50.0, 0.5)}) is None
    assert _common_fraction({}) is None


def test_single_underlying_filings_are_not_flagged_worst_of():
    assert not parse_filing(BOFA).is_worst_of
    assert parse_filing(BOFA).starting_values == ()


def test_buffer_notes_are_parsed_and_priced_as_buffers():
    """'with a 10% Buffer' caps the loss at (decline − 10%). Ignoring it undervalues the note
    by the buffer's put-spread — which is exactly how it surfaced: buffered notes sat
    'unreachable, model too LOW at every correlation' in the benchmark."""
    buffered = WORST_OF.replace(
        "Autocallable Contingent Coupon (with Memory) Barrier Notes Linked",
        "Autocallable Contingent Coupon (with Memory) Barrier Notes with a 10% Buffer Linked",
    )
    f = parse_filing(buffered, issuer="BofA Finance LLC")
    assert f.buffer == pytest.approx(0.10)
    assert parse_filing(WORST_OF).buffer == 0.0  # unbuffered filings stay unbuffered

    note = f.to_autocallable(initial_fixing=100.0)
    assert note.buffer == pytest.approx(0.10)


def test_buffer_softens_the_downside_without_touching_the_upside():
    import numpy as np

    from spdt.pricing.engine import price_mc
    from spdt.pricing.models.bs import BlackScholes
    from spdt.products.catalog import Autocallable

    kwargs = dict(
        notional=100.0, observation_times=(0.5, 1.0), coupon_rate=0.02,
        autocall_level=1.5, coupon_barrier=0.95, knock_in=0.90, memory=True,
        initial_fixing=100.0,
    )
    model = BlackScholes(spot=100.0, r=0.04, q=0.0, sigma=0.35)
    plain = price_mc(Autocallable(**kwargs), model, n_paths=60_000, seed=1).price
    buffered = price_mc(Autocallable(**kwargs, buffer=0.10), model, n_paths=60_000, seed=1).price
    assert buffered > plain  # the buffer is worth something …
    # … and its value is bounded by the buffer itself on the knocked-in mass.
    assert buffered - plain < 10.0

    # Deterministic check of the payoff at maturity: at S_T = 70 with a 10% buffer the
    # investor loses 20, not 30.
    from spdt.products.graph import PathSet

    note = Autocallable(**kwargs, buffer=0.10)
    paths = PathSet(times=np.array([0.0, 0.5, 1.0]),
                    spots=np.array([[100.0, 80.0, 70.0]]))
    total = sum(float(cf.amount[0]) for cf in note.cashflows(paths))
    assert total == pytest.approx(80.0)
