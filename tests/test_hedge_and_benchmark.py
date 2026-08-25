"""Hedge backtest and EDGAR benchmark (network-free)."""


import numpy as np
import pytest

from spdt.data.ingest.edgar import parse_filing
from spdt.pricing.models.bs import BlackScholes
from spdt.products.catalog import Autocallable
from spdt.validation.edgar_benchmark import (
    funding_discounter,
    gap_by_tenor,
    implied_funding_spread,
    implied_vol_from_note,
    price_filed_note,
    summarise,
)
from spdt.validation.hedge_backtest import (
    backtest_hedge_on_path,
    rebalance_frequency_sweep,
)

FILING_TEXT = (
    "Autocallable Contingent Coupon (with Memory) Notes $10 principal amount per unit "
    "Pricing Date Settlement Date Maturity Date August 11, 2025 August 14, 2025 August 18, 2026 "
    "Coupon Barrier: 60.00, which is 60% of the Starting Value "
    "Threshold Value: 60.00, which is 60% of the Starting Value "
    "Call Value: 100.00, which is 100% of the Starting Value "
    "The Contingent Coupon Payment (with Memory) is $0.439 per unit "
    "on each quarterly Coupon Observation Date. "
    "The initial estimated value of the notes as of the pricing date is $9.76 per unit."
)

R, Q = 0.042, 0.013


def _filing():
    return parse_filing(FILING_TEXT, issuer="GS Finance Corp.")


def _live_note() -> Autocallable:
    """Barriers tight enough to carry real delta over the test horizon."""
    return Autocallable(
        notional=100.0, observation_times=(0.25, 0.5, 0.75, 1.0), coupon_rate=0.02,
        autocall_level=1.02, coupon_barrier=0.95, knock_in=0.90, memory=True,
    )


def _path(drift: float = 0.0, vol: float = 0.20, n: int = 25, s0: float = 15_000.0):
    """A deterministic pseudo-realised path — fixed seed, so the test is reproducible."""
    rng = np.random.default_rng(7)
    times = np.linspace(0.0, 1.0, n)
    dt = np.diff(times)
    shocks = (drift - 0.5 * vol**2) * dt + vol * np.sqrt(dt) * rng.standard_normal(n - 1)
    return times, s0 * np.exp(np.concatenate([[0.0], np.cumsum(shocks)]))


# --- funding & benchmark --------------------------------------------------------------------


def test_funding_curve_discounts_the_bond_leg_below_ois():
    d = funding_discounter(0.042, 0.015)
    assert d.funding(3.0) < d.ois(3.0)
    assert d.ois(3.0) == pytest.approx(np.exp(-0.042 * 3.0))


def test_funding_spread_lowers_the_note_value():
    """A note is the issuer's funded debt; discounting it at OIS overvalues it."""
    f = _filing()
    flat = price_filed_note(f, spot=100.0, atm_vol=0.45, r=R, q=Q, n_paths=40_000)
    funded = price_filed_note(
        f, spot=100.0, atm_vol=0.45, r=R, q=Q, funding_spread=0.015, n_paths=40_000
    )
    assert funded.model_pv < flat.model_pv


def test_gap_is_measured_against_the_estimated_value_not_the_offering_price():
    """Matching the offering price would absorb the dealer's fee into a risk-neutral value."""
    r = price_filed_note(_filing(), spot=100.0, atm_vol=0.45, r=R, q=Q, n_paths=40_000)
    assert r.estimated_value_pct == pytest.approx(97.6)
    assert r.gap == pytest.approx(r.model_pv - 97.6)
    assert r.gap != pytest.approx(r.gap_vs_offering)


def test_implied_vol_recovers_the_vol_used_to_build_a_synthetic_target():
    """Invert the pricer against its own output: the solved vol must return the input vol."""
    f = _filing()
    known_vol, spread = 0.52, 0.012
    target = price_filed_note(
        f, spot=100.0, atm_vol=known_vol, r=R, q=Q, funding_spread=spread, n_paths=60_000
    ).model_pv
    synthetic = parse_filing(
        FILING_TEXT.replace("is $9.76 per unit", f"is ${target / 10.0:.4f} per unit")
    )
    solved = implied_vol_from_note(
        synthetic, spot=100.0, r=R, q=Q, funding_spread=spread, n_paths=60_000
    )
    assert solved == pytest.approx(known_vol, abs=5e-3)


def test_unreachable_targets_return_none_rather_than_a_clamped_boundary():
    """A clamped boundary value would masquerade as a fit."""
    absurd = parse_filing(FILING_TEXT.replace("is $9.76 per unit", "is $0.01 per unit"))
    assert implied_funding_spread(absurd, spot=100.0, atm_vol=0.45, r=R, q=Q, n_paths=20_000) is None


