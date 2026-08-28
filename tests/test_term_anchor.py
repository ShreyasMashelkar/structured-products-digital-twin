"""Anchoring the long end of the variance term structure on realised history.

NIFTY quotes a surface to ~4 months and notes are sold at 1-3 years, so the long end is
extrapolation either way. These tests pin that it is *disciplined* extrapolation: arbitrage-free
at every tenor, converging on a level history can defend, and never overwriting a real quote.
"""

import numpy as np
import pytest

from spdt.vol.term_anchor import (
    AnchoredVarianceCurve,
    extend_pillars,
    fit_anchored_curve,
    realised_variance,
)


def test_curve_is_calendar_arbitrage_free_at_every_tenor():
    """w(0)=0 and w strictly increasing, so forward variance is positive everywhere -- the
    property flat-variance extrapolation violates the moment it is asked for a longer tenor."""
    curve = AnchoredVarianceCurve(v0=0.0090, kappa=1.5, v_inf=0.0324)
    taus = np.linspace(1e-4, 30.0, 4000)
    w = np.array([curve.total_variance(float(t)) for t in taus])
    assert curve.total_variance(0.0) == 0.0
    assert np.all(np.diff(w) > 0.0)


def test_the_anchor_is_what_the_long_end_converges_to():
    curve = AnchoredVarianceCurve(v0=0.0090, kappa=1.5, v_inf=0.0324)
    assert curve.atm_vol(0.001) == pytest.approx(np.sqrt(0.0090), rel=1e-3)  # -> sqrt(v0)
    assert curve.atm_vol(200.0) == pytest.approx(np.sqrt(0.0324), rel=1e-2)  # -> sqrt(v_inf)
    # and it is monotone between the two when the front is below the anchor
    vols = [curve.atm_vol(t) for t in (0.1, 0.5, 1.0, 2.0, 5.0, 10.0)]
    assert vols == sorted(vols)


def test_fit_recovers_a_known_curve():
    truth = AnchoredVarianceCurve(v0=0.0081, kappa=2.0, v_inf=0.0324)
    observed = [(t, truth.atm_vol(t)) for t in (0.03, 0.07, 0.16, 0.34)]
    fitted = fit_anchored_curve(observed, v_inf=0.0324)
    for t in (0.03, 0.34, 1.5):
        assert fitted.atm_vol(t) == pytest.approx(truth.atm_vol(t), abs=2e-3)


def test_the_anchor_is_held_fixed_not_fitted():
    """The whole point of the split: the liquid front sets v0 and kappa, history sets v_inf.
    A four-month front must not be allowed to determine the three-year level."""
    observed = [(0.03, 0.0935), (0.07, 0.0930), (0.16, 0.0942), (0.34, 0.1085)]
    low = fit_anchored_curve(observed, v_inf=0.02**2 * 100)   # 20% long-run
    high = fit_anchored_curve(observed, v_inf=0.28**2)         # 28% long-run
    assert low.v_inf != high.v_inf
    assert high.atm_vol(3.0) > low.atm_vol(3.0)
    # ...while both still track the observed front closely
    for t, v in observed:
        assert low.atm_vol(t) == pytest.approx(v, abs=0.02)
        assert high.atm_vol(t) == pytest.approx(v, abs=0.02)


def test_observed_pillars_are_never_overwritten():
    observed = [(0.03, 0.0935), (0.16, 0.0942), (0.34, 0.1085)]
    curve = fit_anchored_curve(observed, v_inf=0.0324)
    out = extend_pillars(observed, curve, horizons=(0.10, 0.34, 0.5, 1.0, 2.0, 3.0))
    assert out[: len(observed)] == tuple(sorted(observed))       # verbatim, in order
    assert [t for t, _ in out[len(observed):]] == [0.5, 1.0, 2.0, 3.0]  # only strictly beyond
    assert all(t > 0.34 for t, _ in out[len(observed):])


def test_premium_scales_the_anchor_and_defaults_to_none():
    observed = [(0.03, 0.0935), (0.16, 0.0942), (0.34, 0.1085)]
    plain = fit_anchored_curve(observed, v_inf=0.0324)
    richer = fit_anchored_curve(observed, v_inf=0.0324, premium=1.20)
    assert plain.v_inf == pytest.approx(0.0324)
    assert richer.v_inf == pytest.approx(0.0324 * 1.20)
    assert richer.atm_vol(3.0) > plain.atm_vol(3.0)


def test_realised_variance_recovers_a_known_volatility():
    rng = np.random.default_rng(7)
    sigma, n = 0.18, 252 * 20
    steps = rng.normal(0.0, sigma / np.sqrt(252.0), n)
    closes = 1000.0 * np.exp(np.cumsum(steps))
    assert np.sqrt(realised_variance(closes)) == pytest.approx(sigma, rel=0.05)


def test_realised_variance_refuses_degenerate_input():
    with pytest.raises(ValueError, match="at least three"):
        realised_variance([100.0, 101.0])
    with pytest.raises(ValueError, match="strictly positive"):
        realised_variance([100.0, 0.0, 101.0])


def test_rejects_malformed_curves():
    for kw in ({"v0": 0.0, "kappa": 1.0, "v_inf": 0.03},
               {"v0": 0.01, "kappa": 0.0, "v_inf": 0.03},
               {"v0": 0.01, "kappa": 1.0, "v_inf": -0.03}):
        with pytest.raises(ValueError):
            AnchoredVarianceCurve(**kw)
    with pytest.raises(ValueError, match="at least one observed pillar"):
        fit_anchored_curve([], v_inf=0.03)
