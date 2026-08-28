"""Calibration fit quality: the surface must report how well it actually fits, not just that
it is arbitrage-free.

The distinction under test is that a *clean* surface and a *faithful* surface are different
claims. The deliberately-bad fit below is arbitrage-free and still wrong by vol points; if
``FitReport`` cannot tell those two cases apart it is not doing its job.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from spdt.data.curate.bs_inversion import IVPoint
from spdt.vol.quality import assess_fit, slice_errors_bps
from spdt.vol.surface import VolSurface
from spdt.vol.svi import SVIParams, calibrate_svi, total_variance_from_iv

TODAY = date(2020, 3, 23)
EXPIRY = TODAY + timedelta(days=38)
TAU = 38 / 365.0


def _smile_points(vol_atm: float = 0.55, skew: float = -0.15) -> list[IVPoint]:
    """A skewed smile dense enough to fit SVI's five parameters, spanning both wings."""
    ks = np.linspace(-0.35, 0.35, 15)
    ivs = vol_atm + skew * ks + 0.6 * ks**2
    return [
        IVPoint(EXPIRY, 7500.0 * float(np.exp(k)), k >= 0, float(k), TAU, float(iv))
        for k, iv in zip(ks, ivs)
    ]


def _calibrated(points: list[IVPoint]) -> tuple[SVIParams, dict, dict]:
    k = np.array([p.log_moneyness for p in points])
    w = total_variance_from_iv(np.array([p.implied_vol for p in points]), TAU)
    params = calibrate_svi(k, np.asarray(w))
    return params, {EXPIRY: params}, {EXPIRY: TAU}


def test_a_good_fit_reports_small_error():
    points = _smile_points()
    _, slices, taus = _calibrated(points)
    report = assess_fit(points, slices, taus)

    assert report.n_points == len(points)
    assert report.rmse_bps < 50.0, f"SVI should fit a smooth smile tightly, got {report.rmse_bps}"
    assert report.is_within(50.0)
    assert report.slices[0].r_squared > 0.99


def test_a_deliberately_wrong_fit_is_caught_even_though_it_is_arbitrage_free():
    """A flat slice 5 vol points below the market: admissible, but badly wrong."""
    points = _smile_points()
    flat_low = SVIParams(a=(0.50**2) * TAU, b=0.0, rho=0.0, m=0.0, sigma=0.1)
    report = assess_fit(points, {EXPIRY: flat_low}, {EXPIRY: TAU})

    assert report.rmse_bps > 300.0
    assert not report.is_within(50.0)
    assert report.slices[0].mean_bias_bps < 0.0  # fit sits below the market, and says so


def test_errors_are_reported_per_moneyness_bucket():
    """Aggregate RMSE hides wing failure; the bucket breakdown is what exposes it."""
    points = _smile_points()
    _, slices, taus = _calibrated(points)
    report = assess_fit(points, slices, taus)

    names = {b.bucket for b in report.buckets}
    assert "atm" in names and names & {"deep_put_wing", "put_wing"}
    assert sum(b.n_points for b in report.buckets) == report.n_points


def test_error_conversion_is_in_vol_bps():
    """One known 100bps offset must read as exactly 100bps, not as a variance difference."""
    k = np.array([0.0])
    iv_market = np.array([0.50])
    off_by_1pct = SVIParams(a=(0.51**2) * TAU, b=0.0, rho=0.0, m=0.0, sigma=1e-6)
    err = slice_errors_bps(off_by_1pct, k, iv_market, TAU)
    assert err[0] == pytest.approx(100.0, abs=1.0)


def test_surface_carries_its_fit_report_and_survives_a_round_trip():
    points = _smile_points()
    surface = VolSurface.calibrate(points, "NIFTY")

    assert surface.fit_status is not None
    assert surface.fit_status.rmse_bps < 50.0
    assert surface.fit_status.worst_slice is not None

    revived = VolSurface.from_dict(surface.to_dict())
    assert revived.fit_status is not None
    assert revived.fit_status.rmse_bps == pytest.approx(surface.fit_status.rmse_bps)
    assert revived.fit_status.slices[0].expiry == EXPIRY
    # Diagnostics must not perturb the economic content hash.
    assert revived.content_hash == surface.content_hash


