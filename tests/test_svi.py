"""Raw SVI: total-variance shape and least-squares calibration recovery."""

import numpy as np
import pytest

from spdt.vol.svi import SVIParams, calibrate_svi, total_variance_from_iv

TRUE = SVIParams(a=0.04, b=0.4, rho=-0.3, m=0.02, sigma=0.15)
GRID = np.linspace(-0.6, 0.6, 13)


def test_total_variance_is_positive_under_sane_params():
    assert np.all(np.asarray(TRUE.total_variance(GRID)) > 0)


def test_scalar_and_array_agree():
    assert TRUE.total_variance(0.1) == pytest.approx(float(TRUE.total_variance(np.array([0.1]))[0]))


def test_derivatives_match_finite_difference():
    h = 1e-5
    w, w1, w2 = TRUE.derivatives(GRID)
    w_up = np.asarray(TRUE.total_variance(GRID + h))
    w_dn = np.asarray(TRUE.total_variance(GRID - h))
    fd1 = (w_up - w_dn) / (2 * h)
    assert np.allclose(w1, fd1, atol=1e-6)
    assert np.all(w2 > 0)  # SVI is convex in k: w'' = b·σ²/r³ > 0


def test_calibration_recovers_the_generating_surface():
    w = np.asarray(TRUE.total_variance(GRID))
    fit = calibrate_svi(GRID, w)
    # Params need not be unique, but the fitted total-variance curve must match.
    assert np.allclose(np.asarray(fit.total_variance(GRID)), w, atol=1e-6)


def test_total_variance_from_iv():
    assert total_variance_from_iv(0.2, 0.25) == pytest.approx(0.2 * 0.2 * 0.25)


def test_too_few_points_is_rejected():
    with pytest.raises(ValueError, match="at least 5"):
        calibrate_svi(np.array([0.0, 0.1]), np.array([0.04, 0.05]))
