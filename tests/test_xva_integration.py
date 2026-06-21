"""Milestone M1 — the curve join (ADR-0007, Phase 2).

Proof that the two codebases share one curve: a single bootstrapped SPDT ``Curve`` is adapted to
XVA's ``OISCurve`` interface, its discount factors match the source to 1e-8, and it drives XVA's
``CVAEngine`` end-to-end with sane economics (CVA ≥ 0, → 0 as the counterparty spread → 0, and
monotone in spread). If this passes, SPDT's curve provably feeds the XVA stack.
"""

from datetime import date, timedelta
from math import exp

import numpy as np
import pytest

import integration  # noqa: F401 — import side-effect: puts xva/ on sys.path
from integration import (
    ExposurePackage,
    SpdtCurveAsOIS,
    autocallable_exposure,
    european_exposure,
    mark_to_future_european,
    note_exposure,
    solve_coupon_all_in,
    worst_of_exposure,
    xva_charge,
)
from spdt.core.types import Curve, year_fraction
from spdt.pricing import BlackScholes, bs_vanilla, price_mc
from spdt.pricing.engine import price_worst_of
from spdt.pricing.mc.rng import standard_normals
from spdt.products import EuropeanOption
from spdt.products.catalog import Autocallable, BarrierReverseConvertible, WorstOfAutocallable
from src.montecarlo.equity_mc import EquityGBM  # type: ignore  # resolved via integration
from src.xva.cva import CVAEngine, CreditCurve  # type: ignore  # resolved via integration


def _spdt_ois_curve(flat_rate: float = 0.06) -> Curve:
    anchor = date(2026, 1, 1)
    taus = [0.5, 1.0, 2.0, 3.0, 5.0]
    pillars = tuple(anchor + timedelta(days=round(365 * t)) for t in taus)
    dfs = {p: exp(-flat_rate * year_fraction(anchor, p)) for p in pillars}
    return Curve(anchor=anchor, pillars=pillars, discount_factors=dfs)


def test_adapter_discount_factors_match_the_source_spdt_curve():
    curve = _spdt_ois_curve()
    ois = SpdtCurveAsOIS(curve)
    for t in (0.25, 0.5, 1.0, 2.5, 4.0, 5.0):
        assert ois.df(t) == pytest.approx(curve.df(t), abs=1e-8)
    # The pillar tenors/rates XVA's IR01 path reads off are exposed and consistent.
    assert ois.tenors.shape == (5,)
    assert ois.rates == pytest.approx(0.06, abs=1e-6)


def test_spdt_curve_drives_xva_cva_engine():
    ois = SpdtCurveAsOIS(_spdt_ois_curve())
    engine = CVAEngine(ois)  # XVA engine consuming a SPDT-sourced curve
    time_grid = np.linspace(0.0, 5.0, 21)
    ee = 100.0 * np.exp(-0.3 * time_grid)  # a decaying expected-exposure profile

    cva = engine.compute_cva(ee, time_grid, CreditCurve(cds_spread_bps=200.0, recovery_rate=0.40))
    assert np.isfinite(cva) and cva > 0.0


def test_cva_vanishes_with_credit_spread_and_is_monotone():
    ois = SpdtCurveAsOIS(_spdt_ois_curve())
    engine = CVAEngine(ois)
    time_grid = np.linspace(0.0, 5.0, 21)
    ee = 100.0 * np.exp(-0.3 * time_grid)

    near_zero = engine.compute_cva(ee, time_grid, CreditCurve(cds_spread_bps=1e-6, recovery_rate=0.40))
    mid = engine.compute_cva(ee, time_grid, CreditCurve(cds_spread_bps=200.0, recovery_rate=0.40))
    wide = engine.compute_cva(ee, time_grid, CreditCurve(cds_spread_bps=600.0, recovery_rate=0.40))
    assert near_zero == pytest.approx(0.0, abs=1e-3)
    assert wide > mid > near_zero  # CVA grows monotonically with counterparty spread