def test_a_filing_without_fixed_terms_cannot_be_benchmarked():
    with pytest.raises(ValueError, match="fixed terms|disclosed value"):
        price_filed_note(
            parse_filing("nothing useful here"), spot=100.0, atm_vol=0.3, r=R, q=Q
        )


def test_summary_reports_dispersion_not_just_a_mean():
    f = _filing()
    results = [
        price_filed_note(f, spot=100.0, atm_vol=v, r=R, q=Q, n_paths=20_000, seed=i)
        for i, v in enumerate((0.40, 0.45, 0.50))
    ]
    s = summarise(results)
    assert s.n == 3
    assert s.std_gap > 0.0
    assert s.min_gap <= s.median_gap <= s.max_gap
    assert isinstance(s.verdict, str) and s.verdict
    assert set(gap_by_tenor(results)) <= {"<=1y", "1-2y", ">2y"}


def test_empty_summary_is_reported_not_crashed():
    assert summarise([]).n == 0
    assert "no benchmarkable" in summarise([]).verdict


# --- hedge backtest -------------------------------------------------------------------------


def test_hedging_a_sold_note_leaves_a_bounded_residual():
    times, spots = _path()
    result = backtest_hedge_on_path(
        _live_note(), times, spots, vol=0.20, r=0.065, q=0.013, n_paths=10_000
    )
    assert result.premium > 0.0
    assert np.isfinite(result.hedge_pnl)
    assert abs(result.hedge_pnl) < result.premium  # a hedge, not a naked position
    assert result.n_rebalances > 0
    assert result.turnover > 0.0


def test_transaction_cost_rises_with_the_spread_and_reduces_pnl():
    times, spots = _path()
    note = _live_note()
    free = backtest_hedge_on_path(note, times, spots, vol=0.20, r=0.065, q=0.013,
                                  spread_bps=0.0, n_paths=10_000)
    costly = backtest_hedge_on_path(note, times, spots, vol=0.20, r=0.065, q=0.013,
                                    spread_bps=10.0, n_paths=10_000)
    assert free.total_cost == pytest.approx(0.0)
    assert costly.total_cost > 0.0
    assert costly.hedge_pnl < free.hedge_pnl
    assert costly.cost_share_of_pnl > 0.0


def test_turnover_is_a_cash_amount_not_a_share_count():
    """On an index at 15,000 against notional 100, share counts carry no intuition."""
    times, spots = _path()
    result = backtest_hedge_on_path(_live_note(), times, spots, vol=0.20, r=0.065,
                                    q=0.013, n_paths=10_000)
    assert result.turnover > 1.0  # cash scale, not the ~1e-4 share scale


def test_rebalance_frequency_sweep_covers_each_requested_step():
    times, spots = _path()
    sweep = rebalance_frequency_sweep(
        _live_note(), times, spots, vol=0.20, r=0.065, q=0.013,
        every=(1, 3, 6), n_paths=10_000,
    )
    assert set(sweep) == {1, 3, 6}
    assert sweep[1].n_rebalances >= sweep[6].n_rebalances
    assert all(np.isfinite(r.hedge_pnl) for r in sweep.values())


def test_delta_of_a_fully_matured_note_is_zero():
    """Past the last observation there is nothing left to hedge."""
    from spdt.validation.hedge_backtest import _autocallable_delta

    model = BlackScholes(spot=15_000.0, r=0.065, q=0.013, sigma=0.2)
    assert _autocallable_delta(_live_note(), model, t=1.5, n_paths=2_000) == 0.0


def test_a_misaligned_path_is_rejected():
    with pytest.raises(ValueError, match="align|at least two"):
        backtest_hedge_on_path(
            _live_note(), np.array([0.0, 0.5]), np.array([100.0]),
            vol=0.2, r=0.065, q=0.013,
        )


# --- worst-of correlation inversion ---------------------------------------------------------

WORST_OF_TEXT = (
    "Autocallable Contingent Coupon (with Memory) Barrier Notes Linked to the Worst-Performing "
    "of three stocks. $10 principal amount per unit "
    "Pricing Date Settlement Date Maturity Date August 12, 2026 August 19, 2026 August 21, 2028 "
    "Coupon Barrier: META: $347.31 (60.00% of its Starting Value). "
    "AAPL: $181.35 (60.00% of its Starting Value). "
    "TSLA: $196.51 (60.00% of its Starting Value). "
    "Threshold Value: META: $347.31 (60.00% of its Starting Value). "
    "AAPL: $181.35 (60.00% of its Starting Value). "
    "TSLA: $196.51 (60.00% of its Starting Value). "
    "Call Value: META: $578.85 (100.00% of its Starting Value). "
    "AAPL: $302.25 (100.00% of its Starting Value). "
    "TSLA: $327.51 (100.00% of its Starting Value). "
    "The Contingent Coupon Payment (with Memory) is $0.4875 per unit "
    "on each quarterly Coupon Observation Date. "
    "The initial estimated value of the notes as of the pricing date is $9.62 per unit."
)
VOLS = {"META": 0.43, "AAPL": 0.30, "TSLA": 0.51}


