"""Tests for the XTS (Symphony) market-data adapter — parsing is pure, HTTP is mocked.

Live XTS access needs broker credentials, so CI tests parse/normalize on fixtures shaped
like the XTS REST API and stubs ``XTSMarketDataClient._request`` (no network, no secrets).
"""

import json
from datetime import date, datetime

import pytest

from spdt.core.types import SourceTag
from spdt.data.ingest.xts import (
    XTS_EPOCH_OFFSET_S,
    InstrumentRef,
    Quote,
    XTSMarketDataClient,
    XTSSource,
    build_raw_market_data,
    parse_instrument_master,
    parse_touchline,
)
from spdt.data.snapshot_builder import build_snapshot

_NIFTY = InstrumentRef(exchange_segment=1, exchange_instrument_id=26000, symbol="NIFTY 50")
_BANKNIFTY = InstrumentRef(exchange_segment=1, exchange_instrument_id=26001, symbol="NIFTY BANK")
_NOW = datetime(2026, 7, 10, 11, 30, 0)


def _touchline_json(instrument_id=26000, ltp=24000.75, ts=None, bid=24000.5, ask=24001.0,
                    segment=1):
    """One entry of ``result.listQuotes`` — XTS returns each as a JSON *string*.

    ``ts`` is Unix seconds; the wire value uses XTS's 1980-IST epoch.
    """
    unix_ts = ts if ts is not None else int(_NOW.timestamp())
    return json.dumps({
        "MessageCode": 1502,
        "ExchangeSegment": segment,
        "ExchangeInstrumentID": instrument_id,
        "Touchline": {
            "BidInfo": {"Size": 100, "Price": bid},
            "AskInfo": {"Size": 50, "Price": ask},
            "LastTradedPrice": ltp,
            "LastUpdateTime": unix_ts - XTS_EPOCH_OFFSET_S,
        },
    })


def _client(**kw):
    kw.setdefault("base_url", "https://xts.example.com/apimarketdata")
    kw.setdefault("app_key", "APPKEY")
    kw.setdefault("secret", "SEKRIT")
    return XTSMarketDataClient(**kw)


# --- pure parsing -------------------------------------------------------------


def test_parse_touchline_normalizes_quote():
    q = parse_touchline(json.loads(_touchline_json()), now=_NOW)
    assert isinstance(q, Quote)
    assert q.instrument.exchange_instrument_id == 26000
    assert q.ltp == 24000.75 and q.bid == 24000.5 and q.ask == 24001.0
    assert q.bid_qty == 100 and q.ask_qty == 50
    assert q.source == "xts" and q.stale is False


def test_parse_touchline_flags_stale_quote():
    hour_old = int(_NOW.timestamp()) - 3600
    q = parse_touchline(json.loads(_touchline_json(ts=hour_old)), now=_NOW, max_age_s=300)
    assert q.stale is True


def test_parse_touchline_flags_unpriced_quote_as_stale():
    q = parse_touchline(json.loads(_touchline_json(ltp=0.0)), now=_NOW)
    assert q.ltp is None and q.stale is True


def test_parse_touchline_fails_closed_on_missing_or_future_timestamp():
    missing = json.loads(_touchline_json())
    missing["Touchline"].pop("LastUpdateTime")
    assert parse_touchline(missing, now=_NOW).stale is True
    future = int(_NOW.timestamp()) + 3600
    assert parse_touchline(json.loads(_touchline_json(ts=future)), now=_NOW).stale is True


def test_parse_instrument_master_maps_rows():
    text = (
        "NSECM|26000|SPOT|NIFTY 50|NIFTY 50|EQ\n"
        "NSECM|22|EQUITY|ACC|ACC LIMITED|EQ\n"
        "\n"  # blank lines tolerated
    )
    rows = parse_instrument_master(text)
    assert len(rows) == 2
    nifty = rows[0]
    assert nifty.exchange_segment == 1 and nifty.exchange_instrument_id == 26000
    assert nifty.symbol == "NIFTY 50"


def test_instrument_master_skips_bad_rows_with_line_diagnostic():
    malformed = _fo_master_row(1, "", "CE")
    valid = "NSECM|26000|SPOT|NIFTY 50|NIFTY 50|EQ"
    with pytest.warns(RuntimeWarning, match="line 1"):
        rows = parse_instrument_master(f"{malformed}\n{valid}")
    assert [row.exchange_instrument_id for row in rows] == [26000]


