"""Price-to-par solving and the objective → structure proposer (L6)."""

import pytest

from spdt.pricing import BlackScholes, price_mc
from spdt.products import Autocallable
from spdt.structurer import ClientBrief, par_target, propose_autocallable, solve_to_par

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
