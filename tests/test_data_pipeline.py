"""End-to-end L1 slice: synthetic source → snapshot → IV recovery → store round-trip."""

from datetime import date

import pytest

from spdt.core.types import SourceTag
from spdt.data import build_snapshot, load_snapshot, save_snapshot
from spdt.data.curate import invert_chain
from spdt.data.ingest.bloomberg_rates_overlay import BloombergRatesOverlaySource
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
    assert raw.spot == 24100.0
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


def test_bloomberg_mifor_overlay_does_not_replace_ois_curve(raw, tmp_path):
    # The Bloomberg overlay is an optional source and openpyxl its optional reader; the
    # production code raises a clear error without it, and this test should skip on the same
    # boundary rather than hard-fail an environment that never installed the extra.
    Workbook = pytest.importorskip("openpyxl").Workbook

    wb = Workbook()
    ws = wb.active
    ws["A1"] = "Modified Mifor curve"
    ws.append(["Term", "Unit", "Final Mid", "Rate Type"])
    ws.append([0, "DY", 96.0, "FX Spot"])
    ws.append([2, "YR", 7.50, "Swap"])
    ws.append([5, "YR", 7.80, "Swap"])
    path = tmp_path / "bbg.xlsx"
    wb.save(path)

    overlaid = BloombergRatesOverlaySource(SyntheticSource(), path).fetch(AS_OF, "NIFTY")

    assert overlaid.source is SourceTag.SYNTHETIC
    assert overlaid.ois_zero_rates == raw.ois_zero_rates
    assert max(overlaid.funding_spread_knots.values()) > 0.0


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


# --- touchline liquidity screens (for feeds with no volume or open interest) -----------


def test_two_sided_and_spread_screens_drop_placeholder_quotes(raw):
    """The XTS broker feed publishes no volume or open interest, so a two-sided touchline with
    a sane spread is the only liquidity evidence it offers. Without it the live NIFTY surface
    was fitted to minimum-tick far wings that inverted to 50%+ vol against a 9.6% ATM."""
    from dataclasses import replace

    snap = build_snapshot(raw)
    chain = list(raw.option_chain)
    # Give every contract a tight two-sided market, then spoil two of them.
    priced = [
        replace(q, bid=q.settlement_price * 0.99, ask=q.settlement_price * 1.01)
        for q in chain
    ]
    priced[0] = replace(priced[0], bid=None, ask=None)          # one-sided
    priced[1] = replace(priced[1], bid=0.05, ask=0.60)          # 169%-of-mid spread
    screened_raw = replace(raw, option_chain=tuple(priced))

    kept_all = invert_chain(screened_raw, snap.ois_curve)
    kept = invert_chain(
        screened_raw, snap.ois_curve, require_two_sided=True, max_relative_spread=0.60
    )
    assert len(kept) == len(kept_all) - 2

    # And the screens are opt-in: a settlement feed with no bid/ask at all is untouched by
    # default, or it would discard every quote it has.
    assert len(invert_chain(raw, snap.ois_curve)) == len(raw.option_chain)


def test_expiry_selection_keeps_the_long_end_a_note_is_priced_against():
    """The desk kept the nearest N liquid expiries. On SPX the nearest six span seventeen days
    out of a chain quoting to five years, so the surface stopped short of every note it was
    used to price -- while the market panel, using a term-spanning selector, showed 4.3 years
    off the same chain."""
    from datetime import timedelta

    from spdt.data.curate.expiries import select_term_spanning_expiries

    as_of = date(2026, 8, 28)
    # An SPX-shaped ladder: dense weeklies up front, LEAPS at the back.
    expiries = [as_of + timedelta(days=d) for d in
                (11, 17, 21, 28, 34, 45, 68, 125, 203, 306, 476, 1575)]

    nearest = sorted(expiries)[:6]
    assert (nearest[-1] - as_of).days == 45  # the old rule: six weeks of a five-year chain

    spread = select_term_spanning_expiries(expiries, as_of, 6)
    assert (spread[-1] - as_of).days > 365 * 2
    assert (spread[0] - as_of).days <= 21  # the front is still represented