# --- Phase 3: the exposure seam (European, cross-checked vs XVA's own equity MC) -------------

def _european_setup():
    model = BlackScholes(spot=100.0, r=0.05, q=0.01, sigma=0.20)
    option = EuropeanOption(strike=100.0, expiry=1.0, is_call=True)
    ois = SpdtCurveAsOIS(_spdt_ois_curve(0.05))
    time_grid = np.linspace(0.0, 1.0, 13)
    spots = model.simulate(time_grid, standard_normals(4000, 12, seed=7))
    return model, option, ois, time_grid, spots


def test_spdt_mark_to_future_matches_xva_equity_mc_elementwise():
    """SPDT's mark-to-future and XVA's equity-MC option MTM agree path-by-path on identical spots —
    proof the exposure producer is faithful, not just close in aggregate."""
    model, option, ois, time_grid, spots = _european_setup()
    r = ois.zero_rate(option.expiry)
    npv_spdt = mark_to_future_european(
        option, r=r, q=model.q, sigma=model.sigma, spot_paths=spots, time_grid=time_grid
    )
    gbm = EquityGBM(spot=100.0, vol=0.20, div_yield=0.01)
    mtm_xva = gbm.option_mtm_paths(spots, time_grid, ois, strike=100.0, maturity=1.0,
                                   units=1.0, call=True)
    assert np.allclose(npv_spdt, mtm_xva, atol=1e-8)


def test_european_exposure_profile_is_economically_sane():
    """EE(0) = today's premium; EE grows over the life of a (always-positive) long call."""
    model, option, ois, time_grid, spots = _european_setup()
    r = ois.zero_rate(option.expiry)
    npv = mark_to_future_european(option, r=r, q=model.q, sigma=model.sigma,
                                  spot_paths=spots, time_grid=time_grid)
    pkg = ExposurePackage("EUR-0", "CP-0", "ns", time_grid, npv, ois, ois)
    ee = pkg.expected_exposure()
    premium = bs_vanilla(100.0, 100.0, 1.0, r, model.q, model.sigma, is_call=True)
    assert ee[0] == pytest.approx(premium, abs=0.05)  # deterministic value at t=0
    assert ee[-1] > ee[0]  # exposure builds toward maturity
    assert np.all(ee >= 0.0)


def test_spdt_european_exposure_flows_through_to_a_cva():
    """End-to-end seam: a SPDT European → ExposurePackage → EE → XVA CVA, a finite positive cost."""
    model, option, ois, time_grid, _ = _european_setup()
    pkg = european_exposure(option, model, ois, ois, time_grid=time_grid, n_paths=8000, seed=3,
                            counterparty_id="ACME-CORP")
    cva = CVAEngine(pkg.ois_curve).compute_cva(
        pkg.expected_exposure(), pkg.time_grid, CreditCurve(cds_spread_bps=250.0, recovery_rate=0.40)
    )
    assert np.isfinite(cva) and cva > 0.0


# --- Phase 3b: path-dependent exposure — the autocallable (EE collapses on autocall) ---------

def _autocall_setup():
    ois = SpdtCurveAsOIS(_spdt_ois_curve(0.06))
    note = Autocallable(notional=100.0, observation_times=(0.5, 1.0, 1.5, 2.0), coupon_rate=0.04,
                        autocall_level=1.0, coupon_barrier=0.8, knock_in=0.6, memory=True,
                        initial_fixing=None)
    model = BlackScholes(spot=100.0, r=0.06, q=0.0, sigma=0.22)
    profile = np.linspace(0.0, 1.95, 14)
    pkg = autocallable_exposure(note, model, ois, ois, time_grid=profile, n_paths=30_000, seed=1)
    return note, model, pkg


