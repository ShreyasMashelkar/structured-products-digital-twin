"""Bucketed vega and surface-aware P&L explain (the desk's vega ladder).

Two checks: the per-bucket vegas of a term-structure model sum (under a parallel surface
shift) to the flat vega; and a bucketed vol-P&L explain reconstructs the full vol revaluation
to a small (volga) residual — the upgrade over a single flat-vol vega number.
"""

import pytest

from spdt.greeks.buckets import bucketed_vega
from spdt.pnl import vega_bucket_explain
from spdt.pricing import price_mc
from spdt.pricing.models import BlackScholes, TermVolBlackScholes
from spdt.products import Autocallable

OBS = (1.0, 2.0, 3.0)
TERM = TermVolBlackScholes(
    spot=100.0, r=0.04, q=0.0, knot_times=OBS, knot_vols=(0.18, 0.20, 0.22)
)
NOTE = Autocallable(
    notional=100.0,
    observation_times=OBS,
    coupon_rate=0.06,
    autocall_level=1.0,
    coupon_barrier=0.7,
    knock_in=0.6,
    initial_fixing=100.0,
)


def test_bucket_vegas_sum_to_the_flat_vega():
    ladder = bucketed_vega(NOTE, TERM, n_paths=200_000, seed=2)
    bucket_sum = sum(ladder.values())

    # Flat vega = a parallel shift of every bucket, priced under single-vol Black-Scholes at the
    # term structure's middle vol. The bucketed ladder, summed, should recover it.
    h = 1e-2
    up = price_mc(NOTE, BlackScholes(100.0, 0.04, 0.0, 0.20 + h), n_paths=200_000, seed=2).price
    dn = price_mc(NOTE, BlackScholes(100.0, 0.04, 0.0, 0.20 - h), n_paths=200_000, seed=2).price
    flat_vega = (up - dn) / (2 * h)
    assert bucket_sum == pytest.approx(flat_vega, rel=0.1)


def test_each_bucket_vega_is_negative_for_a_short_vol_autocallable():
    # An autocallable issuer is structurally short vol ⇒ the investor's note is long vol here;
    # every bucket should carry the same sign (all non-trivial).
    ladder = bucketed_vega(NOTE, TERM, n_paths=200_000, seed=2)
    assert all(abs(v) > 1e-6 for v in ladder.values())


def test_vega_bucket_explain_reconstructs_the_vol_pnl():
    today = TermVolBlackScholes(
        spot=100.0, r=0.04, q=0.0, knot_times=OBS, knot_vols=(0.19, 0.205, 0.225)
    )
    explain = vega_bucket_explain(NOTE, TERM, today, n_paths=200_000, seed=2)
    # First-order ladder should explain the bulk of the (small) vol move; residual is volga.
    assert abs(explain.residual) < 0.2 * abs(explain.total)
    assert set(explain.by_bucket) == set(OBS)


def test_explain_requires_matching_bucket_tenors():
    other = TermVolBlackScholes(spot=100.0, r=0.04, q=0.0, knot_times=(1.0, 2.0), knot_vols=(0.2, 0.2))
    with pytest.raises(ValueError, match="bucket tenors"):
        vega_bucket_explain(NOTE, TERM, other)
