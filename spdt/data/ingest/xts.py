"""XTS (Symphony Fintech) market-data adapter — broker feed for live quotes (Phase 1).

Speaks the XTS REST market-data API used by Symphony-powered brokers (e.g. AC Agarwal):
login, instrument master, and touchline quotes, normalized into SPDT-side ``Quote`` /
``InstrumentRef`` objects. Follows the same shape as :mod:`spdt.data.ingest.dhan` — pure
parse functions (unit-tested on fixtures) around one mockable ``_request`` HTTP method, so
tests need neither network nor credentials. Credentials come from ``SPDT_XTS_*``
environment variables and never appear in logs or errors.

Core quant modules must not import this directly — XTS data reaches them only through
``MarketSnapshot`` (see docs/XTS_INTEGRATION_ROADMAP.md).
"""

from __future__ import annotations

import json
import os
import urllib.request
import warnings
from dataclasses import dataclass, replace
from datetime import date as Date
from datetime import datetime, timezone
from math import exp, log1p, sqrt

from spdt.core.types import SourceTag, Underlying, year_fraction
from spdt.data.curate.implied_dividend import (
    implied_dividend_yield,
    implied_dividend_yield_from_strip,
)
from spdt.data.curate.expiries import select_term_spanning_expiries
from spdt.data.curate.rate_bootstrap import RateInstrument, bootstrap_zero_rates
from spdt.data.ingest import RawMarketData, RawOptionQuote

# XTS exchange-segment codes (instrument master uses the names, quote payloads the numbers).
EXCHANGE_SEGMENTS = {"NSECM": 1, "NSEFO": 2, "NSECD": 3, "BSECM": 11, "BSEFO": 12}
_SEGMENT_NAMES = {v: k for k, v in EXCHANGE_SEGMENTS.items()}
_TOUCHLINE_CODE = 1502  # xtsMessageCode for touchline (LTP + best bid/ask)
_OPTION_TYPES = {"CE": "CE", "PE": "PE", "3": "CE", "4": "PE"}  # masters use either form
_INDEX_NAMES = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK"}  # underlying → index-list name
# XTS timestamps count seconds since 1980-01-01 00:00 IST (verified against the live
# AC Agarwal feed 2026-07-16), not the Unix epoch.
XTS_EPOCH_OFFSET_S = 315_513_000  # Unix timestamp of 1980-01-01T00:00:00+05:30
# The fetch window is a *log-moneyness* band scaled by √τ, not a fixed percentage of spot:
# the strikes that matter at 1.3 years sit far further from spot than those at 1 month, and a
# ±10%-of-spot request captured 25 of the 48 quoted contracts at the 123-day expiry — enough
# of a loss to push that slice under the minimum-strike bar and out of the surface entirely.
_BAND_SD = 3.0          # how many standard deviations of the reference vol to span
_BAND_REF_VOL = 0.15    # a representative NIFTY vol; only sets the band's scale, not a price
_MAX_STRIKE_WINDOW = 0.60


@dataclass(frozen=True)
class InstrumentRef:
    """Broker-side identity of one instrument (segment + exchange instrument id).

    Option contracts additionally carry their terms (expiry/strike/option_type), parsed
    from the NSEFO instrument master.
    """

    exchange_segment: int
    exchange_instrument_id: int
    symbol: str = ""
    description: str = ""
    series: str = ""
    instrument_type: str = ""
    expiry: Date | None = None
    strike: float | None = None
    option_type: str = ""  # "CE", "PE", or "" for non-options
    lot_size: int = 0  # 0 = unknown (e.g. refs built from quote payloads)


@dataclass(frozen=True)
class Quote:
    """One normalized touchline quote. ``stale`` is explicit — never guess freshness."""

    instrument: InstrumentRef
    ltp: float | None
    bid: float | None
    ask: float | None
    bid_qty: float | None
    ask_qty: float | None
    timestamp: datetime | None
    stale: bool
    source: str = "xts"


