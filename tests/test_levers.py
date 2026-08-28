"""Manufacturing a coupon the market will not hand over.

The engine's job is to turn "we can't do 15%" into "15% costs you this specific term". Its
correctness rests on one thing: every lever must actually move the coupon the way its label
claims. These tests pin that, including the direction error the guard originally caught.
"""

import dataclasses

import pytest

from spdt.structurer.levers import _LEVERS, manufacture, solve_lever
from spdt.structurer.objectives import SolveFor
from spdt.structurer.proposer import Proposal

OBS = 4


def _proposal(**overrides) -> Proposal:
    params = {
        "coupon_rate": 0.02, "autocall_level": 1.0,
        "coupon_barrier": 0.70, "knock_in": 0.70, "memory": True,
    }
    params.update(overrides)
    return Proposal(
        product_type="autocallable", observation_times=(0.25, 0.5, 0.75, 1.0),
        maturity=1.0, params=params, solve_for=SolveFor.COUPON,
        free_param_key="coupon_rate", bracket=(0.0, 0.10),
    )


def _linear_solver(sensitivities: dict[str, float], base: float = 0.0125):
    """A stand-in for the MC solve: coupon rises linearly in each lever above its base.

    Deterministic on purpose — the lever logic is what is under test, not the pricer, and a
    Monte-Carlo solve would make these assertions noisy for no gain.
    """
    def solve(prop: Proposal) -> float:
        c = base
        for key, slope in sensitivities.items():
            c += slope * (prop.params[key] - _proposal().params[key])
        return max(c, 0.0)
    return solve


def test_no_concession_offered_when_the_market_already_pays():
    report = manufacture(_proposal(), _linear_solver({"knock_in": 0.05}), 0.03, OBS)
    assert report.already_met
    assert report.levers == ()
    assert "no concession needed" in report.summary()


def test_a_reachable_target_names_the_term_and_the_value():
    # coupon = 0.0125 + 0.05*(knock_in - 0.70) per period; annualised x4.
    # Target 8% p.a. = 0.02/period needs knock_in = 0.85.
    report = manufacture(_proposal(), _linear_solver({"knock_in": 0.05}), 0.08, OBS)
    assert not report.already_met
    assert report.shortfall == pytest.approx(0.03, abs=1e-6)
    lever = report.reachable_levers[0]
    assert lever.key == "knock_in"
    assert lever.required == pytest.approx(0.85, abs=1e-3)
    assert lever.move == pytest.approx(0.15, abs=1e-3)


def test_a_target_beyond_every_bound_is_reported_not_faked():
    report = manufacture(_proposal(), _linear_solver({"knock_in": 0.05}), 0.50, OBS)
    assert report.reachable_levers == ()
    assert "not reachable by moving any single term" in report.summary()
    assert all(v.required is None for v in report.levers)


def test_a_lever_wired_backwards_is_refused_rather_than_root_solved():
    """The formative bug: the first lever table pointed every direction the wrong way, on the
    intuition that a *deeper* barrier sells more risk. It does not — a knock-in further from
    spot is safer, so it lowers the coupon. Brent on a backwards lever would have returned a
    confident number selling the client the opposite of the label."""
    backwards = _linear_solver({"knock_in": -0.05})  # coupon FALLS as the lever rises
    lever = solve_lever(_proposal(), backwards, "knock_in", 0.08, OBS)
    assert not lever.reachable
    assert lever.required is None


def test_a_lever_that_does_nothing_is_also_refused():
    flat = _linear_solver({})  # coupon independent of every lever
    lever = solve_lever(_proposal(), flat, "knock_in", 0.08, OBS)
    assert not lever.reachable


def test_every_configured_lever_raises_the_coupon_as_its_bound_is_approached():
    """The table's claim, asserted directly: each lever's bound must sit on the richer side."""
    base = _proposal()
    for key, cfg in _LEVERS.items():
        assert cfg["bound"] > base.params[key], f"{key} bound must move the coupon up"


def test_unsolvable_structure_reports_nothing_rather_than_zero():
    report = manufacture(_proposal(), lambda prop: None, 0.10, OBS)
    assert report.natural_coupon is None
    assert report.shortfall is None
    assert "could not be solved" in report.summary()


def test_levers_absent_from_the_product_are_skipped():
    """A capital-protected note has no knock-in; asking for one must not raise."""
    cpn = dataclasses.replace(
        _proposal(), params={"protection": 0.95, "participation": 1.0, "coupon_rate": 0.01}
    )
    report = manufacture(cpn, _linear_solver({}), 0.10, OBS)
    assert all(v.key in cpn.params for v in report.levers)


def test_cheapest_concession_is_listed_first():
    """Two reachable levers: the one asking for the smaller relative move leads the table."""
    solver = _linear_solver({"knock_in": 0.05, "coupon_barrier": 0.02})
    report = manufacture(_proposal(), solver, 0.06, OBS)
    reachable = report.reachable_levers
    assert len(reachable) >= 2
    frac = [abs(v.move) / abs(v.limit - v.current) for v in reachable]
    assert frac == sorted(frac)
