"""Validation harness (network-free).

The legs that touch the NSE archive are exercised in the report run, not here; these tests
pin the logic that must hold regardless of which market is loaded.
"""

from datetime import date

import numpy as np
import pytest

from spdt.core.types import SourceTag
from spdt.data import build_snapshot
from spdt.data.curate import invert_chain
from spdt.data.curate.bs_inversion import bs_price
from spdt.data.ingest import RawMarketData, RawOptionQuote
from spdt.pricing.models.bs import BlackScholes
from spdt.products.catalog import Autocallable
from spdt.validation.greeks_crosscheck import (
    MethodAgreement,
    bump_convergence,
    cross_check_autocallable,
    cross_check_vanilla,
)
from spdt.validation.sensitivity import coupon_sensitivity

MODEL = BlackScholes(spot=22_000.0, r=0.065, q=0.013, sigma=0.16)
OBS = tuple(round(0.25 * i, 4) for i in range(1, 5))  # 1y quarterly


def _note(coupon: float = 0.02) -> Autocallable:
    return Autocallable(
        notional=100.0, observation_times=OBS, coupon_rate=coupon,
        autocall_level=1.0, coupon_barrier=0.8, knock_in=0.6, memory=True,
        initial_fixing=MODEL.spot,
    )


# --- Greeks cross-check -----------------------------------------------------------------


def test_vanilla_greeks_agree_across_every_method():
    """A known answer exists here, so disagreement means a bug — not a modelling subtlety."""
    comparison = cross_check_vanilla(MODEL, 22_000.0, 1.0, n_paths=200_000, seed=0)
    assert comparison.has_closed_form
    for agreement in comparison.agreements:
        assert agreement.agrees(rel_tol=0.05), (
            f"{agreement.method_b} {agreement.greek} = {agreement.value_b}, "
            f"closed form = {agreement.value_a}"
        )


def test_analytic_aad_matches_closed_form_almost_exactly():
    """The adjoint of the analytic formula has no MC error, so its tolerance is tight."""
    comparison = cross_check_vanilla(MODEL, 22_000.0, 1.0, n_paths=20_000, seed=0)
    exact = [a for a in comparison.agreements if a.method_b == "aad_analytic"]
    assert exact, "no analytic-AAD comparison produced"
    for agreement in exact:
        assert agreement.rel_diff < 1e-6


def test_autocallable_aad_and_bump_are_compared_not_asserted_equal():
    """No closed form exists; the useful output is the size of the gap, and it must be finite."""
    comparison = cross_check_autocallable(_note(), MODEL, n_paths=100_000, seed=0)
    assert not comparison.has_closed_form
    assert {a.greek for a in comparison.agreements} == {"delta", "vega"}
    for agreement in comparison.agreements:
        assert np.isfinite(agreement.value_a) and np.isfinite(agreement.value_b)


def test_unstruck_note_is_refused_rather_than_silently_zero():
    """An unstruck note is scale-invariant, so its delta is structurally 0 — a vacuous check."""
    unstruck = Autocallable(
        notional=100.0, observation_times=OBS, coupon_rate=0.02, initial_fixing=None
    )
    with pytest.raises(ValueError, match="struck"):
        cross_check_autocallable(unstruck, MODEL)


def test_bump_convergence_reports_every_requested_step():
    steps = (2e-2, 1e-2, 5e-3)
    curve = bump_convergence(_note(), MODEL, bumps=steps, n_paths=50_000, seed=0)
    assert set(curve) == set(steps)
    assert all(np.isfinite(v) for v in curve.values())


def test_agreement_handles_both_values_near_zero():
    """rel_diff is undefined at zero; agrees() must fall back to the absolute test."""
    tiny = MethodAgreement("delta", "a", 0.0, "b", 1e-15)
    assert tiny.agrees(rel_tol=1e-6, abs_tol=1e-9)
    assert np.isnan(tiny.rel_diff)


# --- Coupon sensitivity -----------------------------------------------------------------


