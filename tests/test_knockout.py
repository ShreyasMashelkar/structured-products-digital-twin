"""Knock-out barriers: the autocall as a barrier, and the shark-fin CPN.

Both close the same gap. The codebase had full knock-out machinery — the primitive, the
component type, the hit-probability engine, the pre-unwind scheduler written specifically for
knock-outs — and not one product that emitted a knock-out component for any of it to act on.
"""

import dataclasses

import numpy as np
import pytest

from spdt.decomposition import decompose
from spdt.pricing.engine import price_mc
from spdt.pricing.models.bs import BlackScholes
from spdt.products.catalog import Autocallable, CapitalProtectedNote
from spdt.products.graph import PathSet

OBS = (0.25, 0.5, 0.75, 1.0)
MODEL = BlackScholes(spot=100.0, r=0.065, q=0.013, sigma=0.20)


def _cpn(**kw) -> CapitalProtectedNote:
    base = dict(notional=100.0, maturity=1.0, protection=1.0, participation=1.0,
                strike=1.0, initial_fixing=100.0)
    return CapitalProtectedNote(**{**base, **kw})


# --- the autocall, finally visible to the risk layer ----------------------------------------


def test_autocall_is_emitted_as_an_up_and_out_barrier():
    note = Autocallable(100.0, OBS, 0.02, 1.0, 0.8, 0.6, True, initial_fixing=100.0)
    kinds = [c.component_type for c in decompose(note).components]
    assert "barrier_knock_out_call" in kinds
    assert "barrier_knock_in_put" in kinds  # and the knock-in is still there


def test_the_autocall_barrier_reaches_the_barrier_book():
    """The point of the change: pre_unwind and the hit-probability heatmap had no knock-out
    product to act on, so the machinery was exercised only in isolation."""
    from spdt.book.book import Trade
    from spdt.semistatic.book import BarrierBookManager

    note = Autocallable(100.0, OBS, 0.02, 1.0, 0.8, 0.6, True, initial_fixing=100.0)
    mgr = BarrierBookManager([Trade(trade_id="T1", product=note, underlying="NIFTY", direction=-1)])
    seen = {c.component_type: c for _, c in mgr._barrier_components}
    assert set(seen) == {"barrier_knock_in_put", "barrier_knock_out_call"}
    assert seen["barrier_knock_out_call"].barrier == pytest.approx(1.0)
    assert seen["barrier_knock_out_call"].knock_in is False


def test_a_note_with_no_autocall_dates_emits_no_knock_out():
    """A single-observation note has no early redemption to describe."""
    note = Autocallable(100.0, (1.0,), 0.02, 1.0, 0.8, 0.6, True, initial_fixing=100.0)
    kinds = [c.component_type for c in decompose(note).components]
    assert "barrier_knock_out_call" not in kinds


# --- the shark fin --------------------------------------------------------------------------


def test_knock_out_extinguishes_participation_and_pays_the_rebate():
    """Deterministic payoff check: a path that touches 120% loses ALL upside, unlike a cap
    which would keep the gain up to the cap."""
    note = _cpn(knock_out=1.20, rebate=0.02, ko_monitoring=OBS)
    # Path rises through 125% then ends at 110%: knocked out, so 100 protection + 2 rebate.
    paths = PathSet(times=np.array([0.0, *OBS]),
                    spots=np.array([[100.0, 105.0, 125.0, 115.0, 110.0]]))
    total = sum(float(cf.amount[0]) for cf in note.cashflows(paths))
    assert total == pytest.approx(102.0)


def test_an_untouched_path_keeps_full_participation():
    note = _cpn(knock_out=1.20, rebate=0.02, ko_monitoring=OBS)
    paths = PathSet(times=np.array([0.0, *OBS]),
                    spots=np.array([[100.0, 105.0, 112.0, 115.0, 118.0]]))
    total = sum(float(cf.amount[0]) for cf in note.cashflows(paths))
    assert total == pytest.approx(118.0)  # 100 protection + 18 upside, no rebate


def test_a_knock_out_is_cheaper_than_the_same_level_as_a_cap():
    """The economic claim the product rests on: a cap keeps the gain and stops it growing; a
    knock-out takes the gain away for having been too right, so it costs less — which is what
    buys the client more participation at par."""
    capped = price_mc(_cpn(cap=1.20), MODEL, n_paths=60_000, seed=3).price
    shark = price_mc(_cpn(knock_out=1.20, ko_monitoring=OBS), MODEL, n_paths=60_000, seed=3).price
    uncapped = price_mc(_cpn(), MODEL, n_paths=60_000, seed=3).price
    assert shark < capped < uncapped