def test_autocallable_value_at_zero_reconciles_with_the_spdt_pricer():
    """The exposure machinery's t=0 mark (regression collapses to the mean when all spots are
    equal) must match SPDT's own MC price of the note — a non-circular cross-check."""
    note, model, pkg = _autocall_setup()
    value_0 = float(pkg.npv_paths[:, 0].mean())
    price = price_mc(note, model, n_paths=60_000, seed=2).price
    assert value_0 == pytest.approx(price, abs=0.8)


def test_autocallable_ee_rises_then_collapses_on_autocall():
    """The defining CCR signature: EE builds within each observation window, then drops sharply
    at each autocall date as redeemed paths leave the book — a structural cliff, not noise."""
    _, _, pkg = _autocall_setup()
    ee = pkg.expected_exposure()
    assert np.all(np.isfinite(ee)) and np.all(ee >= 0.0)
    assert ee.max() > ee[0]                       # exposure builds above the initial mark
    assert ee[-1] < 0.5 * ee.max()                # and collapses as the book autocalls away
    assert ee[-1] > 0.0                            # the never-autocalled tail keeps a residual
    ratios = ee[1:] / np.maximum(ee[:-1], 1e-9)
    assert ratios.min() < 0.7                       # at least one ≥30% cliff (an autocall date)


def test_autocallable_exposure_flows_through_to_a_cva():
    _, _, pkg = _autocall_setup()
    cva = CVAEngine(pkg.ois_curve).compute_cva(
        pkg.expected_exposure(), pkg.time_grid, CreditCurve(cds_spread_bps=300.0, recovery_rate=0.40)
    )
    assert np.isfinite(cva) and cva > 0.0


# --- Phase 3c: the remaining products — BRC (non-callable) and worst-of (multi-asset) --------

def _brc_setup():
    ois = SpdtCurveAsOIS(_spdt_ois_curve(0.06))
    brc = BarrierReverseConvertible(notional=100.0, observation_times=(0.5, 1.0, 1.5, 2.0),
                                    coupon_rate=0.05, strike=1.0, knock_in=0.7, initial_fixing=None)
    model = BlackScholes(spot=100.0, r=0.06, q=0.0, sigma=0.25)
    pkg = note_exposure(brc, model, ois, ois, time_grid=np.linspace(0.0, 1.95, 12),
                        n_paths=20_000, seed=1)
    return brc, model, pkg


def test_brc_value_at_zero_reconciles_with_the_pricer():
    brc, model, pkg = _brc_setup()
    price = price_mc(brc, model, n_paths=60_000, seed=2).price
    assert float(pkg.npv_paths[:, 0].mean()) == pytest.approx(price, abs=0.8)


def test_brc_exposure_stays_elevated_with_no_autocall_cliff():
    """A reverse convertible has no early redemption, so — unlike the autocallable — its EE does
    not collapse: the par redemption keeps exposure high across the whole life."""
    _, _, pkg = _brc_setup()
    ee = pkg.expected_exposure()
    assert np.all(np.isfinite(ee)) and np.all(ee >= 0.0)
    assert ee.min() > 0.5 * ee.max()  # no autocall cliff


def _wo_setup():
    ois = SpdtCurveAsOIS(_spdt_ois_curve(0.06))
    spots0 = np.array([100.0, 100.0, 100.0])
    vols = np.array([0.25, 0.28, 0.24])
    corr = np.full((3, 3), 0.6)
    np.fill_diagonal(corr, 1.0)
    wo = WorstOfAutocallable(notional=100.0, observation_times=(0.5, 1.0, 1.5, 2.0),
                             coupon_rate=0.06, autocall_level=1.0, coupon_barrier=0.75, knock_in=0.6,
                             memory=True, underlyings=("A", "B", "C"),
                             initial_fixings=(100.0, 100.0, 100.0))  # struck at the spot levels
    pkg = worst_of_exposure(wo, spots0, vols, corr, ois, ois, time_grid=np.linspace(0.0, 1.95, 12),
                            r=0.06, q=0.0, n_paths=20_000, seed=1)
    return wo, spots0, vols, corr, pkg