def _price_or_none(value, *, field: str) -> float | None:
    try:
        price = float(value or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid XTS {field}: {value!r}") from exc
    return price if price > 0.0 else None


def parse_touchline(
    payload: dict, *, now: datetime | None = None, max_age_s: float = 300.0,
    max_future_skew_s: float = 5.0,
) -> Quote:
    """Normalize one decoded ``listQuotes`` touchline entry into a :class:`Quote`.

    A quote is stale when it has no positive last-traded price, or when its exchange
    timestamp is more than ``max_age_s`` behind ``now``.
    """
    touch = payload.get("Touchline", {})
    ltp = _price_or_none(touch.get("LastTradedPrice"), field="LastTradedPrice")
    raw_ts = touch.get("LastUpdateTime")
    try:
        timestamp = (
            datetime.fromtimestamp(int(raw_ts) + XTS_EPOCH_OFFSET_S, tz=timezone.utc)
            if raw_ts else None
        )
    except (TypeError, ValueError, OSError, OverflowError) as exc:
        raise ValueError(f"invalid XTS LastUpdateTime: {raw_ts!r}") from exc
    normalized_now = None
    if now is not None:
        normalized_now = now.astimezone(timezone.utc)
    age_s = (
        (normalized_now - timestamp).total_seconds()
        if normalized_now is not None and timestamp is not None else None
    )
    bid, ask = touch.get("BidInfo", {}), touch.get("AskInfo", {})
    bid_price = _price_or_none(bid.get("Price"), field="BidInfo.Price")
    ask_price = _price_or_none(ask.get("Price"), field="AskInfo.Price")
    crossed = bid_price is not None and ask_price is not None and bid_price > ask_price
    stale = (
        ltp is None or timestamp is None or crossed
        or (age_s is not None and (age_s > max_age_s or age_s < -max_future_skew_s))
    )
    return Quote(
        instrument=InstrumentRef(
            exchange_segment=int(payload.get("ExchangeSegment", 0)),
            exchange_instrument_id=int(payload.get("ExchangeInstrumentID", 0)),
        ),
        ltp=ltp,
        bid=bid_price,
        ask=ask_price,
        bid_qty=float(bid["Size"]) if bid.get("Size") else None,
        ask_qty=float(ask["Size"]) if ask.get("Size") else None,
        timestamp=timestamp,
        stale=stale,
    )


def parse_instrument_master(text: str) -> list[InstrumentRef]:
    """Parse the pipe-delimited instrument master into :class:`InstrumentRef` rows.

    Column layout verified against the live AC Agarwal master (2026-07-16). The series
    column (5) discriminates row kinds: ``OPT*`` rows carry expiry/strike/option-type at
    columns 16/17/18 (expiry is ISO datetime, option type numeric 3=CE/4=PE), ``FUT*``
    rows carry expiry at 16, cash rows have no contract terms (their column 16 is a
    price numerator, not a date). Calendar-spread rows (instrument-type code 4) are
    dropped — they are two-leg contracts, not outrights.
    """
    rows: list[InstrumentRef] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        fields = line.split("|")
        if len(fields) < 6:
            continue  # blank / malformed line
        try:
            segment = EXCHANGE_SEGMENTS[fields[0]]
            instrument_id = int(fields[1])
            if instrument_id <= 0:
                raise ValueError("instrument id must be positive")
            series = fields[5].strip()
            expiry = strike = None
            option_type = ""
            if series.startswith("OPT"):
                if len(fields) < 19 or not fields[16] or not fields[17]:
                    raise ValueError("option row lacks expiry or strike")
                expiry = datetime.strptime(fields[16][:10], "%Y-%m-%d").date()
                strike = float(fields[17])
                if strike <= 0:
                    raise ValueError("option strike must be positive")
                raw_option_type = fields[18].strip()
                option_type = _OPTION_TYPES.get(raw_option_type, "")
                if not option_type:
                    raise ValueError(f"unknown option type {raw_option_type!r}")
            elif series.startswith("FUT"):
                if fields[2].strip() == "4":
                    continue  # calendar spread, not an outright future
                if len(fields) < 17 or not fields[16]:
                    raise ValueError("futures row lacks expiry")
                expiry = datetime.strptime(fields[16][:10], "%Y-%m-%d").date()
            rows.append(InstrumentRef(
                exchange_segment=segment,
                exchange_instrument_id=instrument_id,
                symbol=fields[3].strip(),
                description=fields[4].strip(),
                series=series,
                instrument_type=series,
                expiry=expiry,
                strike=strike,
                option_type=option_type,
                lot_size=int(fields[12]) if len(fields) > 12 and fields[12].isdigit() else 0,
            ))
        except (KeyError, TypeError, ValueError) as exc:
            warnings.warn(
                f"skipping malformed XTS instrument-master line {line_number}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
    return rows


def _calibration_price(quote: Quote) -> float | None:
    if quote.bid is not None and quote.ask is not None and quote.bid <= quote.ask:
        return (quote.bid + quote.ask) / 2.0
    return quote.ltp


def build_raw_market_data(
    spot: float,
    option_quotes: list[Quote],
    as_of: Date,
    *,
    underlying: Underlying = "NIFTY",
    risk_free_rate: float = 0.065,
    funding_spread: float = 0.012,
    dividend_yield: float = 0.013,
    rate_instruments: list[RateInstrument] | None = None,
) -> RawMarketData:
    """Assemble :class:`RawMarketData` from an XTS spot + option quotes (+ FBIL rates).

    Stale/unpriced quotes are dropped; quotes whose instrument lacks contract terms are a
    programming error and raise.
    """
    if spot <= 0.0:
        raise ValueError("XTS returned a non-positive spot")
    chain: list[RawOptionQuote] = []
    for quote in option_quotes:
        ref = quote.instrument
        if ref.expiry is None or ref.strike is None or not ref.option_type:
            raise ValueError(
                f"option quote for instrument {ref.exchange_instrument_id} lacks contract terms"
            )
        price = _calibration_price(quote)
        if quote.stale or price is None:
            continue
        # Carry the touchline's two sides through. XTS publishes no volume or open interest, so
        # the presence of a real bid *and* a real ask is the only liquidity evidence this feed
        # offers — and dropping it here left the live surface with no liquidity screen at all,
        # fitted to whatever the chain happened to print.
        chain.append(RawOptionQuote(
            ref.expiry, ref.strike, ref.option_type == "CE", price,
            bid=quote.bid, ask=quote.ask,
        ))
    if not chain:
        raise ValueError("no live priced option quotes in the XTS chain")
    if rate_instruments:
        ois_zero_rates = bootstrap_zero_rates(as_of, rate_instruments)
    else:
        ois_zero_rates = {e: risk_free_rate for e in sorted({q.expiry for q in chain})}
    pillars = sorted(ois_zero_rates)
    return RawMarketData(
        date=as_of,
        underlying=underlying,
        spot=spot,
        option_chain=tuple(chain),
        ois_zero_rates=ois_zero_rates,
        funding_spread_knots={pillars[0]: funding_spread, pillars[-1]: funding_spread},
        dividend_yield=dividend_yield,
        source=SourceTag.OBSERVED,
    )


class XTSMarketDataClient:
    """Thin authenticated client for the XTS market-data REST API.

    All HTTP goes through :meth:`_request` so tests can stub it (no network, no secrets).
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        app_key: str | None = None,
        secret: str | None = None,
        source: str = "WebAPI",
        timeout: float = 30.0,
        master_cache_dir: str | os.PathLike | None = None,  # None = no disk cache
    ) -> None:
        self.base_url = (base_url or os.environ.get("SPDT_XTS_BASE_URL", "")).rstrip("/")
        self.app_key = app_key or os.environ.get("SPDT_XTS_MARKETDATA_APP_KEY")
        self.secret = secret or os.environ.get("SPDT_XTS_MARKETDATA_SECRET")
        self.source = source
        self.timeout = timeout
        self.master_cache_dir = master_cache_dir
        self.token: str | None = None

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["authorization"] = self.token
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 (configured host)
            return json.loads(response.read())

    def _result(self, payload: dict):
        if payload.get("type") != "success":
            # description only — credentials must never appear in errors
            raise RuntimeError(f"XTS API error: {payload.get('description', 'unknown error')}")
        return payload.get("result")

    def login(self) -> None:
        """Authenticate and store the session token for subsequent calls."""
        if not self.app_key or not self.secret:
            raise RuntimeError(
                "XTS credentials missing — set SPDT_XTS_MARKETDATA_APP_KEY and "
                "SPDT_XTS_MARKETDATA_SECRET"
            )
        result = self._result(self._request("POST", "/auth/login", {
            "appKey": self.app_key, "secretKey": self.secret, "source": self.source,
        }))
        self.token = result["token"]

    def instruments(self, exchange_segment: str) -> list[InstrumentRef]:
        """Fetch and parse the instrument master for one segment (e.g. ``"NSEFO"``).

        The raw master (~17MB for NSEFO) only changes daily, so when the client was
        built with ``master_cache_dir`` it is cached on disk per segment per day.
        """
        from pathlib import Path

        cache = None
        if self.master_cache_dir is not None:
            cache = Path(self.master_cache_dir) / (
                f"spdt_xts_master_{exchange_segment}_{Date.today().isoformat()}.txt"
            )
            if cache.exists():
                return parse_instrument_master(cache.read_text())
        result = self._result(self._request("POST", "/instruments/master", {
            "exchangeSegmentList": [exchange_segment],
        }))
        if cache is not None:
            try:
                cache.write_text(result)
            except OSError:
                pass  # cache is best-effort — never fail the fetch over it
        return parse_instrument_master(result)

    def indexes(self, exchange_segment: int = 1) -> list[InstrumentRef]:
        """Fetch the index list (indexes are not in the cash instrument master).

        Entries come back as ``"NIFTY 50_26000"`` — name and instrument id joined by
        the last underscore.
        """
        result = self._result(self._request(
            "GET", f"/instruments/indexlist?exchangeSegment={exchange_segment}",
        ))
        refs: list[InstrumentRef] = []
        for entry in result.get("indexList", []):
            name, _, raw_id = str(entry).rpartition("_")
            if not name or not raw_id.isdigit():
                raise ValueError(f"malformed XTS index-list entry: {entry!r}")
            refs.append(InstrumentRef(
                exchange_segment=exchange_segment,
                exchange_instrument_id=int(raw_id),
                symbol=name,
            ))
        return refs

    def quotes(
        self,
        instruments: list[InstrumentRef],
        *,
        now: datetime | None = None,
        max_age_s: float = 300.0,
    ) -> list[Quote]:
        """Fetch touchline quotes. Instruments the broker omits are simply absent."""
        result = self._result(self._request("POST", "/instruments/quotes", {
            "instruments": [
                {"exchangeSegment": i.exchange_segment,
                 "exchangeInstrumentID": i.exchange_instrument_id}
                for i in instruments
            ],
            "xtsMessageCode": _TOUCHLINE_CODE,
            "publishFormat": "JSON",
        }))
        if not isinstance(result, dict):
            raise ValueError("XTS quote result must be an object")
        quotes: list[Quote] = []
        for index, entry in enumerate(result.get("listQuotes", [])):
            if isinstance(entry, str):
                try:
                    decoded = json.loads(entry)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON in XTS listQuotes[{index}]") from exc
            elif isinstance(entry, dict):
                decoded = entry
            else:
                raise ValueError(f"XTS listQuotes[{index}] must be a JSON string or object")
            quotes.append(parse_touchline(decoded, now=now, max_age_s=max_age_s))
        return quotes


class XTSSource:
    """XTS-fed ``MarketDataSource``: spot + near-the-money option chain → :class:`RawMarketData`.

    Universe selection: options on ``underlying`` with the nearest ``n_expiries`` expiries on
    or after ``as_of``, strikes within ``strike_window`` (fraction) of the live spot.
    """

    def __init__(
        self,
        *,
        client: XTSMarketDataClient | None = None,
        # Enough to span weeklies through the multi-year LEAPS the NIFTY master lists; the
        # selection below spreads them across the curve rather than taking the nearest N.
        n_expiries: int = 8,
        # Contracts fed to the dividend-carry fit. Three covers the liquid part of the NIFTY
        # futures curve; beyond that the quotes thin out and add noise to the slope.
        n_dividend_futures: int = 3,
        strike_window: float = 0.10,
        batch_size: int = 50,  # XTS quote API caps instruments per request
        # Marking source, like bhavcopy: outside market hours quotes sit at the last
        # session's close, so accept up to 3 days (covers weekends). Live-execution
        # freshness is gated separately (SPDT_QUOTE_MAX_AGE_S in the hedge path).
        # ponytail: one window for spot+chain — a dead intraday feed serving a
        # hours-old close passes; split spot/chain windows if that ever bites.
        max_age_s: float = 259_200.0,
        risk_free_rate: float = 0.065,
        funding_spread: float = 0.012,
        dividend_yield: float = 0.013,
        rate_instruments: list[RateInstrument] | None = None,
        clock=datetime.now,  # injectable for tests / deterministic replay
    ) -> None:
        self.client = client or XTSMarketDataClient()
        self.clock = clock
        self.max_age_s = max_age_s
        self.n_expiries = n_expiries
        self.n_dividend_futures = n_dividend_futures
        self.strike_window = strike_window
        self.batch_size = batch_size
        self.risk_free_rate = risk_free_rate
        self.funding_spread = funding_spread
        self.dividend_yield = dividend_yield
        self.rate_instruments = rate_instruments

    def _quotes_with_refs(self, refs: list[InstrumentRef], now: datetime | None) -> list[Quote]:
        """Fetch quotes in batches and re-attach the full master refs (touchline only has ids)."""
        by_id = {(r.exchange_segment, r.exchange_instrument_id): r for r in refs}
        quotes: list[Quote] = []
        for i in range(0, len(refs), self.batch_size):
            batch = self.client.quotes(
                refs[i : i + self.batch_size], now=now, max_age_s=self.max_age_s,
            )
            for quote in batch:
                key = (quote.instrument.exchange_segment, quote.instrument.exchange_instrument_id)
                if key in by_id:
                    quotes.append(replace(quote, instrument=by_id[key]))
        return quotes

    def fetch(self, as_of: Date, underlying: Underlying = "NIFTY") -> RawMarketData:
        """Pull spot + near-the-money chain via XTS and build a snapshot input (network I/O)."""
        if not self.client.token:
            self.client.login()
        now = self.clock()

        index_symbol = _INDEX_NAMES.get(underlying, underlying)
        index = [r for r in self.client.indexes() if r.symbol == index_symbol]
        if not index:
            raise RuntimeError(f"index {index_symbol!r} not found in the XTS index list")
        spot_quotes = self._quotes_with_refs(index[:1], now)
        if len(spot_quotes) != 1:
            raise RuntimeError(f"expected one live spot for {index_symbol!r}, got {len(spot_quotes)}")
        spot_quote = spot_quotes[0]
        if spot_quote.stale or spot_quote.ltp is None:
            raise RuntimeError(f"no fresh live spot for {index_symbol!r}")
        spot = spot_quote.ltp

        fo_master = [r for r in self.client.instruments("NSEFO")
                     if r.symbol == underlying and r.expiry and r.expiry >= as_of]
        options = [r for r in fo_master if r.option_type and r.strike is not None]
        expiries = select_term_spanning_expiries(
            [r.expiry for r in options if r.expiry is not None], as_of, self.n_expiries
        )
        # The strike window has to widen with maturity: ±10% spans a 1-month smile but
        # truncates a 2-year one to a sliver around the forward, which is both too few points
        # to fit and blind to exactly the wings a barrier note is sensitive to. Scale by √τ
        # against a one-month reference, capped so a 5-year request stays a sane size.
        expiry_set = set(expiries)
        chain_refs = []
        for r in options:
            if r.expiry not in expiry_set or r.strike is None:
                continue
            tau = max(year_fraction(as_of, r.expiry), 1.0 / 365.0)
            half_width = min(_BAND_SD * _BAND_REF_VOL * sqrt(tau), log1p(_MAX_STRIKE_WINDOW))
            if spot * exp(-half_width) <= r.strike <= spot * exp(half_width):
                chain_refs.append(r)

        return build_raw_market_data(
            spot, self._quotes_with_refs(chain_refs, now), as_of,
            underlying=underlying, risk_free_rate=self.risk_free_rate,
            funding_spread=self.funding_spread,
            dividend_yield=self._implied_dividend(fo_master, spot, as_of, now),
            rate_instruments=self.rate_instruments,
        )

    def _implied_dividend(self, fo_master: list[InstrumentRef], spot: float,
                          as_of: Date, now: datetime | None) -> float:
        """Imply q from the futures curve's carry; fall back to the configured yield.

        Fits the whole strip when two or more contracts quote, because that reads the carry
        off the *slope* and so never touches spot — the input most likely to be stale against
        the futures, and the one a single-contract inversion amplifies by 1/T. Only when a
        lone contract quotes does this fall back to the spot-based form.
        """
        futures = sorted(
            (r for r in fo_master if r.instrument_type == "FUTIDX" and r.expiry is not None),
            key=lambda r: r.expiry or Date.max,
        )
        if not futures:
            return self.dividend_yield
        quotes = self._quotes_with_refs(futures[: self.n_dividend_futures], now)
        priced: list[tuple[Date, float]] = []
        for quote in quotes:
            expiry = quote.instrument.expiry
            price = _calibration_price(quote) if not quote.stale else None
            if expiry is not None and price is not None:
                priced.append((expiry, price))
        if not priced:
            return self.dividend_yield
        priced.sort()

        zeros = bootstrap_zero_rates(as_of, self.rate_instruments) if self.rate_instruments else {}

        def rate_for(expiry: Date) -> float:
            if not zeros:
                return self.risk_free_rate
            return zeros[min(zeros, key=lambda p: abs((p - expiry).days))]

        try:
            if len(priced) >= 2:
                strip = [(year_fraction(as_of, e), p) for e, p in priced]
                return implied_dividend_yield_from_strip(strip, rate_for(priced[-1][0]))
            expiry, price = priced[0]
            return implied_dividend_yield(
                spot, price, year_fraction(as_of, expiry), rate_for(expiry)
            )
        except ValueError:  # bad futures print — keep the assumption rather than a wild q
            return self.dividend_yield
