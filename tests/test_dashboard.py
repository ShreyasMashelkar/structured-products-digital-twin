"""Desk dataset that powers the dashboard: structure, signs, and persistence (L14)."""

import json

import pytest

from spdt.dashboard.desk_data import DeskData, build_desk_data


@pytest.fixture(scope="module")
def desk():
    return build_desk_data(n_notes=4, seed=1, n_paths=4000)


def test_payload_has_the_desk_sections(desk):
    p = desk.payload
    for key in ("as_of", "spot", "nav", "day_pnl", "net_greeks", "total_reserve",
                "positions", "pnl_explain", "stress", "reserves", "vega_ladder", "surface"):
        assert key in p
    assert len(p["positions"]) == 7  # 4 generated notes + a 3-basket worst-of sub-book
    assert sum(pos["product_type"] == "worst_of" for pos in p["positions"]) == 3
    assert len(p["correlation_risk"]["baskets"]) == 3
    assert p["arb_clean"] is True


def test_book_is_short_vol_and_reserves_positive(desk):
    p = desk.payload
    assert p["net_greeks"]["vega"] < 0.0  # a book of autocallables is short vol
    assert p["total_reserve"] > 0.0


def test_equity_crash_is_the_worst_scenario(desk):
    by_name = {s["scenario"]: s["pnl"] for s in desk.payload["stress"]}
    assert by_name["equity_crash"] < 0.0
    assert by_name["equity_crash"] == min(by_name.values())  # crash hurts most


def test_pnl_explain_identity_holds(desk):
    e = desk.payload["pnl_explain"]
    terms = e["delta_pnl"] + e["gamma_pnl"] + e["theta_pnl"] + e["vega_pnl"] + \
        e["volga_pnl"] + e["vanna_pnl"] + e["rho_pnl"]
    assert terms + e["residual"] == pytest.approx(e["total"], abs=1e-9)


def test_surface_grid_is_rectangular(desk):
    s = desk.payload["surface"]
    assert all(len(row) == len(s["log_moneyness"]) for row in s["iv"])
    assert len(s["iv"]) == len(s["tenors"])


def test_save_load_round_trip(desk, tmp_path):
    path = desk.save(tmp_path / "desk.json")
    assert json.loads(path.read_text())["nav"] == desk.payload["nav"]
    assert DeskData.load(path).payload == desk.payload