def test_coupon_sensitivity_ranks_inputs_by_impact():
    table = coupon_sensitivity(_note(), MODEL, n_paths=20_000, seed=0)
    assert 0.0 < table.base_coupon < 0.20
    assert {p.input_name for p in table.perturbations} == {"vol", "rate", "dividend"}

    ranked = table.ranked
    assert [p.half_range_bps for p in ranked] == sorted(
        [p.half_range_bps for p in ranked], reverse=True
    )
    assert table.dominant_input == ranked[0].input_name
    assert table.total_uncertainty_bps > 0.0


def test_higher_vol_raises_the_coupon_a_note_can_pay():
    """Selling more vol funds more coupon; a violation means the solve is unstable."""
    table = coupon_sensitivity(_note(), MODEL, n_paths=20_000, seed=0)
    vol = next(p for p in table.perturbations if p.input_name == "vol")
    assert vol.coupon_up > vol.coupon_down


def test_uncertainty_is_added_in_quadrature_not_summed():
    table = coupon_sensitivity(_note(), MODEL, n_paths=20_000, seed=0)
    arithmetic = sum(p.half_range_bps for p in table.perturbations)
    assert table.total_uncertainty_bps <= arithmetic + 1e-9


# --- Liquidity filtering ----------------------------------------------------------------


def _chain_with_dead_long_end() -> RawMarketData:
    """A liquid front expiry and a long-dated one that never traded — the real NIFTY shape."""
    as_of = date(2020, 3, 23)
    near, far = date(2020, 4, 30), date(2023, 6, 29)
    spot, r, q = 7578.0, 0.065, 0.013
    quotes = []
    for expiry, traded, oi, vol in ((near, 5000.0, 100_000.0, 0.55), (far, 0.0, 0.0, 0.80)):
        tau = (expiry - as_of).days / 365.0
        fwd = spot * np.exp((r - q) * tau)
        disc = float(np.exp(-r * tau))
        for strike in (6000.0, 6500.0, 7000.0, 7500.0, 8000.0, 8500.0, 9000.0):
            is_call = strike >= fwd
            quotes.append(
                RawOptionQuote(
                    expiry=expiry, strike=strike, is_call=is_call,
                    settlement_price=bs_price(fwd, strike, tau, vol, disc, is_call),
                    contracts_traded=traded, open_interest=oi,
                )
            )
    return RawMarketData(
        date=as_of, underlying="NIFTY", spot=spot, option_chain=tuple(quotes),
        ois_zero_rates={near: r, far: r}, funding_spread_knots={near: 0.012, far: 0.012},
        dividend_yield=q, source=SourceTag.OBSERVED,
    )


def test_untraded_contracts_are_excluded_from_the_surface():
    """A settlement mark on a zero-volume contract is not a market price."""
    raw = _chain_with_dead_long_end()
    curve = build_snapshot(raw).ois_curve

    unfiltered = invert_chain(raw, curve)
    filtered = invert_chain(raw, curve, min_contracts=1.0, min_open_interest=1.0)

    assert {p.expiry for p in unfiltered} == {date(2020, 4, 30), date(2023, 6, 29)}
    assert {p.expiry for p in filtered} == {date(2020, 4, 30)}, (
        "the untraded 2023 expiry must not reach calibration"
    )


def test_slices_with_too_few_quotes_are_skipped_not_fitted():
    """Four points cannot identify five SVI parameters; fitting them anyway invents a smile."""
    from spdt.vol.surface import VolSurface

    raw = _chain_with_dead_long_end()
    curve = build_snapshot(raw).ois_curve
    points = invert_chain(raw, curve, min_contracts=1.0)
    surface = VolSurface.calibrate(points, "NIFTY", min_points_per_slice=5)
    assert date(2023, 6, 29) not in surface.slices

    starved = VolSurface.calibrate(points, "NIFTY", min_points_per_slice=99)
    assert not starved.slices  # every expiry dropped, and no exception raised
