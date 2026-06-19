"""Bootstrapping the OIS/risk-free curve from T-bill and OIS quotes (FBIL)."""

from datetime import date, timedelta

import pytest

from spdt.core.types import year_fraction
from spdt.data import build_snapshot
from spdt.data.curate.rate_bootstrap import (
    RateInstrument,
    bootstrap_discount_factors,
    bootstrap_ois_curve,
    bootstrap_zero_rates,
)
from spdt.data.ingest.fbil import fbil_instruments
from spdt.data.ingest.nse_bhavcopy import parse_fo_bhavcopy
from tests.test_nse_bhavcopy import _sample_bhavcopy

ANCHOR = date(2024, 6, 17)


def _instruments():
    return fbil_instruments(
        ANCHOR,
        tbill_yields={91: 0.0660, 182: 0.0665, 364: 0.0670},
        ois_par_rates={1: 0.0670, 2: 0.0685, 3: 0.0695, 5: 0.0710},
    )


def test_tbill_discount_factor_is_simple_interest():
    insts = [RateInstrument(ANCHOR + timedelta(days=91), 0.066, kind="zero")]
    dfs = bootstrap_discount_factors(ANCHOR, insts)
    tau = year_fraction(ANCHOR, ANCHOR + timedelta(days=91))
    assert dfs[ANCHOR + timedelta(days=91)] == pytest.approx(1.0 / (1.0 + 0.066 * tau))


def test_each_ois_reprices_to_par():
    insts = _instruments()
    discount = bootstrap_discount_factors(ANCHOR, insts)
    ois = sorted((i for i in insts if i.kind == "ois"), key=lambda x: x.maturity)
    coupon_dates = [i.maturity for i in ois]
    for n, inst in enumerate(ois):
        # Fixed leg S·Σ τ_i D(t_i) must equal the floating leg 1 − D(T).
        annuity, last = 0.0, ANCHOR
        for cd in coupon_dates[: n + 1]:
            annuity += year_fraction(last, cd) * discount[cd]
            last = cd
        assert inst.rate * annuity == pytest.approx(1.0 - discount[inst.maturity], abs=1e-12)


def test_discount_factors_decrease_with_maturity():
    discount = bootstrap_discount_factors(ANCHOR, _instruments())
    dfs = [discount[m] for m in sorted(discount)]
    assert all(b < a for a, b in zip(dfs, dfs[1:]))


def test_bootstrapped_curve_is_upward_sloping_here():
    curve = bootstrap_ois_curve(ANCHOR, _instruments())
    z1 = curve.zero_rate(ANCHOR + timedelta(days=364))
    z5 = curve.zero_rate(ANCHOR + timedelta(days=365 * 5))
    assert 0.06 < z1 < z5 < 0.08  # rising par rates ⇒ rising zero curve


def test_flat_ois_gives_a_flat_zero_curve():
    flat = fbil_instruments(ANCHOR, tbill_yields={}, ois_par_rates={1: 0.07, 2: 0.07, 3: 0.07})
    zeros = list(bootstrap_zero_rates(ANCHOR, flat).values())
    # A flat *par* curve bootstraps to a flat *continuously-compounded* zero curve, sitting a
    # touch below the par rate (the annual-vs-continuous compounding gap).
    assert max(zeros) - min(zeros) < 1e-3
    assert all(0.066 < z < 0.07 for z in zeros)


def test_snapshot_uses_the_bootstrapped_curve():
    raw = parse_fo_bhavcopy(
        _sample_bhavcopy(), date(2024, 6, 17), "NIFTY",
        risk_free_rate=0.065, funding_spread=0.012, dividend_yield=0.013,
        rate_instruments=_instruments(),
    )
    snap = build_snapshot(raw)
    # The OIS curve now carries the bootstrapped term structure, not a single flat rate.
    z1 = snap.ois_curve.zero_rate(ANCHOR + timedelta(days=364))
    z5 = snap.ois_curve.zero_rate(ANCHOR + timedelta(days=365 * 5))
    assert z5 > z1
    assert snap.funding_curve.zero_rate(ANCHOR + timedelta(days=364)) > z1  # funding > OIS
