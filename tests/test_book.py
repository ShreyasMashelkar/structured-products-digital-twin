"""Virtual book: generation, marking, netting, and the short-vol aggregate (L8)."""

import pytest

from spdt.book import Trade, generate_autocallable_book, mark_book
from spdt.pricing import BlackScholes
from spdt.products import Autocallable

MODEL = BlackScholes(spot=100.0, r=0.03, q=0.0, sigma=0.25)


def test_generator_is_deterministic_and_sized():
    a = generate_autocallable_book(8, initial_fixing=100.0, seed=0)
    b = generate_autocallable_book(8, initial_fixing=100.0, seed=0)
    assert len(a) == 8
    assert [t.trade_id for t in a] == [t.trade_id for t in b]
    assert a[0].product.knock_in == b[0].product.knock_in


def test_book_marks_and_nets():
    trades = generate_autocallable_book(6, initial_fixing=100.0, seed=1)
    book = mark_book(trades, MODEL, n_paths=40_000, seed=2)
    assert len(book.positions) == 6
    # Totals are the sum of the per-trade marks (netting identity).
    assert book.total_pv == pytest.approx(sum(p.pv for p in book.positions))
    assert book.net_greeks.vega == pytest.approx(sum(p.greeks.vega for p in book.positions))


def test_book_of_held_notes_is_short_vol():
    trades = generate_autocallable_book(6, initial_fixing=100.0, seed=1)
    book = mark_book(trades, MODEL, n_paths=80_000, seed=2)
    assert book.net_greeks.vega < 0.0  # autocallable holders are structurally short vol


def test_offsetting_positions_net_down():
    note = Autocallable(
        notional=100.0,
        observation_times=(0.5, 1.0),
        coupon_rate=0.03,
        knock_in=0.6,
        initial_fixing=100.0,
    )
    long_short = [Trade("L", note, direction=1), Trade("S", note, direction=-1)]
    book = mark_book(long_short, MODEL, n_paths=40_000, seed=3)
    assert book.total_pv == pytest.approx(0.0, abs=1e-9)
    assert book.net_greeks.vega == pytest.approx(0.0, abs=1e-9)


def test_concentration_tracks_gamma_by_underlying():
    trades = generate_autocallable_book(4, initial_fixing=100.0, seed=1)
    book = mark_book(trades, MODEL, n_paths=40_000, seed=2)
    assert set(book.concentration_by_underlying()) == {"NIFTY"}
