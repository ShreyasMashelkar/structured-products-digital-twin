"""Likelihood-ratio delta on the autocallable: the estimator that sees the barrier jumps.

AAD and a finite-difference bump disagree by 60–73% on this product. That is not a bug — the
adjoint differentiates the payoff, and the payoff is a step function of the observation spots,
so the Dirac terms are invisible to it. The LR estimator differentiates the *density* instead
and so keeps them. Agreement between LR and bump is what turns two disagreeing numbers into a
validated one.
"""

import numpy as np
import pytest

from spdt.greeks.aad import autocallable_aad_greeks
from spdt.greeks.bump import bump_greeks
from spdt.greeks.likelihood import (
    _autocallable_discounted_payoff,
    lr_autocallable_delta,
    lr_digital_delta,
)
from spdt.pricing.engine import price_mc
from spdt.pricing.models.bs import BlackScholes
from spdt.products.catalog import Autocallable

MODEL = BlackScholes(spot=22_000.0, r=0.065, q=0.013, sigma=0.16)


def _note(knock_in: float = 0.90, coupon_barrier: float = 0.95, autocall: float = 1.02):
    return Autocallable(
        notional=100.0, observation_times=(0.25, 0.5), coupon_rate=0.02,
        autocall_level=autocall, coupon_barrier=coupon_barrier, knock_in=knock_in,
        memory=True, initial_fixing=MODEL.spot,
    )


def test_lr_payoff_engine_reproduces_the_dsl_price():
    """The LR estimator carries its own payoff loop; if it drifts from the DSL, its delta is
    the derivative of a different product."""
    note = _note()
    obs = np.array(note.observation_times)
    z = np.random.default_rng(0).standard_normal((60_000, obs.size))
    dt = np.diff(np.concatenate([[0.0], obs]))
    inc = (MODEL.r - MODEL.q - 0.5 * MODEL.sigma**2) * dt + MODEL.sigma * np.sqrt(dt) * z
    spots = MODEL.spot * np.exp(np.cumsum(inc, axis=1))

    lr_pv = _autocallable_discounted_payoff(note, spots, obs, MODEL.r).mean()
    dsl_pv = price_mc(note, MODEL, n_paths=200_000, seed=0).price
    assert lr_pv == pytest.approx(dsl_pv, rel=5e-3)


def test_lr_and_bump_agree_where_aad_cannot_reach():
    """The headline: two estimators that fail differently now give the same delta."""
    note = _note()
    bump = bump_greeks(note, MODEL, n_paths=200_000).delta
    lr = lr_autocallable_delta(note, MODEL, n_paths=400_000)
    assert lr == pytest.approx(bump, rel=0.10), f"LR {lr} vs bump {bump}"


def test_aad_recovers_only_the_smooth_part():
    """AAD's shortfall is the barrier's Dirac contribution — quantified, not hand-waved."""
    note = _note()
    aad = autocallable_aad_greeks(note, MODEL, n_paths=200_000)["delta"]
    lr = lr_autocallable_delta(note, MODEL, n_paths=400_000)
    assert abs(aad) < abs(lr)  # the adjoint sees strictly less
    dirac_share = 1.0 - abs(aad) / abs(lr)
    assert 0.4 < dirac_share < 0.95  # most of this note's delta lives in the jumps


def test_a_note_with_unreachable_barriers_has_all_three_agree_at_zero():
    """When no barrier is live the payoff is smooth, so AAD, bump and LR must coincide."""
    note = _note(knock_in=0.60, coupon_barrier=0.80, autocall=1.00)
    aad = autocallable_aad_greeks(note, MODEL, n_paths=200_000)["delta"]
    bump = bump_greeks(note, MODEL, n_paths=200_000).delta
    lr = lr_autocallable_delta(note, MODEL, n_paths=400_000)
    for value in (aad, bump, lr):
        assert abs(value) < 1e-3


def test_lr_needs_a_struck_note():
    unstruck = Autocallable(
        notional=100.0, observation_times=(0.25, 0.5), coupon_rate=0.02, initial_fixing=None
    )
    with pytest.raises(ValueError, match="struck"):
        lr_autocallable_delta(unstruck, MODEL)


def test_lr_digital_delta_still_matches_its_closed_form():
    """Regression guard on the pre-existing estimator this one generalises."""
    from math import exp, log, sqrt

    from scipy.stats import norm

    s, k, t = MODEL.spot, MODEL.spot, 1.0
    r, q, sig = MODEL.r, MODEL.q, MODEL.sigma
    d2 = (log(s / k) + (r - q - 0.5 * sig * sig) * t) / (sig * sqrt(t))
    closed = exp(-r * t) * norm.pdf(d2) / (s * sig * sqrt(t))
    got = lr_digital_delta(MODEL, k, t, n_paths=400_000)
    assert got == pytest.approx(closed, rel=0.05)
