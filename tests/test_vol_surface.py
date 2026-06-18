"""VolSurface end-to-end: calibrate to L1 synthetic IV points, query, hash, persist."""

from datetime import date
from math import log

import pytest

from spdt.data import build_snapshot, load_snapshot, save_snapshot
from spdt.data.curate import invert_chain
from spdt.data.ingest.synthetic import SyntheticSource, _smile_vol
from spdt.vol import VolSurface, with_surfaces

AS_OF = date(2024, 6, 17)


@pytest.fixture
def surface_and_snapshot():
    raw = SyntheticSource().fetch(AS_OF, "NIFTY")
    snap = build_snapshot(raw)
    points = invert_chain(raw, snap.ois_curve)
    surface = VolSurface.calibrate(points, "NIFTY")
    return surface, snap


def test_calibration_recovers_the_synthetic_smile(surface_and_snapshot):
    surface, _ = surface_and_snapshot
    raw = SyntheticSource().fetch(AS_OF, "NIFTY")
    for q in raw.option_chain:
        recovered = surface.implied_vol(q.strike, q.expiry)
        k = log(q.strike / surface.forwards[q.expiry])
        assert recovered == pytest.approx(_smile_vol(k), abs=2e-3)


def test_surface_is_arbitrage_free(surface_and_snapshot):
    surface, _ = surface_and_snapshot
    assert surface.arb_status.is_clean
    assert len(surface.slices) == 3  # three synthetic expiries


def test_cross_tenor_interpolation_is_monotone(surface_and_snapshot):
    surface, _ = surface_and_snapshot
    taus = sorted(surface.taus.values())
    mid = 0.5 * (taus[0] + taus[1])
    w_near = surface.total_variance(0.0, taus[0])
    w_mid = surface.total_variance(0.0, mid)
    w_far = surface.total_variance(0.0, taus[1])
    assert w_near <= w_mid <= w_far


def test_content_hash_is_deterministic_and_serialisation_round_trips(surface_and_snapshot):
    surface, _ = surface_and_snapshot
    assert surface.content_hash == VolSurface.from_dict(surface.to_dict()).content_hash


def test_attaching_surface_changes_snapshot_hash(surface_and_snapshot):
    surface, snap = surface_and_snapshot
    with_surf = with_surfaces(snap, {"NIFTY": surface})
    assert with_surf.content_hash != snap.content_hash


def test_snapshot_with_surface_store_round_trip(surface_and_snapshot, tmp_path):
    surface, snap = surface_and_snapshot
    with_surf = with_surfaces(snap, {"NIFTY": surface})
    path = save_snapshot(with_surf, tmp_path)
    reloaded = load_snapshot(path)
    assert reloaded.content_hash == with_surf.content_hash
    assert len(reloaded.surfaces["NIFTY"].slices) == 3
