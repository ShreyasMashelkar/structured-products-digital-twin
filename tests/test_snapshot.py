"""MarketSnapshot content-addressing: determinism, order-independence, sensitivity."""

from dataclasses import dataclass
from datetime import date
from math import exp

import pytest

from spdt.core.provenance import Provenance
from spdt.core.snapshot import MarketSnapshot
from spdt.core.types import Curve, DividendSchedule, SourceTag, year_fraction

ANCHOR = date(2024, 6, 17)


@dataclass(frozen=True)
class _FakeSurface:
    """Stand-in for a calibrated VolSurface — participates via its content_hash."""

    content_hash: str


def _curve(rate: float) -> Curve:
    pillars = (date(2025, 6, 17), date(2026, 6, 17))
    return Curve(
        anchor=ANCHOR,
        pillars=pillars,
        discount_factors={d: exp(-rate * year_fraction(ANCHOR, d)) for d in pillars},
    )


def _snapshot(*, spot: float = 22000.0, surface_hash: str = "abc", prov_tag=SourceTag.OBSERVED):
    ois = _curve(0.06)
    funding = Curve(anchor=ANCHOR, spread_over=ois, spread_knots={date(2026, 6, 17): 0.012})
    return MarketSnapshot(
        date=ANCHOR,
        spots={"NIFTY": spot},
        ois_curve=ois,
        funding_curve=funding,
        surfaces={"NIFTY": _FakeSurface(surface_hash)},
        dividends={"NIFTY": DividendSchedule(continuous_yield=0.013)},
        provenance=Provenance({"spot.NIFTY": prov_tag}),
    )


def test_hash_is_deterministic():
    assert _snapshot().content_hash == _snapshot().content_hash


def test_short_hash_is_prefix_of_content_hash():
    snap = _snapshot()
    assert snap.content_hash.startswith(snap.short_hash)
    assert len(snap.short_hash) == 16


def test_hash_ignores_spot_dict_ordering():
    ois = _curve(0.06)
    funding = Curve(anchor=ANCHOR, spread_over=ois, spread_knots={date(2026, 6, 17): 0.012})
    common = dict(
        date=ANCHOR,
        ois_curve=ois,
        funding_curve=funding,
        surfaces={},
        dividends={},
        provenance=Provenance({}),
    )
    a = MarketSnapshot(spots={"NIFTY": 1.0, "BANKNIFTY": 2.0}, **common)
    b = MarketSnapshot(spots={"BANKNIFTY": 2.0, "NIFTY": 1.0}, **common)
    assert a.content_hash == b.content_hash


def test_hash_excludes_provenance():
    observed = _snapshot(prov_tag=SourceTag.OBSERVED)
    interpolated = _snapshot(prov_tag=SourceTag.INTERPOLATED)
    assert observed.content_hash == interpolated.content_hash


def test_hash_changes_with_economic_content():
    assert _snapshot(spot=22000.0).content_hash != _snapshot(spot=22001.0).content_hash


def test_hash_tracks_surface_content_hash():
    assert _snapshot(surface_hash="v1").content_hash != _snapshot(surface_hash="v2").content_hash


def test_unhashable_surface_is_rejected():
    snap = MarketSnapshot(
        date=ANCHOR,
        spots={},
        ois_curve=_curve(0.06),
        funding_curve=_curve(0.06),
        surfaces={"NIFTY": object()},  # no content_hash, not a dataclass
        dividends={},
        provenance=Provenance({}),
    )
    with pytest.raises(TypeError, match="canonicalize"):
        _ = snap.content_hash