def _wo():
    return parse_filing(WORST_OF_TEXT, issuer="BofA Finance LLC")


def test_equicorrelation_is_a_valid_correlation_matrix():
    from spdt.validation.edgar_benchmark import equicorrelation

    for rho in (-0.4, 0.0, 0.5, 0.99):
        m = equicorrelation(3, rho)
        assert np.allclose(np.diag(m), 1.0)
        assert np.allclose(m, m.T)
    assert np.linalg.eigvalsh(equicorrelation(3, 0.5)).min() > 0.0
    # Below −1/(n−1) it stops being positive semi-definite, which is why the bracket is bounded.
    assert np.linalg.eigvalsh(equicorrelation(3, -0.6)).min() < 0.0


def test_worst_of_value_rises_with_correlation():
    """Higher correlation means less dispersion, a better worst performer, a more valuable note.

    If this monotonicity fails the correlation solve is not well posed.
    """
    from spdt.validation.edgar_benchmark import price_worst_of_filing

    f = _wo()
    low = price_worst_of_filing(f, vols=VOLS, rho=0.10, r=R, q=Q, n_paths=30_000)
    high = price_worst_of_filing(f, vols=VOLS, rho=0.95, r=R, q=Q, n_paths=30_000)
    assert high > low


def test_implied_correlation_recovers_a_synthetic_target():
    """Invert the worst-of pricer against its own output."""
    from spdt.validation.edgar_benchmark import implied_correlation, price_worst_of_filing

    f = _wo()
    known = 0.55
    target = price_worst_of_filing(
        f, vols=VOLS, rho=known, r=R, q=Q, funding_spread=0.012, n_paths=40_000
    )
    synthetic = parse_filing(
        WORST_OF_TEXT.replace("is $9.62 per unit", f"is ${target / 10.0:.4f} per unit")
    )
    solved = implied_correlation(
        synthetic, vols=VOLS, r=R, q=Q, funding_spread=0.012, n_paths=40_000
    )
    assert solved == pytest.approx(known, abs=0.03)


def test_unreachable_correlation_returns_none():
    """A disclosed value no correlation can reach is reported, not clamped to the bracket end."""
    from spdt.validation.edgar_benchmark import implied_correlation

    absurd = parse_filing(WORST_OF_TEXT.replace("is $9.62 per unit", "is $2.00 per unit"))
    assert implied_correlation(absurd, vols=VOLS, r=R, q=Q, n_paths=20_000) is None


def test_single_underlying_filings_have_no_implied_correlation():
    from spdt.validation.edgar_benchmark import implied_correlation

    assert implied_correlation(_filing(), vols=VOLS, r=R, q=Q, n_paths=10_000) is None


def test_pricing_needs_a_vol_for_every_leg():
    """A missing leg's vol leaves correlation unidentified; refuse rather than drop the leg."""
    from spdt.validation.edgar_benchmark import price_worst_of_filing

    with pytest.raises(ValueError, match="at least two underlyings"):
        price_worst_of_filing(_wo(), vols={"META": 0.43}, rho=0.5, r=R, q=Q, n_paths=5_000)


# --- shaped correlation & leg-based worst-of funding ---------------------------------------


def test_shaped_correlation_interpolates_between_realised_and_unity():
    from spdt.validation.edgar_benchmark import shaped_correlation

    base = np.array([[1.0, 0.3, 0.5], [0.3, 1.0, 0.7], [0.5, 0.7, 1.0]])
    names = ["A", "B", "C"]
    at_one = shaped_correlation(names, base, 1.0)
    assert np.allclose(at_one, base)
    near_zero = shaped_correlation(names, base, 0.01)
    assert near_zero[0, 1] > 0.98  # approaches perfect correlation …
    assert near_zero[0, 1] <= 0.995  # … but never reaches the singular all-ones matrix