# --- client (HTTP mocked) -----------------------------------------------------


def test_login_sends_credentials_and_stores_token(monkeypatch):
    client = _client()
    calls = []

    def fake_request(method, path, body=None):
        calls.append((method, path, body))
        return {"type": "success", "result": {"token": "TOK123", "userID": "U1"}}

    monkeypatch.setattr(client, "_request", fake_request)
    client.login()
    (method, path, body), = calls
    assert path.endswith("/auth/login") and body["appKey"] == "APPKEY"
    assert client.token == "TOK123"


def test_client_reads_credentials_from_environment(monkeypatch):
    monkeypatch.setenv("SPDT_XTS_BASE_URL", "https://env.example.com/apimarketdata")
    monkeypatch.setenv("SPDT_XTS_MARKETDATA_APP_KEY", "ENVKEY")
    monkeypatch.setenv("SPDT_XTS_MARKETDATA_SECRET", "ENVSECRET")
    client = XTSMarketDataClient()
    assert client.base_url == "https://env.example.com/apimarketdata"
    assert client.app_key == "ENVKEY"


def test_login_without_credentials_raises_without_leaking_secret(monkeypatch):
    monkeypatch.delenv("SPDT_XTS_MARKETDATA_APP_KEY", raising=False)
    monkeypatch.delenv("SPDT_XTS_MARKETDATA_SECRET", raising=False)
    client = XTSMarketDataClient(base_url="https://xts.example.com/apimarketdata")
    with pytest.raises(RuntimeError, match="SPDT_XTS_MARKETDATA_APP_KEY"):
        client.login()


def test_quotes_normalizes_and_skips_missing(monkeypatch):
    """Ask for two instruments, broker returns one → one Quote, no invention."""
    client = _client()

    def fake_request(method, path, body=None):
        assert body["xtsMessageCode"] == 1502
        return {"type": "success", "result": {"listQuotes": [_touchline_json()]}}

    monkeypatch.setattr(client, "_request", fake_request)
    client.token = "TOK123"
    quotes = client.quotes([_NIFTY, _BANKNIFTY], now=_NOW)
    assert len(quotes) == 1
    assert quotes[0].instrument.exchange_instrument_id == 26000


def test_quotes_accepts_already_decoded_list_quote(monkeypatch):
    client = _client()
    decoded = json.loads(_touchline_json())
    monkeypatch.setattr(client, "_request", lambda *a, **k: {
        "type": "success", "result": {"listQuotes": [decoded]},
    })
    (quote,) = client.quotes([_NIFTY], now=_NOW)
    assert quote.instrument.exchange_instrument_id == 26000


def _fo_master_row(instrument_id, strike, option_type, expiry="2026-07-30T14:30:00",
                   name="NIFTY"):
    """One NSEFO option master row, columns per the live AC Agarwal layout (see xts.py)."""
    fields = [""] * 23
    fields[0], fields[1], fields[2], fields[3] = "NSEFO", str(instrument_id), "2", name
    fields[4], fields[5] = f"{name} {expiry[:10]} {option_type} {strike}", "OPTIDX"
    fields[16], fields[17], fields[18] = expiry, str(strike), option_type
    return "|".join(fields)


def _fo_future_row(instrument_id, expiry="2026-07-28T14:30:00", name="NIFTY", type_code="1"):
    """One NSEFO futures master row (21 columns; type code 4 = calendar spread)."""
    fields = [""] * 21
    fields[0], fields[1], fields[2], fields[3] = "NSEFO", str(instrument_id), type_code, name
    fields[4], fields[5] = f"{name}FUT", "FUTIDX"
    fields[16] = expiry
    return "|".join(fields)


def _option_ref(instrument_id, strike, option_type, expiry=date(2026, 7, 30)):
    return InstrumentRef(exchange_segment=2, exchange_instrument_id=instrument_id,
                         symbol="NIFTY", expiry=expiry, strike=strike, option_type=option_type)


def _option_quote(ref, ltp, stale=False):
    return Quote(instrument=ref, ltp=ltp, bid=None, ask=None, bid_qty=None, ask_qty=None,
                 timestamp=_NOW, stale=stale)