def test_giving_up_the_tail_buys_materially_more_participation():
    from spdt.structurer.solver import par_target, solve_to_par

    def solved(note: CapitalProtectedNote) -> float:
        return solve_to_par(
            lambda x: price_mc(dataclasses.replace(note, participation=x), MODEL,
                               n_paths=40_000, seed=3).price,
            par_target(100.0, fee=1.0), (0.0, 6.0),
        ).param

    assert solved(_cpn(knock_out=1.20, rebate=0.02, ko_monitoring=OBS)) > 2 * solved(_cpn())


def test_the_plain_note_is_untouched_by_the_new_fields():
    """Every existing CPN must price exactly as before — knock_out defaults to None."""
    note = _cpn()
    assert note.knock_out is None and note.rebate == 0.0
    assert note.monitoring_times() == (1.0,)
    paths = PathSet(times=np.array([0.0, 1.0]), spots=np.array([[100.0, 130.0]]))
    assert sum(float(cf.amount[0]) for cf in note.cashflows(paths)) == pytest.approx(130.0)


def test_shark_fin_decomposition_declares_itself_inexact():
    """The barrier extinguishes the call beside it, so the components do not sum to the payoff
    and nothing downstream may treat the sum as a price."""
    d = decompose(_cpn(knock_out=1.20, ko_monitoring=OBS))
    assert not d.is_exact
    assert "barrier_knock_out_call" in [c.component_type for c in d.components]
    assert decompose(_cpn(cap=1.20)).is_exact  # the capped note is still exact


# --- the shark fin as a proposable family ---------------------------------------------------


def test_shark_fin_is_only_offered_once_the_client_accepts_the_knock_out():
    """Its upside is conditional, so it must never outrank the plain protected note unless the
    client has actually said they will surrender the tail."""
    from spdt.structurer.proposer import ClientBrief, ClientObjective, recommend

    def top(accept: bool) -> str:
        brief = ClientBrief(0.10, 0.25, 1.0, 4, objective=ClientObjective.PROTECTION,
                            accept_knockout=accept)
        return recommend(brief)[0].proposal.product_type

    assert top(False) == "capital_protected"
    assert top(True) == "shark_fin"


def test_shark_fin_is_not_even_a_candidate_without_consent():
    """Not merely ranked last — absent. Quoting a knock-out to a client who has not accepted one
    misrepresents what they get for being right."""
    from spdt.structurer.proposer import ClientBrief, recommend

    kinds = {r.proposal.product_type for r in recommend(ClientBrief(0.12, 0.30))}
    assert "shark_fin" not in kinds


def test_shark_fin_never_leads_for_an_income_client():
    from spdt.structurer.proposer import ClientBrief, ClientObjective, recommend

    brief = ClientBrief(0.12, 0.30, 1.0, 4, objective=ClientObjective.INCOME,
                        accept_knockout=True)
    assert recommend(brief)[0].proposal.product_type != "shark_fin"


def test_the_knock_out_mirrors_the_downside_the_client_already_stated():
    """A client who will stomach a 25% fall is quoted a 25% ceiling — the concession is
    symmetric with their own stated risk, not a number chosen arbitrarily."""
    from spdt.structurer.proposer import ClientBrief, _shark_fin_proposal

    prop = _shark_fin_proposal(ClientBrief(0.10, 0.25, 1.0, 4, accept_knockout=True))
    assert prop.params["knock_out"] == pytest.approx(1.25)
    assert prop.params["rebate"] > 0.0  # something for having been right
    assert prop.params["ko_monitoring"] == prop.observation_times
    assert prop.free_param_key == "participation"


def test_shark_fin_proposal_prices_and_solves():
    """End-to-end: the proposal the recommender emits must actually be priceable."""
    from spdt.structurer.proposer import ClientBrief, _shark_fin_proposal
    from spdt.structurer.solver import par_target, solve_to_par

    prop = _shark_fin_proposal(ClientBrief(0.10, 0.25, 1.0, 4, accept_knockout=True))
    p = prop.params

    def pv(x: float) -> float:
        note = CapitalProtectedNote(
            100.0, prop.maturity, p["protection"], x, p["strike"], p["cap"],
            initial_fixing=100.0, knock_out=p["knock_out"], rebate=p["rebate"],
            ko_monitoring=tuple(p["ko_monitoring"]),
        )
        return price_mc(note, MODEL, n_paths=30_000, seed=5).price

    solved = solve_to_par(pv, par_target(100.0, fee=1.0), prop.bracket)
    assert 0.0 < solved.param < prop.bracket[1]