def test_fit_quality_is_independent_of_arbitrage_status():
    """The two reports answer different questions and must not be conflated."""
    points = _smile_points()
    surface = VolSurface.calibrate(points, "NIFTY")
    flat_low = SVIParams(a=(0.50**2) * TAU, b=0.0, rho=0.0, m=0.0, sigma=0.1)
    bad = assess_fit(points, {EXPIRY: flat_low}, {EXPIRY: TAU})

    from spdt.vol.arbitrage import check_slices

    assert check_slices([flat_low]).butterfly_ok  # admissible …
    assert bad.rmse_bps > surface.fit_status.rmse_bps  # … and still much worse


def test_unreliable_slices_are_identified_individually():
    """A surface is rarely uniformly good; the report must localise the bad tenors."""
    points = _smile_points()
    _, good_slices, taus = _calibrated(points)
    good = good_slices[EXPIRY]

    bad_expiry = EXPIRY + timedelta(days=30)
    bad_tau = TAU + 30 / 365.0
    bad_points = [
        IVPoint(bad_expiry, p.strike, p.is_call, p.log_moneyness, bad_tau, p.implied_vol)
        for p in points
    ]
    flat_wrong = SVIParams(a=(0.30**2) * bad_tau, b=0.0, rho=0.0, m=0.0, sigma=0.1)

    report = assess_fit(
        points + bad_points,
        {EXPIRY: good, bad_expiry: flat_wrong},
        {EXPIRY: TAU, bad_expiry: bad_tau},
    )
    flagged = report.unreliable_slices(tolerance_bps=200.0)
    assert [s.expiry for s in flagged] == [bad_expiry]
    assert report.reliable_fraction(200.0) == pytest.approx(0.5)


def test_otm_only_filter_drops_the_itm_half_of_each_strike():
    """Settlement prints violate put-call parity; keeping both halves cannot be fitted."""
    from datetime import date as _date

    from spdt.core.types import SourceTag
    from spdt.data import build_snapshot
    from spdt.data.curate import invert_chain
    from spdt.data.ingest import RawMarketData, RawOptionQuote

    as_of, expiry = _date(2020, 3, 23), _date(2020, 4, 30)
    quotes = tuple(
        RawOptionQuote(expiry=expiry, strike=k, is_call=c, settlement_price=200.0)
        for k in (7000.0, 7500.0, 8000.0)
        for c in (True, False)
    )
    raw = RawMarketData(
        date=as_of, underlying="NIFTY", spot=7578.0, option_chain=quotes,
        ois_zero_rates={expiry: 0.065}, funding_spread_knots={expiry: 0.012},
        dividend_yield=0.013, source=SourceTag.OBSERVED,
    )
    curve = build_snapshot(raw).ois_curve
    both = invert_chain(raw, curve)
    otm = invert_chain(raw, curve, otm_only=True)

    assert len(otm) < len(both)
    # Every survivor is out of the money: calls above the forward, puts below it.
    assert all(p.is_call == (p.log_moneyness >= 0.0) for p in otm)


def test_ssvi_slices_are_arbitrage_free_where_independent_svi_slices_are_not():
    """The live desk panel reported butterfly and calendar violations while the desk's own
    surface was clean, because the two calibrated different models off the same chain.
    Independent per-slice SVI is unconstrained across strikes and tenors and guarantees
    nothing; SSVI is Gatheral-Jacquier constrained and calendar-free by construction."""
    from spdt.vol.arbitrage import check_calendar

    # Noisy multi-tenor points of the kind a real chain produces.
    rng = np.random.default_rng(11)
    pts: list[IVPoint] = []
    for tau, atm in ((0.03, 0.096), (0.16, 0.099), (0.34, 0.108), (0.84, 0.128)):
        expiry = TODAY + timedelta(days=round(tau * 365))
        for k in np.linspace(-0.30, 0.30, 14):
            iv = atm - 0.22 * k + 0.55 * k**2 + float(rng.normal(0.0, 0.004))
            pts.append(IVPoint(expiry, 24000.0 * float(np.exp(k)), k >= 0,
                               float(k), tau, float(iv)))

    ssvi = VolSurface.calibrate(pts, "NIFTY", param_model="SSVI")
    ordered = sorted(ssvi.slices, key=lambda e: ssvi.taus[e])
    assert ssvi.arb_status.butterfly_ok
    assert ssvi.arb_status.calendar_ok
    assert ssvi.arb_status.min_g >= 0.0
    assert check_calendar([ssvi.slices[e] for e in ordered])