def test_parse_instrument_master_extracts_option_contract_terms():
    rows = parse_instrument_master(_fo_master_row(43125, 24000, "CE"))
    (opt,) = rows
    assert opt.exchange_segment == 2 and opt.exchange_instrument_id == 43125
    assert opt.expiry == date(2026, 7, 30) and opt.strike == 24000.0
    assert opt.option_type == "CE"


def test_parse_instrument_master_maps_numeric_option_type_codes():
    rows = parse_instrument_master(_fo_master_row(43126, 24000, "4"))  # 3=CE, 4=PE
    assert rows[0].option_type == "PE"


def test_parse_instrument_master_extracts_futures_and_drops_spreads():
    text = "\n".join([
        _fo_future_row(61093),
        _fo_future_row(14934839, type_code="4"),  # calendar spread → dropped
    ])
    (fut,) = parse_instrument_master(text)
    assert fut.exchange_instrument_id == 61093
    assert fut.instrument_type == "FUTIDX" and fut.expiry == date(2026, 7, 28)
    assert fut.strike is None and fut.option_type == ""


def test_indexes_parses_index_list(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "_request", lambda method, path, body=None: {
        "type": "success",
        "result": {"exchangeSegment": "1", "indexList": ["NIFTY 50_26000", "NIFTY BANK_26001"]},
    })
    client.token = "TOK"
    nifty, banknifty = client.indexes()
    assert nifty.symbol == "NIFTY 50" and nifty.exchange_instrument_id == 26000
    assert banknifty.exchange_instrument_id == 26001 and banknifty.exchange_segment == 1


def test_build_raw_market_data_from_xts_quotes():
    quotes = [
        _option_quote(_option_ref(1, 24000, "CE"), 250.0),
        _option_quote(_option_ref(2, 24000, "PE"), 180.0),
        _option_quote(_option_ref(3, 24100, "CE"), 190.0, stale=True),  # stale → excluded
    ]
    raw = build_raw_market_data(24050.0, quotes, _AS_OF := date(2026, 7, 10))
    assert raw.underlying == "NIFTY" and raw.spot == 24050.0
    assert raw.source is SourceTag.OBSERVED
    assert {(q.strike, q.is_call, q.settlement_price) for q in raw.option_chain} == {
        (24000.0, True, 250.0), (24000.0, False, 180.0),
    }
    # and the existing snapshot builder accepts it end-to-end
    snapshot = build_snapshot(raw)
    assert snapshot.spots["NIFTY"] == 24050.0


def test_build_raw_market_data_prefers_valid_bid_ask_midpoint():
    ref = _option_ref(1, 24000, "CE")
    quote = Quote(ref, ltp=150.0, bid=100.0, ask=102.0, bid_qty=10.0, ask_qty=10.0,
                  timestamp=_NOW, stale=False)
    raw = build_raw_market_data(24050.0, [quote], date(2026, 7, 10))
    assert raw.option_chain[0].settlement_price == 101.0


def test_build_raw_market_data_rejects_bad_inputs():
    good = _option_quote(_option_ref(1, 24000, "CE"), 250.0)
    with pytest.raises(ValueError, match="spot"):
        build_raw_market_data(0.0, [good], date(2026, 7, 10))
    with pytest.raises(ValueError, match="option"):
        build_raw_market_data(24050.0, [], date(2026, 7, 10))
    no_terms = _option_quote(InstrumentRef(exchange_segment=2, exchange_instrument_id=9), 5.0)
    with pytest.raises(ValueError, match="contract terms"):
        build_raw_market_data(24050.0, [good, no_terms], date(2026, 7, 10))


