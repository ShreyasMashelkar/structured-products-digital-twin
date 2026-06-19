"""End-to-end L1 slice: synthetic source → snapshot → IV recovery → store round-trip."""

from datetime import date

import pytest

from spdt.core.types import SourceTag
from spdt.data import build_snapshot, load_snapshot, save_snapshot
from spdt.data.curate import invert_chain
from spdt.data.ingest.synthetic import SyntheticSource, _smile_vol
from spdt.data.store import load_iv_points, save_iv_points

AS_OF = date(2024, 6, 17)


@pytest.fixture
def raw():
    return SyntheticSource().fetch(AS_OF, "NIFTY")


# --- synthetic source -----------------------------------------------------------------

def test_synthetic_source_is_deterministic(raw):
    again = SyntheticSource().fetch(AS_OF, "NIFTY")
    assert [q.settlement_price for q in raw.option_chain] == [
        q.settlement_price for q in again.option_chain
    ]


def test_synthetic_data_is_tagged_synthetic(raw):
    assert raw.source is SourceTag.SYNTHETIC
    assert raw.spot == 22000.0
    assert len(raw.option_chain) == 3 * 5 * 2  # 3 expiries × 5 strikes × {call, put}


# --- snapshot builder -----------------------------------------------------------------

def test_builder_recovers_input_zero_rates(raw):
    snap = build_snapshot(raw)
    for pillar, z in raw.ois_zero_rates.items():
        assert snap.ois_curve.zero_rate(pillar) == pytest.approx(z, abs=1e-12)


def test_funding_curve_sits_above_ois(raw):
    snap = build_snapshot(raw)
    pillar = max(raw.ois_zero_rates)
    assert snap.funding_curve.zero_rate(pillar) > snap.ois_curve.zero_rate(pillar)


def test_builder_is_single_underlying_with_empty_surface(raw):
    snap = build_snapshot(raw)
    assert set(snap.spots) == {"NIFTY"}
    assert snap.correlation is None
    assert snap.surfaces == {}
    assert snap.provenance.summary() == {SourceTag.SYNTHETIC: 1.0}


# --- IV inversion recovers the smile that priced the chain ----------------------------

def test_inversion_recovers_the_synthetic_smile(raw):
    snap = build_snapshot(raw)
    points = invert_chain(raw, snap.ois_curve)
    assert len(points) == len(raw.option_chain)
    for p in points:
        assert p.implied_vol == pytest.approx(_smile_vol(p.log_moneyness), abs=1e-6)


# --- store round-trips and verifies the content hash ----------------------------------

def test_snapshot_store_round_trip(raw, tmp_path):
    snap = build_snapshot(raw)
    path = save_snapshot(snap, tmp_path)
    assert snap.short_hash in path.name

    reloaded = load_snapshot(path)
    assert reloaded.content_hash == snap.content_hash


def test_load_rejects_tampered_hash(raw, tmp_path):
    snap = build_snapshot(raw)
    path = save_snapshot(snap, tmp_path)
    tampered = path.with_name("snapshot-deadbeefdeadbeef.json")
    path.rename(tampered)
    with pytest.raises(ValueError, match="content hash mismatch"):
        load_snapshot(tampered)


def test_iv_points_parquet_round_trip(raw, tmp_path):
    snap = build_snapshot(raw)
    points = invert_chain(raw, snap.ois_curve)
    path = save_iv_points(points, "NIFTY", AS_OF, tmp_path)
    reloaded = load_iv_points(path)
    assert len(reloaded) == len(points)
    assert [round(p.implied_vol, 9) for p in reloaded] == [
        round(p.implied_vol, 9) for p in points
    ]
