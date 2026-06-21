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
    CSA,
    ExposurePackage,
    GovernanceGate,
    SpdtCurveAsOIS,
    autocallable_exposure,
    collateralise,
    economic_capital,
    european_exposure,
    exposure_metrics,
    mark_to_future_european,
    netting_set_exposure,
    note_exposure,
    solve_coupon_all_in,
    worst_of_exposure,
    wrong_way_ee,
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


# --- Phase 5: the governance gate — APPROVE / REJECT / MANUAL_REVIEW over the exposure seam ----

def _governance_pkg():
    """An autocallable exposure package + counterparty credit, the gate's two primary inputs."""
    ois = SpdtCurveAsOIS(_spdt_ois_curve(0.06))
    note = Autocallable(notional=100.0, observation_times=(0.5, 1.0, 1.5, 2.0), coupon_rate=0.04,
                        autocall_level=1.0, coupon_barrier=0.8, knock_in=0.6, memory=True,
                        initial_fixing=None)
    model = BlackScholes(spot=100.0, r=0.06, q=0.0, sigma=0.22)
    pkg = autocallable_exposure(note, model, ois, ois, time_grid=np.linspace(0.0, 1.95, 14),
                                n_paths=20_000, seed=1)
    return pkg, CreditCurve(cds_spread_bps=200.0, recovery_rate=0.40)


def test_exposure_metrics_are_ordered_and_consistent():
    """The CCR ladder read off the cube: a tail quantile dominates the mean peak, the running-max
    average dominates the raw average, and EAD is exactly α·EEPE."""
    pkg, _ = _governance_pkg()
    m = exposure_metrics(pkg, alpha=1.4)
    assert m["PFE"] >= m["EE_peak"] >= m["EEPE"] >= m["EPE"] >= 0.0
    assert m["EAD"] == pytest.approx(1.4 * m["EEPE"], rel=1e-12)


def test_economic_capital_grows_with_counterparty_spread():
    """Unexpected loss is monotone in default risk: a wider CDS spread consumes more capital."""
    pkg, _ = _governance_pkg()
    tight = economic_capital(pkg, CreditCurve(cds_spread_bps=100.0, recovery_rate=0.40))
    wide = economic_capital(pkg, CreditCurve(cds_spread_bps=600.0, recovery_rate=0.40))
    assert wide["Economic_Capital"] > tight["Economic_Capital"] > 0.0


def test_clean_accretive_trade_within_limits_is_approved():
    """Generous limits + a fat margin clears every gate → APPROVED, with all charges reported."""
    pkg, cc = _governance_pkg()
    gate = GovernanceGate(limits=[{"LegalEntityID": "LE_CP-0", "Metric": "EAD", "LimitAmount": 1e9}])
    res = gate.evaluate(pkg, cc, revenue=20.0)
    assert res["Decision"] == "APPROVED"
    assert res["Limit_Status"] == "PASS"
    assert res["XVA_Total"] == pytest.approx(res["CVA"] + res["FVA"])
    assert res["Trade_RAROC"] >= gate.hurdle_rate


def test_limit_breach_rejects_the_trade():
    """An EAD limit below the trade's own EAD is a breach → REJECTED, regardless of profitability."""
    pkg, cc = _governance_pkg()
    ead = exposure_metrics(pkg)["EAD"]
    gate = GovernanceGate(limits=[{"LegalEntityID": "LE_CP-0", "Metric": "EAD",
                                   "LimitAmount": ead * 0.5}])
    res = gate.evaluate(pkg, cc, revenue=20.0)
    assert res["Decision"] == "REJECTED"
    assert res["Limit_Status"] == "FAIL"
    assert "Limit breach detected." in res["Reasons"]


def test_sub_hurdle_margin_routes_to_manual_review():
    """Within limits but the margin doesn't cover XVA + capital cost → not auto-approved."""
    pkg, cc = _governance_pkg()
    gate = GovernanceGate(limits=[{"LegalEntityID": "LE_CP-0", "Metric": "EAD", "LimitAmount": 1e9}])
    res = gate.evaluate(pkg, cc, revenue=1e-6)
    assert res["Decision"] == "MANUAL_REVIEW"
    assert res["Trade_RAROC"] < gate.hurdle_rate
    assert "Standalone RAROC below hurdle." in res["Reasons"]


def test_amber_utilisation_downgrades_approval_to_manual_review():
    """A trade that would clear on profitability but lands in the amber band (80–100% of an EAD
    limit) is held back from auto-approval for a human to sign off."""
    pkg, cc = _governance_pkg()
    ead = exposure_metrics(pkg)["EAD"]
    gate = GovernanceGate(limits=[{"LegalEntityID": "LE_CP-0", "Metric": "EAD",
                                   "LimitAmount": ead / 0.9}])  # utilisation ≈ 0.9 → amber
    res = gate.evaluate(pkg, cc, revenue=20.0)
    assert res["Limit_Status"] == "WARNING"
    assert res["Decision"] == "MANUAL_REVIEW"
    assert "Approaching limit (amber)." in res["Reasons"]


# --- Phase 7: CCR depth — bilateral DVA, KVA, EEPE cap, collateral, netting, wrong-way risk ----

def _two_sided_pkg(seed=0, n_paths=4000):
    """A synthetic Brownian exposure cube with both signs — needed to exercise the negative side
    (DVA, netting benefit) that a long autocallable note never shows."""
    ois = SpdtCurveAsOIS(_spdt_ois_curve(0.05))
    grid = np.linspace(0.0, 1.0, 11)
    rng = np.random.default_rng(seed)
    incr = rng.standard_normal((n_paths, 10)) * 0.10
    npv = np.concatenate([np.zeros((n_paths, 1)), np.cumsum(incr, axis=1)], axis=1)
    return ExposurePackage("SYN", "CP-0", "ns", grid, npv, ois, ois), ois


