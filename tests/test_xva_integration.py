"""Milestone M1 — the curve join (ADR-0007, Phase 2).

Proof that the two codebases share one curve: a single bootstrapped SPDT ``Curve`` is adapted to
XVA's ``OISCurve`` interface, its discount factors match the source to 1e-8, and it drives XVA's
``CVAEngine`` end-to-end with sane economics (CVA ≥ 0, → 0 as the counterparty spread → 0, and
monotone in spread). If this passes, SPDT's curve provably feeds the XVA stack.
"""

from datetime import date, timedelta
from math import exp

import numpy as np
import pytest

import integration  # noqa: F401 — import side-effect: puts xva/ on sys.path
from integration import SpdtCurveAsOIS
from spdt.core.types import Curve, year_fraction
from src.xva.cva import CVAEngine, CreditCurve  # type: ignore  # resolved via integration


def _spdt_ois_curve(flat_rate: float = 0.06) -> Curve:
    anchor = date(2026, 1, 1)
    taus = [0.5, 1.0, 2.0, 3.0, 5.0]
    pillars = tuple(anchor + timedelta(days=round(365 * t)) for t in taus)
    dfs = {p: exp(-flat_rate * year_fraction(anchor, p)) for p in pillars}
    return Curve(anchor=anchor, pillars=pillars, discount_factors=dfs)


def test_adapter_discount_factors_match_the_source_spdt_curve():
    curve = _spdt_ois_curve()
    ois = SpdtCurveAsOIS(curve)
    for t in (0.25, 0.5, 1.0, 2.5, 4.0, 5.0):
        assert ois.df(t) == pytest.approx(curve.df(t), abs=1e-8)
    # The pillar tenors/rates XVA's IR01 path reads off are exposed and consistent.
    assert ois.tenors.shape == (5,)
    assert ois.rates == pytest.approx(0.06, abs=1e-6)


def test_spdt_curve_drives_xva_cva_engine():
    ois = SpdtCurveAsOIS(_spdt_ois_curve())
    engine = CVAEngine(ois)  # XVA engine consuming a SPDT-sourced curve
    time_grid = np.linspace(0.0, 5.0, 21)
    ee = 100.0 * np.exp(-0.3 * time_grid)  # a decaying expected-exposure profile

    cva = engine.compute_cva(ee, time_grid, CreditCurve(cds_spread_bps=200.0, recovery_rate=0.40))
    assert np.isfinite(cva) and cva > 0.0


def test_cva_vanishes_with_credit_spread_and_is_monotone():
    ois = SpdtCurveAsOIS(_spdt_ois_curve())
    engine = CVAEngine(ois)
    time_grid = np.linspace(0.0, 5.0, 21)
    ee = 100.0 * np.exp(-0.3 * time_grid)

    near_zero = engine.compute_cva(ee, time_grid, CreditCurve(cds_spread_bps=1e-6, recovery_rate=0.40))
    mid = engine.compute_cva(ee, time_grid, CreditCurve(cds_spread_bps=200.0, recovery_rate=0.40))
    wide = engine.compute_cva(ee, time_grid, CreditCurve(cds_spread_bps=600.0, recovery_rate=0.40))
    assert near_zero == pytest.approx(0.0, abs=1e-3)
    assert wide > mid > near_zero  # CVA grows monotonically with counterparty spread
