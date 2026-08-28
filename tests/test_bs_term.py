"""Black-Scholes with a volatility term structure.

The desk calibrated a real term structure and then priced every note off a single scalar vol,
so a 3-month and a 1.5-year note saw the same volatility. These tests pin the two properties
that make the replacement safe: it reduces exactly to the flat model when the curve is flat,
and its integrated variance matches the surface it was built from.
"""

import numpy as np
import pytest

from spdt.pricing import BlackScholes, price_mc
from spdt.pricing.models.bs_term import BlackScholesTermVol
from spdt.products import Autocallable

SPOT, R, Q = 24100.0, 0.053, 0.013
OBS = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5)


def _note(coupon: float = 0.02) -> Autocallable:
    return Autocallable(100.0, OBS, coupon, 1.0, 0.8, 0.8, True, initial_fixing=SPOT)


def test_a_flat_term_structure_is_exactly_black_scholes():
    """The safety property: wherever the curve is flat the new model must not move a price."""
    sigma = 0.0975
    flat = BlackScholes(spot=SPOT, r=R, q=Q, sigma=sigma)
    term = BlackScholesTermVol(
        spot=SPOT, r=R, q=Q, pillars=((0.08, sigma), (0.5, sigma), (2.0, sigma))
    )
    times = np.array([0.0, 0.25, 0.75, 1.5])
    rng = np.random.default_rng(3)
    normals = rng.standard_normal((5_000, times.size - 1))
    assert np.allclose(flat.simulate(times, normals), term.simulate(times, normals))
    assert price_mc(_note(), term, n_paths=20_000, seed=4).price == pytest.approx(
        price_mc(_note(), flat, n_paths=20_000, seed=4).price
    )


def test_a_single_pillar_reduces_to_the_flat_model():
    sigma = 0.12
    term = BlackScholesTermVol(spot=SPOT, r=R, q=Q, pillars=((0.5, sigma),))
    for t in (0.1, 0.5, 3.0):
        assert term.atm_vol(t) == pytest.approx(sigma)


def test_integrated_variance_matches_the_surface_at_every_pillar():
    """What 'respects the term structure' means operationally: the vol quoted for maturity T is
    the surface's vol at T, not the vol at some other tenor."""
    pillars = ((0.03, 0.0957), (0.0685, 0.0985), (0.1644, 0.0987), (0.337, 0.1080),
               (0.8356, 0.1280))
    term = BlackScholesTermVol(spot=SPOT, r=R, q=Q, pillars=pillars)
    for tau, vol in pillars:
        assert term.atm_vol(tau) == pytest.approx(vol, abs=1e-9)
        assert term.total_variance(tau) == pytest.approx(vol * vol * tau)


def test_vol_is_held_flat_past_the_last_pillar_not_variance():
    """The surface extrapolates flat in total variance, which implies sigma ~ 1/sqrt(tau) --
    vol *decaying* with maturity. From a 60-day pillar that prices a 1.5y note at ~3.2%."""
    term = BlackScholesTermVol(spot=SPOT, r=R, q=Q, pillars=((0.0685, 0.0985), (0.1644, 0.0975)))
    last_vol = 0.0975
    for t in (0.5, 1.5, 3.0):
        assert term.atm_vol(t) == pytest.approx(last_vol)
        flat_variance_vol = (last_vol**2 * 0.1644 / t) ** 0.5
        assert term.atm_vol(t) > flat_variance_vol  # strictly better than the surface's rule
    assert (last_vol**2 * 0.1644 / 1.5) ** 0.5 < 0.04  # the 3.2% the module docstring cites


def test_an_upward_sloping_curve_raises_the_coupon_a_long_note_affords():
    """The economic point. A note maturing past the front month is short volatility through
    its barrier; using the front-month vol for it understates what the market pays."""
    from spdt.structurer.solver import par_target, solve_to_par

    front_only = BlackScholes(spot=SPOT, r=R, q=Q, sigma=0.0975)
    sloped = BlackScholesTermVol(
        spot=SPOT, r=R, q=Q,
        pillars=((0.0685, 0.0985), (0.1644, 0.0975), (0.337, 0.1080), (0.8356, 0.1280)),
    )
    assert sloped.atm_vol(1.5) > front_only.sigma

    def coupon(model) -> float:
        return solve_to_par(
            lambda c: price_mc(_note(c), model, n_paths=40_000, seed=9).price,
            par_target(100.0, fee=1.0), (0.0, 0.30),
        ).param * 4

    assert coupon(sloped) > coupon(front_only)


def test_rejects_a_malformed_term_structure():
    for bad in (
        (),                                    # no pillars
        ((0.0, 0.10),),                        # non-positive maturity
        ((0.5, 0.10), (0.2, 0.11)),            # not ascending
        ((0.2, 0.10), (0.2, 0.11)),            # duplicate maturity
        ((0.2, 0.0),),                         # non-positive vol
    ):
        with pytest.raises(ValueError):
            BlackScholesTermVol(spot=SPOT, r=R, q=Q, pillars=bad)


def test_forward_variance_never_goes_negative_on_an_inverted_curve():
    """A calendar-arbitrageable curve must degrade to a zero-vol step, not a NaN."""
    term = BlackScholesTermVol(spot=SPOT, r=R, q=Q, pillars=((0.5, 0.30), (1.0, 0.10)))
    times = np.array([0.0, 0.5, 1.0])
    normals = np.random.default_rng(0).standard_normal((100, 2))
    spots = term.simulate(times, normals)
    assert np.isfinite(spots).all() and (spots > 0).all()
