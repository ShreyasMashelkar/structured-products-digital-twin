"""Chain recorder: capture the live two-sided option chain that bhavcopy never publishes."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from spdt.data.ingest.chain_recorder import (
    ChainRecord,
    in_market_hours,
    read_records,
    record_chain,
    select_chain,
    write_records,
)
from spdt.data.ingest.xts import InstrumentRef, Quote

_TS = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)


def _opt(iid: int, expiry: date, strike: float, kind: str) -> InstrumentRef:
    return InstrumentRef(
        exchange_segment=2, exchange_instrument_id=iid, symbol="NIFTY",
        series="OPTIDX", instrument_type="OPTIDX",
        expiry=expiry, strike=strike, option_type=kind, lot_size=65,
    )


_MASTER = [
    _opt(101, date(2026, 8, 27), 24000.0, "CE"),
    _opt(102, date(2026, 8, 27), 24000.0, "PE"),
    _opt(103, date(2026, 9, 24), 24000.0, "CE"),
    _opt(104, date(2026, 10, 29), 24000.0, "CE"),
    # non-option and foreign-underlying rows the selector must skip
    InstrumentRef(2, 900, symbol="NIFTY", series="FUTIDX", instrument_type="FUTIDX",
                  expiry=date(2026, 8, 27)),
    InstrumentRef(2, 105, symbol="BANKNIFTY", series="OPTIDX", instrument_type="OPTIDX",
                  expiry=date(2026, 8, 27), strike=52000.0, option_type="CE", lot_size=30),
]


class _FakeClient:
    """Returns one quote per requested instrument; records chunk sizes it was asked for."""

    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def quotes(self, instruments, *, now=None, max_age_s=300.0):
        self.batch_sizes.append(len(instruments))
        return [
            Quote(instrument=InstrumentRef(2, ref.exchange_instrument_id),
                  ltp=100.0, bid=99.0, ask=101.0, bid_qty=65.0, ask_qty=130.0,
                  timestamp=_TS, stale=False)
            for ref in instruments
        ]


def test_select_chain_keeps_only_the_underlyings_options() -> None:
    refs = select_chain(_MASTER, underlying="NIFTY", n_expiries=3)
    assert all(r.option_type in ("CE", "PE") for r in refs)
    assert all(r.symbol == "NIFTY" for r in refs)
    assert len(refs) == 4


def test_select_chain_limits_to_nearest_expiries() -> None:
    refs = select_chain(_MASTER, underlying="NIFTY", n_expiries=2)
    assert {r.expiry for r in refs} == {date(2026, 8, 27), date(2026, 9, 24)}


def test_record_chain_captures_the_two_sided_market() -> None:
    refs = select_chain(_MASTER, underlying="NIFTY", n_expiries=2)
    records = record_chain(_FakeClient(), refs)
    assert len(records) == 3
    call = next(r for r in records if r.is_call and r.strike == 24000.0
                and r.expiry == date(2026, 8, 27))
    assert (call.bid, call.ask) == (99.0, 101.0)
    assert call.underlying == "NIFTY"


def test_record_chain_chunks_quote_requests() -> None:
    many = [_opt(200 + i, date(2026, 8, 27), 20000.0 + 50 * i, "CE") for i in range(60)]
    client = _FakeClient()
    record_chain(client, many, batch_size=25)
    assert client.batch_sizes == [25, 25, 10]


def test_stale_quotes_are_flagged_not_dropped() -> None:
    class _StaleClient(_FakeClient):
        def quotes(self, instruments, *, now=None, max_age_s=300.0):
            qs = super().quotes(instruments, now=now, max_age_s=max_age_s)
            return [Quote(**{**q.__dict__, "stale": True}) for q in qs]

    records = record_chain(_StaleClient(), select_chain(_MASTER, "NIFTY", n_expiries=1))
    assert records and all(r.stale for r in records)


def test_records_round_trip_through_parquet(tmp_path: Path) -> None:
    records = [ChainRecord(
        as_of_ts=_TS, underlying="NIFTY", expiry=date(2026, 8, 27), strike=24000.0,
        is_call=True, bid=99.0, ask=101.0, bid_qty=65.0, ask_qty=130.0,
        ltp=100.0, stale=False,
    )]
    path = write_records(records, tmp_path)
    assert path.name == "chain_2026-08-25.parquet"
    back = read_records(tmp_path)
    assert len(back) == 1 and back[0].ask == 101.0 and back[0].expiry == date(2026, 8, 27)


def test_write_appends_within_a_day(tmp_path: Path) -> None:
    rec = ChainRecord(_TS, "NIFTY", date(2026, 8, 27), 24000.0, True,
                      99.0, 101.0, 65.0, 130.0, 100.0, False)
    write_records([rec], tmp_path)
    write_records([rec], tmp_path)
    assert len(read_records(tmp_path)) == 2


def test_market_hours_window_is_ist_weekdays() -> None:
    assert in_market_hours(datetime(2026, 8, 25, 10, 30))    # Tuesday mid-session IST
    assert not in_market_hours(datetime(2026, 8, 25, 8, 0))  # before open
    assert not in_market_hours(datetime(2026, 8, 23, 11, 0))  # Sunday
