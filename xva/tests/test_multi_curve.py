import pytest
from src.curves.multi_curve import MultiCurveFramework


def test_multi_curve_builds_and_prices():
    # Will use real data or fallback
    mc = MultiCurveFramework.build_from_market_data()
    assert mc.basis_bps is not None
    assert mc.discount.df(1.0) <= 1.0

    # Forward rate should be higher than OIS spot if basis is positive
    fwd = mc.forward_rate(1.0, 2.0)
    assert fwd > 0.0
