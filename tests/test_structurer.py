"""Price-to-par solving and the objective → structure proposer (L6)."""

import pytest

from spdt.pricing import BlackScholes, price_mc
from spdt.products import Autocallable
from spdt.structurer import (
    ClientBrief,
    ClientObjective,
    SolveFor,
    par_target,
    propose_autocallable,
    recommend,
    solve_to_par,
)

MODEL = BlackScholes(spot=100.0, r=0.03, q=0.0, sigma=0.25)
OBS = (0.25, 0.5, 0.75, 1.0)


def _note(coupon_rate: float, knock_in: float = 0.6) -> Autocallable:
    return Autocallable(
        notional=100.0,
        observation_times=OBS,
        coupon_rate=coupon_rate,
        autocall_level=1.0,
        coupon_barrier=0.7,
        knock_in=knock_in,
    )


def _pv_for_coupon(coupon: float) -> float:
    return price_mc(_note(coupon), MODEL, n_paths=50_000, seed=3).price


def _pv_for_ki(ki: float) -> float:
    return price_mc(_note(0.02, knock_in=ki), MODEL, n_paths=50_000, seed=3).price


def test_solve_coupon_to_par():
    result = solve_to_par(_pv_for_coupon, target=par_target(100.0), bracket=(0.0, 0.2))
    assert result.achieved_pv == pytest.approx(100.0, abs=1e-4)
    assert 0.0 < result.param < 0.2


def test_solve_knock_in_to_target():
    # PV is monotone decreasing in the knock-in; pick a target it can reach.
    target = 0.5 * (_pv_for_ki(0.4) + _pv_for_ki(0.9))
    result = solve_to_par(_pv_for_ki, target=target, bracket=(0.4, 0.9))
    assert result.achieved_pv == pytest.approx(target, abs=1e-4)


def test_unreachable_target_is_rejected():
    with pytest.raises(ValueError, match="not bracketed"):
        solve_to_par(_pv_for_coupon, target=1_000.0, bracket=(0.0, 0.2))


def test_proposer_maps_brief_to_phoenix():
    ts = propose_autocallable(ClientBrief(target_coupon=0.08, max_downside=0.30))
    assert ts.product_type == "autocallable"
    assert ts.params["knock_in"] == pytest.approx(0.70)  # 30% down ⇒ KI at 70%
    assert ts.params["memory"] is True  # Phoenix
    assert len(ts.observation_times) == 4
    assert ts.params["coupon_rate"] == pytest.approx(0.02)  # 8% annual / 4 obs
    # The proposed structure is priceable end to end.
    assert price_mc(Autocallable.from_termsheet(ts), MODEL, n_paths=20_000, seed=6).price > 0.0


def test_recommender_matches_objective_to_product():
    # Each client objective should surface the product family a desk would actually pitch.
    income = recommend(ClientBrief(0.10, 0.30, objective=ClientObjective.INCOME))
    assert income[0].proposal.product_type == "autocallable"
    protection = recommend(ClientBrief(0.05, 0.10, objective=ClientObjective.PROTECTION))
    assert protection[0].proposal.product_type == "capital_protected"
    assert protection[0].proposal.solve_for == SolveFor.PARTICIPATION
    yield_basket = recommend(
        ClientBrief(0.14, 0.35, objective=ClientObjective.YIELD_ENHANCED, prefer_basket=True)
    )
    assert yield_basket[0].proposal.product_type == "worst_of"


def test_recommender_covers_all_families_with_rationale():
    ranked = recommend(ClientBrief(0.12, 0.30))
    kinds = {r.proposal.product_type for r in ranked}
    assert kinds == {"autocallable", "brc", "worst_of", "capital_protected"}
    # Ranked best-first, every candidate carries a non-empty rationale and a 0–1 fit score.
    scores = [r.fit_score for r in ranked]
    assert scores == sorted(scores, reverse=True)
    assert all(r.rationale and 0.0 <= r.fit_score <= 1.0 for r in ranked)


# --- knock-in solve and configurable autocall (the terms a desk negotiates) -----------------


def test_brief_can_solve_the_barrier_instead_of_the_coupon():
    """The question income clients actually ask: 'I want 15% — how much downside is that?'"""
    from spdt.structurer.objectives import SolveFor
    from spdt.structurer.proposer import ClientBrief, _autocallable_proposal

    brief = ClientBrief(0.15, 0.30, 1.0, 4, solve_for=SolveFor.KNOCK_IN)
    prop = _autocallable_proposal(brief)
    assert prop.solve_for == SolveFor.KNOCK_IN
    assert prop.free_param_key == "knock_in"
    lo, hi = prop.bracket
    assert 0.0 < lo < hi <= 1.0  # a barrier bracket, not a coupon one


def test_coupon_remains_the_default_solve():
    from spdt.structurer.objectives import SolveFor
    from spdt.structurer.proposer import ClientBrief, _autocallable_proposal

    prop = _autocallable_proposal(ClientBrief(0.12, 0.30, 1.0, 4))
    assert prop.solve_for == SolveFor.COUPON
    assert prop.free_param_key == "coupon_rate"


def test_autocall_level_is_a_negotiable_term_not_a_constant():
    """It was hardcoded at 1.0; a step-down autocall is a real concession a desk offers."""
    from spdt.structurer.proposer import ClientBrief, _autocallable_proposal, _worst_of_proposal

    brief = ClientBrief(0.12, 0.30, 1.0, 4, autocall_level=0.95)
    assert _autocallable_proposal(brief).params["autocall_level"] == 0.95
    assert _worst_of_proposal(brief).params["autocall_level"] == 0.95
    # and the default is unchanged for every existing caller
    assert _autocallable_proposal(ClientBrief(0.12, 0.30)).params["autocall_level"] == 1.0
