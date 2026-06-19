"""Correlation framework: Higham PSD repair, estimators, copulas, worst-of pricing."""

import numpy as np
import pytest

from spdt.corr import (
    gaussian_correlated_normals,
    historical_correlation,
    is_positive_semidefinite,
    nearest_correlation,
)
from spdt.pricing import price_mc, price_worst_of_autocallable
from spdt.pricing.models import BlackScholes
from spdt.products import Autocallable


# --- Higham PSD repair ------------------------------------------------------------------

def test_nearest_correlation_repairs_a_non_psd_matrix():
    # "Everything 0.9" on the off-diagonal is a classic non-PSD stress matrix.
    bad = np.array([[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]])
    assert not is_positive_semidefinite(bad)
    fixed = nearest_correlation(bad)
    assert is_positive_semidefinite(fixed)
    assert np.allclose(np.diag(fixed), 1.0)


def test_nearest_correlation_leaves_a_valid_matrix_essentially_unchanged():
    good = np.array([[1.0, 0.3, 0.2], [0.3, 1.0, 0.25], [0.2, 0.25, 1.0]])
    assert np.allclose(nearest_correlation(good), good, atol=1e-6)


# --- estimators & copula ----------------------------------------------------------------

def test_historical_correlation_recovers_a_planted_correlation():
    rng = np.random.default_rng(0)
    target = np.array([[1.0, 0.6], [0.6, 1.0]])
    chol = np.linalg.cholesky(target)
    returns = rng.standard_normal((20_000, 2)) @ chol.T
    assert historical_correlation(returns)[0, 1] == pytest.approx(0.6, abs=0.03)


def test_gaussian_copula_reproduces_the_target_correlation():
    rng = np.random.default_rng(1)
    corr = np.array([[1.0, -0.4], [-0.4, 1.0]])
    z = gaussian_correlated_normals(corr, 50_000, 1, rng)[:, 0, :]
    assert np.corrcoef(z, rowvar=False)[0, 1] == pytest.approx(-0.4, abs=0.02)


# --- worst-of autocallable --------------------------------------------------------------

def _note():
    return Autocallable(100.0, (0.5, 1.0), coupon_rate=0.04, autocall_level=1.0,
                        coupon_barrier=0.8, knock_in=0.6)


def test_worst_of_is_worth_less_than_the_single_name():
    note = _note()
    single = price_mc(note, BlackScholes(100.0, 0.03, 0.0, 0.25), n_paths=80_000, seed=3).price
    worst = price_worst_of_autocallable(
        note, [100.0, 100.0], [0.25, 0.25], np.array([[1.0, 0.5], [0.5, 1.0]]),
        r=0.03, n_paths=80_000, seed=3,
    ).price
    assert worst < single  # the worst performer drags the basket down


def test_higher_correlation_lifts_the_worst_of_price():
    note = _note()
    spots, vols = [100.0, 100.0], [0.25, 0.25]

    def price(rho):
        corr = np.array([[1.0, rho], [rho, 1.0]])
        return price_worst_of_autocallable(
            note, spots, vols, corr, r=0.03, n_paths=80_000, seed=4
        ).price

    # As ρ → 1 the two names move together, dispersion shrinks, the worst-of improves.
    assert price(0.95) > price(0.2)