def test_xts_source_fetch_end_to_end(monkeypatch):
    """Login → index list + master → spot quote → filtered option quotes → RawMarketData."""
    client = _client()
    nsefo = "\n".join([
        _fo_master_row(1, 24000, "CE"),
        _fo_master_row(2, 24000, "PE"),
        _fo_master_row(3, 30000, "CE"),                            # far from spot → excluded
        _fo_master_row(4, 24000, "CE", expiry="2026-08-27T14:30:00"),  # 2nd expiry → beyond n_expiries
        _fo_master_row(5, 24000, "CE", expiry="2026-06-25T14:30:00"),  # past expiry → excluded
        _fo_master_row(6, 24000, "CE", name="BANKNIFTY"),          # other underlying → excluded
    ])
    prices = {26000: 24050.0, 1: 250.0, 2: 180.0}

    def fake_request(method, path, body=None):
        if path.endswith("/auth/login"):
            return {"type": "success", "result": {"token": "TOK", "userID": "U1"}}
        if "/instruments/indexlist" in path:
            return {"type": "success", "result": {"indexList": ["NIFTY 50_26000"]}}
        if path.endswith("/instruments/master"):
            assert body["exchangeSegmentList"] == ["NSEFO"]
            return {"type": "success", "result": nsefo}
        return {"type": "success", "result": {"listQuotes": [
            _touchline_json(
                i["exchangeInstrumentID"], ltp=prices[i["exchangeInstrumentID"]],
                bid=prices[i["exchangeInstrumentID"]] - 0.5,
                ask=prices[i["exchangeInstrumentID"]] + 0.5,
                segment=i["exchangeSegment"],
            )
            for i in body["instruments"]
        ]}}

    monkeypatch.setattr(client, "_request", fake_request)
    source = XTSSource(client=client, n_expiries=1, strike_window=0.10, clock=lambda: _NOW)
    raw = source.fetch(date(2026, 7, 10), "NIFTY")
    assert raw.spot == 24050.0
    assert {(q.strike, q.is_call) for q in raw.option_chain} == {(24000.0, True), (24000.0, False)}
    assert all(q.expiry == date(2026, 7, 30) for q in raw.option_chain)


def test_xts_source_rejects_explicitly_stale_spot(monkeypatch):
    client = _client()
    client.token = "TOK"
    option = _option_ref(1, 24000, "CE")
    monkeypatch.setattr(client, "indexes", lambda segment=1: [_NIFTY])
    monkeypatch.setattr(client, "instruments", lambda segment: [option])

    def fake_quotes(refs, **kwargs):
        ref = refs[0]
        return [Quote(
            ref, ltp=24000.0 if ref.exchange_segment == 1 else 100.0,
            bid=23999.0 if ref.exchange_segment == 1 else 99.0,
            ask=24001.0 if ref.exchange_segment == 1 else 101.0,
            bid_qty=10.0, ask_qty=10.0, timestamp=_NOW,
            stale=ref.exchange_segment == 1,
        )]

    monkeypatch.setattr(client, "quotes", fake_quotes)
    with pytest.raises(RuntimeError, match="fresh live spot"):
        XTSSource(client=client, clock=lambda: _NOW).fetch(date(2026, 7, 10), "NIFTY")


def test_api_error_raises_clean_error(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client, "_request",
        lambda *a, **k: {"type": "error", "code": "e-app-001", "description": "Invalid app key"},
    )
    client.token = "TOK123"
    with pytest.raises(RuntimeError) as excinfo:
        client.quotes([_NIFTY])
    assert "Invalid app key" in str(excinfo.value)
    assert "SEKRIT" not in str(excinfo.value)  # secrets never appear in errors


def test_instrument_master_is_cached_on_disk_per_day(tmp_path, monkeypatch):
    client = _client(master_cache_dir=tmp_path)
    calls = []

    def fake_request(method, path, body=None):
        calls.append(path)
        return {"type": "success", "result": _fo_future_row(61093)}

    monkeypatch.setattr(client, "_request", fake_request)
    client.token = "TOK"
    first = client.instruments("NSEFO")
    assert len(calls) == 1 and first[0].exchange_instrument_id == 61093

    # second call must come from the disk cache — the network would now fail
    monkeypatch.setattr(client, "_request", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    second = client.instruments("NSEFO")
    assert [r.exchange_instrument_id for r in second] == [61093]

    # a cache-less client (the test/CI default) never touches the shared disk cache
    uncached = _client()
    monkeypatch.setattr(uncached, "_request", fake_request)
    uncached.token = "TOK"
    uncached.instruments("NSEFO")
    assert len(calls) == 2


def test_instrument_master_parses_lot_size():
    (fut,) = parse_instrument_master(_fo_future_row(61093))
    assert fut.lot_size == 0  # fixture leaves col 12 blank
    real = "NSEFO|61093|1|NIFTY|NIFTY26JULFUT|FUTIDX|NIFTY-FUTIDX|1|26474.5|21661.1|1801|0.1|65|1|-1|Nifty 50|2026-07-28T14:30:00|NIFTY 28JUL2026|1|1|NIFTY26JULFUT"
    (fut,) = parse_instrument_master(real)
    assert fut.lot_size == 65