def test_shaped_correlation_is_always_choleskyable():
    """The failure this guards against was silent: LinAlgError subclasses ValueError, so a
    singular endpoint vanished into the solver's except-clause and every inversion read
    'unreachable'."""
    from spdt.validation.edgar_benchmark import shaped_correlation

    base = np.array([[1.0, 0.09, 0.1], [0.09, 1.0, 0.12], [0.1, 0.12, 1.0]])
    for scale in (0.0, 0.5, 1.0, 1.8):  # includes both degenerate regimes
        m = shaped_correlation(["A", "B", "C"], base, scale)
        np.linalg.cholesky(m)  # must not raise
        assert np.allclose(np.diag(m), 1.0)


def test_realised_correlation_recovers_a_known_structure():
    from spdt.validation.edgar_benchmark import realised_correlation

    rng = np.random.default_rng(3)
    common = rng.standard_normal(300)
    a = np.exp(np.cumsum(0.01 * common))
    b = np.exp(np.cumsum(0.01 * (0.9 * common + np.sqrt(1 - 0.81) * rng.standard_normal(300))))
    c = np.exp(np.cumsum(0.01 * rng.standard_normal(300)))
    corr = realised_correlation({"A": a, "B": b, "C": c})
    assert corr is not None
    assert corr[0, 1] > 0.8  # A and B share a driver
    assert abs(corr[0, 2]) < 0.25  # C does not


def test_realised_correlation_refuses_short_series():
    from spdt.validation.edgar_benchmark import realised_correlation

    short = {"A": np.ones(10), "B": np.ones(10)}
    assert realised_correlation(short, min_overlap=60) is None


def test_worst_of_leg_funding_lowers_the_value_like_the_single_name_path():
    """The bond leg is the issuer's debt; discounting it risk-free overvalues the note. The
    multiplicative shortcut this replaces also over-penalised autocalling notes, whose expected
    life is far shorter than their stated maturity."""
    from spdt.pricing.engine import price_worst_of
    from spdt.products.catalog import WorstOfAutocallable
    from spdt.validation.edgar_benchmark import funding_discounter

    note = WorstOfAutocallable(
        notional=100.0, observation_times=(0.5, 1.0, 1.5, 2.0), coupon_rate=0.02,
        autocall_level=1.0, coupon_barrier=0.8, knock_in=0.6, memory=True,
        underlyings=("A", "B"), initial_fixings=(100.0, 100.0),
    )
    spots = np.array([100.0, 100.0])
    vols = np.array([0.3, 0.4])
    corr = np.array([[1.0, 0.5], [0.5, 1.0]])
    flat = price_worst_of(note, spots, vols, corr, r=0.04, q=0.0, n_paths=40_000, seed=2).price
    funded = price_worst_of(
        note, spots, vols, corr, r=0.04, q=0.0, n_paths=40_000, seed=2,
        discount=funding_discounter(0.04, 0.015),
    ).price
    assert funded < flat
    # And by less than spread x full tenor: the note autocalls early with high probability,
    # which is exactly what the old whole-PV discount ignored.
    assert flat - funded < flat * 0.015 * 2.0


def test_implied_scale_recovers_a_synthetic_target():
    from spdt.validation.edgar_benchmark import implied_correlation_scale, shaped_correlation

    f = _wo()
    base = np.array([[1.0, 0.3, 0.5], [0.3, 1.0, 0.7], [0.5, 0.7, 1.0]])
    names = [t for t, _ in f.starting_values]
    known = 0.6
    # Price at the shaped matrix for the known scale, then invert for it.
    from spdt.pricing.engine import price_worst_of
    from spdt.products.catalog import WorstOfAutocallable
    from spdt.validation.edgar_benchmark import funding_discounter

    starts = dict(f.starting_values)
    spots = np.array([starts[t] for t in names])
    sigma = np.array([VOLS[t] for t in names])
    wo = WorstOfAutocallable(
        notional=100.0, observation_times=f.observation_times(),
        coupon_rate=(f.coupon_per_period or 0.0) / f.denomination,
        autocall_level=f.call_level or 1.0, coupon_barrier=f.coupon_barrier or 0.8,
        knock_in=f.knock_in or 0.6, memory=f.memory,
        underlyings=tuple(names), initial_fixings=tuple(spots),
    )
    target = price_worst_of(
        wo, spots, sigma, shaped_correlation(names, base, known),
        r=R, q=Q, n_paths=40_000, seed=0, discount=funding_discounter(R, 0.012),
    ).price
    synthetic = parse_filing(
        WORST_OF_TEXT.replace("is $9.62 per unit", f"is ${target / 10.0:.4f} per unit")
    )
    solved = implied_correlation_scale(
        synthetic, vols=VOLS, base_corr=base, r=R, q=Q, funding_spread=0.012, n_paths=40_000
    )
    assert solved == pytest.approx(known, abs=0.08)