def test_expected_negative_exposure_is_nonpositive_and_mirrors_ee():
    pkg, _ = _two_sided_pkg()
    ene = pkg.expected_negative_exposure()
    ee = pkg.expected_exposure()
    assert np.all(ene <= 0.0) and np.all(ee >= 0.0)
    assert ene.min() < 0.0 and ee.max() > 0.0  # genuinely two-sided


def test_dva_is_a_benefit_so_bilateral_charge_is_below_unilateral():
    """DVA nets *against* the cost: total(bilateral) = CVA + FVA − DVA < CVA + FVA."""
    pkg, _ = _two_sided_pkg()
    cpty = CreditCurve(cds_spread_bps=300.0, recovery_rate=0.40)
    own = CreditCurve(cds_spread_bps=120.0, recovery_rate=0.40)
    uni = xva_charge(pkg, cpty)
    bil = xva_charge(pkg, cpty, own_credit_curve=own)
    assert uni["dva"] == 0.0
    assert bil["dva"] > 0.0
    assert bil["total"] == pytest.approx(bil["cva"] + bil["fva"] + bil["kva"] - bil["dva"])
    assert bil["total"] < uni["total"]


def test_kva_adds_a_capital_cost_that_scales_with_cost_of_capital():
    _, expo = _allin_pieces()
    pkg = expo(0.04)
    cc = CreditCurve(cds_spread_bps=200.0, recovery_rate=0.40)
    base = xva_charge(pkg, cc)
    with_kva = xva_charge(pkg, cc, cost_of_capital=0.12)
    pricier = xva_charge(pkg, cc, cost_of_capital=0.20)
    assert base["kva"] == 0.0
    assert with_kva["kva"] > 0.0
    assert pricier["kva"] > with_kva["kva"]                       # linear in cost of capital
    assert with_kva["total"] == pytest.approx(with_kva["cva"] + with_kva["fva"] + with_kva["kva"])


def test_eepe_horizon_cap_changes_the_regulatory_ead():
    """Basel caps the EEPE averaging window at one year. Effective EE is the *running max* of EE
    (non-decreasing), so averaging over the first year — which still carries the early ramp — gives a
    strictly lower EEPE than the full-life average: the window is a real modelling choice, not cosmetic."""
    _, _, pkg = _autocall_setup()  # maturity ≈ 2y
    capped = exposure_metrics(pkg, eepe_horizon=1.0)
    full = exposure_metrics(pkg, eepe_horizon=10.0)
    assert capped["EEPE"] < full["EEPE"]
    assert capped["EAD"] == pytest.approx(1.4 * capped["EEPE"])


def test_collateral_reduces_exposure_and_cva():
    """A CSA (here zero-threshold, 10-day MPoR) leaves only the close-out gap, so collateralised
    EAD and CVA sit well below the uncollateralised values."""
    _, _, pkg = _autocall_setup()
    cc = CreditCurve(cds_spread_bps=300.0, recovery_rate=0.40)
    coll = collateralise(pkg, CSA(threshold=0.0, mpor_days=10))
    assert exposure_metrics(coll)["EAD"] < exposure_metrics(pkg)["EAD"]
    assert xva_charge(coll, cc)["cva"] < xva_charge(pkg, cc)["cva"]


def test_netting_benefit_offsetting_trades_net_down():
    """Two offsetting positions on common paths: the netted exposure collapses far below the sum of
    the standalone exposures — the netting benefit."""
    pkg_long, ois = _two_sided_pkg(seed=1)
    pkg_short = ExposurePackage("SYN2", "CP-0", "ns", pkg_long.time_grid, -pkg_long.npv_paths, ois, ois)
    netted = netting_set_exposure([pkg_long, pkg_short])
    sum_standalone = pkg_long.expected_exposure() + pkg_short.expected_exposure()
    assert netted.expected_exposure().max() < 0.1 * sum_standalone.max()  # near-perfect offset


def test_netting_requires_common_grid_and_counterparty():
    pkg, ois = _two_sided_pkg()
    other_cp = ExposurePackage("X", "OTHER-CP", "ns", pkg.time_grid, pkg.npv_paths, ois, ois)
    with pytest.raises(ValueError):
        netting_set_exposure([pkg, other_cp])


def test_wrong_way_risk_lifts_ee_and_cva_right_way_lowers_it():
    """Exponential tilt: β>0 (wrong-way) up-weights high-exposure paths → EE and CVA rise above the
    independent case; β<0 (right-way) pulls them below. β=0 is the ordinary EE."""
    _, _, pkg = _autocall_setup()
    cc = CreditCurve(cds_spread_bps=300.0, recovery_rate=0.40)
    indep = pkg.expected_exposure().sum()
    assert wrong_way_ee(pkg, beta=0.0).sum() == pytest.approx(indep)
    assert wrong_way_ee(pkg, beta=0.8).sum() > indep
    assert wrong_way_ee(pkg, beta=-0.8).sum() < indep
    assert xva_charge(pkg, cc, wwr_beta=0.8)["cva"] > xva_charge(pkg, cc)["cva"]
    assert xva_charge(pkg, cc, wwr_beta=-0.8)["cva"] < xva_charge(pkg, cc)["cva"]