def test_worst_of_value_at_zero_reconciles_with_price_worst_of():
    wo, spots0, vols, corr, pkg = _wo_setup()
    price = price_worst_of(wo, spots0, vols, corr, r=0.06, q=0.0, n_paths=50_000, seed=2).price
    assert float(pkg.npv_paths[:, 0].mean()) == pytest.approx(price, abs=1.5)


def test_worst_of_ee_rises_then_collapses_on_basket_autocall():
    _, _, _, _, pkg = _wo_setup()
    ee = pkg.expected_exposure()
    assert np.all(np.isfinite(ee)) and np.all(ee >= 0.0)
    assert ee.max() > ee[0]                    # builds
    assert ee[-1] < 0.7 * ee.max()             # collapses as the basket autocalls
    assert ee[-1] > 0.0
    assert (ee[1:] / np.maximum(ee[:-1], 1e-9)).min() < 0.8  # an autocall cliff


def test_worst_of_exposure_flows_through_to_a_cva():
    _, _, _, _, pkg = _wo_setup()
    cva = CVAEngine(pkg.ois_curve).compute_cva(
        pkg.expected_exposure(), pkg.time_grid, CreditCurve(cds_spread_bps=300.0, recovery_rate=0.40)
    )
    assert np.isfinite(cva) and cva > 0.0


# --- Phase 4: the all-in price — XVA folded into the structurer's solve ----------------------

def _allin_pieces():
    ois = SpdtCurveAsOIS(_spdt_ois_curve(0.06))
    model = BlackScholes(spot=100.0, r=0.06, q=0.0, sigma=0.22)
    obs = (0.5, 1.0, 1.5, 2.0)
    profile = np.linspace(0.0, 1.95, 8)

    def make(c):
        return Autocallable(notional=100.0, observation_times=obs, coupon_rate=c, autocall_level=1.0,
                            coupon_barrier=0.8, knock_in=0.6, memory=True, initial_fixing=None)

    price = lambda c: price_mc(make(c), model, n_paths=30_000, seed=11).price  # noqa: E731
    expo = lambda c: autocallable_exposure(make(c), model, ois, ois,  # noqa: E731
                                           time_grid=profile, n_paths=12_000, seed=5)
    return price, expo


def test_xva_charge_grows_with_counterparty_spread():
    _, expo = _allin_pieces()
    pkg = expo(0.04)
    near = xva_charge(pkg, CreditCurve(cds_spread_bps=1e-6, recovery_rate=0.40))
    mid = xva_charge(pkg, CreditCurve(cds_spread_bps=200.0, recovery_rate=0.40))
    wide = xva_charge(pkg, CreditCurve(cds_spread_bps=600.0, recovery_rate=0.40))
    assert near["cva"] == pytest.approx(0.0, abs=1e-3)
    assert wide["cva"] > mid["cva"] > near["cva"]
    assert mid["fva"] > 0.0 and mid["total"] == pytest.approx(mid["cva"] + mid["fva"])


def test_all_in_coupon_is_below_par_coupon_and_falls_with_spread():
    """The headline of the combined platform: carrying XVA lowers the coupon the desk can offer,
    and a wider counterparty spread lowers it further."""
    price, expo = _allin_pieces()

    def coupon_at(spread_bp):
        res = solve_coupon_all_in(price, expo, CreditCurve(cds_spread_bps=spread_bp, recovery_rate=0.40),
                                  par=100.0, fee=1.0, bracket=(0.0, 0.25))
        return res["coupon_base"], res["coupon_all_in"]

    base, allin_tight = coupon_at(50.0)
    _, allin_wide = coupon_at(500.0)
    assert allin_tight < base                 # XVA eats into the offered coupon
    assert allin_wide < allin_tight           # and more so as the counterparty deteriorates
    assert allin_wide > 0.0                    # still a real, sellable note
