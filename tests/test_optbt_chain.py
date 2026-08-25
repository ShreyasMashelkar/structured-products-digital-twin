"""Chain snapshot: immutable, content-hashed, and honest about what actually traded."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from spdt.optbt.chain import OptionChainSnapshot, OptionKey, OptionQuoteView


def _view(strike: float, is_call: bool, traded: bool = True) -> OptionQuoteView:
    key = OptionKey("NIFTY", date(2026, 9, 24), strike, is_call)
    return OptionQuoteView(
        key=key, settlement_price=100.0, contracts_traded=10.0 if traded else 0.0,
        open_interest=500.0 if traded else 0.0, bid=None, ask=None, traded=traded,
        mark=100.0, mark_provenance="settlement", implied_vol=None,
    )


def _snapshot(views: list[OptionQuoteView]) -> OptionChainSnapshot:
    return OptionChainSnapshot(
        as_of=date(2026, 8, 25), underlying="NIFTY", spot=24000.0,
        quotes={v.key: v for v in views}, surface=None, ois_curve=None,
        dividend_yield=0.012,
    )


def test_traded_fraction_is_computed_from_the_quotes() -> None:
    snap = _snapshot([_view(24000, True), _view(24100, True, traded=False)])
    assert snap.traded_fraction == pytest.approx(0.5)


def test_traded_fraction_of_an_empty_chain_is_zero() -> None:
    assert _snapshot([]).traded_fraction == 0.0


def test_strikes_for_expiry_are_sorted_and_deduplicated() -> None:
    snap = _snapshot([_view(24100, True), _view(24000, True), _view(24000, False)])
    assert snap.strikes_for(date(2026, 9, 24)) == [24000.0, 24100.0]
    assert snap.strikes_for(date(2026, 10, 29)) == []


def test_get_returns_none_for_unlisted_contracts() -> None:
    snap = _snapshot([_view(24000, True)])
    assert snap.get(OptionKey("NIFTY", date(2026, 9, 24), 24000.0, True)) is not None
    assert snap.get(OptionKey("NIFTY", date(2026, 9, 24), 99999.0, True)) is None


def test_quotes_mapping_is_immutable() -> None:
    snap = _snapshot([_view(24000, True)])
    with pytest.raises(TypeError):
        snap.quotes[OptionKey("NIFTY", date(2026, 9, 24), 1.0, True)] = _view(1.0, True)  # type: ignore[index]


def test_content_hash_is_stable_and_insertion_order_independent() -> None:
    a = _snapshot([_view(24000, True), _view(24100, True)])
    b = _snapshot([_view(24100, True), _view(24000, True)])
    assert a.content_hash == b.content_hash


def test_content_hash_changes_when_a_mark_changes() -> None:
    v = _view(24000, True)
    assert (_snapshot([v]).content_hash
            != _snapshot([replace(v, mark=101.0)]).content_hash)


def test_content_hash_changes_when_provenance_changes() -> None:
    v = _view(24000, True)
    assert (_snapshot([v]).content_hash
            != _snapshot([replace(v, mark_provenance="surface")]).content_hash)
