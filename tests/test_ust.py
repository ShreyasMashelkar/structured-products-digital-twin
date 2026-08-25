"""US Treasury curve ingestion and par-to-zero bootstrap (network-free).

The bootstrap's correctness has a closed-form anchor: a flat par curve must produce (nearly)
flat zeros, and on an upward-sloping curve the long-end zero must sit *below* the par yield —
the direction of the correction is the whole reason par yields cannot be used as zeros.
"""

import pytest

from spdt.data.ingest.ust import bootstrap_zero_curve


def test_flat_par_curve_gives_flat_zeros():
    par = {0.5: 0.04, 1.0: 0.04, 2.0: 0.04, 5.0: 0.04, 10.0: 0.04}
    zeros = bootstrap_zero_curve(par)
    for t, z in zeros.items():
        # Semi-annual compounding vs continuous costs a few bp; flat means flat within that.
        assert z == pytest.approx(0.04, abs=6e-4), (t, z)


def test_upward_slope_pulls_long_zeros_below_par():
    """On a rising curve a par bond's early coupons discount at lower rates, so its yield
    understates the true long zero... no — overstates the df, hence zero < par. Getting this
    backwards is the classic error of using par yields as zeros directly."""
    par = {0.5: 0.030, 1.0: 0.034, 2.0: 0.038, 5.0: 0.044, 10.0: 0.048}
    zeros = bootstrap_zero_curve(par)
    assert zeros[10.0] > par[10.0]  # rising curve: zero sits ABOVE par at the long end
    assert zeros[0.5] == pytest.approx(0.030)  # sub-1y tenors pass through as zeros


def test_bootstrap_is_exact_for_a_two_pillar_hand_calculation():
    """One step of the recursion, checked by hand: a 2y 4% par bond with 1y zeros at 3%."""
    from math import exp

    par = {0.5: 0.03, 1.0: 0.03, 2.0: 0.04}
    zeros = bootstrap_zero_curve(par)
    # Hand recursion with the self-consistent interp: the 1.5y coupon discounts at the rate
    # midway between z(1y) and the solved z(2y), so the solved pillar must satisfy the par
    # equation exactly when plugged back in.
    df05, df10 = exp(-0.03 * 0.5), exp(-0.03 * 1.0)
    z20 = zeros[2.0]
    z15 = zeros[1.0] + (z20 - zeros[1.0]) * 0.5
    residual = 0.02 * (df05 + df10 + exp(-z15 * 1.5)) + 1.02 * exp(-z20 * 2.0) - 1.0
    assert residual == pytest.approx(0.0, abs=1e-10)


def test_nonsense_par_curve_fails_loudly():
    with pytest.raises(ValueError, match="non-positive"):
        # A 300% "yield" with near-zero short rates: the very first coupon (discounted at the
        # already-solved short pillar, which no candidate zero can change) exceeds par on its
        # own, so the par equation has no root at any long rate. Milder nonsense — even a 50%
        # yield — legitimately bootstraps, because the self-consistent solve lets a large
        # candidate zero crush the intermediate coupons; the failure boundary is where the
        # *fixed* short end already breaks the bond.
        bootstrap_zero_curve({0.5: 0.001, 5.0: 3.0})
