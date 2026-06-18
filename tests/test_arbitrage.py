"""Butterfly (Durrleman) and calendar arbitrage checks."""

import numpy as np

from spdt.vol.arbitrage import check_butterfly, check_calendar, check_slices, durrleman_g
from spdt.vol.svi import SVIParams

# A mild, well-behaved smile — should be butterfly-arbitrage-free.
GOOD = SVIParams(a=0.04, b=0.4, rho=-0.3, m=0.0, sigma=0.15)
# Steep wings with a sharp kink (large b, tiny sigma, strong skew) — induces a negative density.
BAD = SVIParams(a=0.04, b=2.0, rho=-0.95, m=0.0, sigma=0.01)


def test_good_slice_is_butterfly_arbitrage_free():
    ok, min_g = check_butterfly(GOOD)
    assert ok
    assert min_g > 0


def test_bad_slice_has_negative_durrleman_g():
    ok, min_g = check_butterfly(BAD)
    assert not ok
    assert min_g < 0
    assert np.any(durrleman_g(BAD, np.linspace(-1.5, 1.5, 301)) < 0)


def test_calendar_ok_when_total_variance_increases_in_maturity():
    near = SVIParams(a=0.02, b=0.3, rho=-0.2, m=0.0, sigma=0.15)
    far = SVIParams(a=0.05, b=0.4, rho=-0.2, m=0.0, sigma=0.15)  # higher level everywhere
    assert check_calendar([near, far])
    assert not check_calendar([far, near])  # decreasing in maturity ⇒ calendar arb


def test_check_slices_summarises():
    report = check_slices([GOOD, SVIParams(a=0.06, b=0.4, rho=-0.3, m=0.0, sigma=0.15)])
    assert report.n_slices == 2
    assert report.is_clean


def test_empty_surface_is_trivially_clean():
    assert check_slices([]).is_clean
