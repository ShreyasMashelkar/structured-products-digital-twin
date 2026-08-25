"""CBOE SPX/SPY option chain — real two-sided quotes (design doc §2.2, US shelf).

Why this source exists alongside the NSE path: the model validation run
(:mod:`spdt.validation.report`) established that the NIFTY settlement archive cannot support
the flagship product. After screening out contracts with no traded volume and no open interest,
no historical NIFTY date carried a usable quote past ~1 year, and several stopped below three
months. A three-year autocallable priced on that data is priced on an extrapolation.

CBOE's delayed-quote feed fixes both halves of that problem at once:

* **Tenor.** SPX lists LEAPS with genuine open interest out past five years, so the note can be
  priced across its whole life on quotes that exist rather than on a flat extrapolation of the
  last calibrated slice.
* **Two-sided markets.** NSE publishes one settlement mark per contract. CBOE publishes bid and
  ask, which is the difference between *assuming* a transaction cost and *measuring* one. The
  hedge backtest and the funding/bid-ask cost model both depend on this.

The feed is delayed and free, which bounds what it can honestly be used for: it is a snapshot
of one moment, not a history. There is no way to ask it for 2020-03-23. The NSE archive remains
the only source in this project that reaches back through a crisis, so the two sources are
complementary — US for depth and realism today, India for stressed history — and neither
replaces the other.
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.request
from datetime import date, datetime
from pathlib import Path

try:  # certifi's CA bundle — robust across machines (esp. macOS python.org builds)
    import certifi

    _SSL_CONTEXT: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover - falls back to the system trust store
    _SSL_CONTEXT = None

from spdt.core.types import SourceTag, Underlying
from spdt.data.ingest import RawMarketData, RawOptionQuote

_ENDPOINT = "https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
_USER_AGENT = "Mozilla/5.0 (compatible; spdt-research/1.0)"
_CACHE_DIR = Path("data/cboe_cache")

# CBOE prefixes cash-settled index symbols with an underscore in the quote feed but not in the
# OCC contract codes inside it. Mapping them explicitly beats guessing: an unknown symbol
# silently returns an empty chain, which would read downstream as "an illiquid day".
_SYMBOLS: dict[str, str] = {
    "SPX": "_SPX",
    "SPY": "SPY",
    "NDX": "_NDX",
    "QQQ": "QQQ",
    "RUT": "_RUT",
}

# OCC option symbol: root, YYMMDD, C/P, strike in thousandths of a dollar.
_OCC = re.compile(r"^(?P<root>[A-Z^_]+)(?P<ymd>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")


def cboe_url(underlying: Underlying) -> str:
    """Delayed-quote endpoint for ``underlying``.

    Cash-settled indices need the underscore prefix and are mapped explicitly. Single equities
    and ETFs use their plain ticker, so they are passed through rather than enumerated — the
    single-stock notes that dominate the EDGAR shelf reference hundreds of different names, and
    a fixed list would have to be maintained forever to keep up with them.
    """
    if underlying in _SYMBOLS:
        return _ENDPOINT.format(symbol=_SYMBOLS[underlying])
    if re.fullmatch(r"[A-Z][A-Z.]{0,5}", underlying):
        return _ENDPOINT.format(symbol=underlying)
    raise ValueError(
        f"{underlying!r} is neither a mapped index nor a plausible listed ticker; "
        f"mapped indices: {sorted(_SYMBOLS)}"
    )


def parse_occ_symbol(symbol: str) -> tuple[date, float, bool] | None:
    """Parse an OCC contract code into ``(expiry, strike, is_call)``; ``None`` if malformed.

    Returning ``None`` rather than raising keeps one unrecognised contract in a 30,000-line feed
    from destroying the whole chain.
    """
    m = _OCC.match(symbol)
    if not m:
        return None
    ymd = m.group("ymd")
    try:
        expiry = date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6]))
    except ValueError:
        return None
    return expiry, int(m.group("strike")) / 1000.0, m.group("cp") == "C"


def download_chain(
    underlying: Underlying, *, timeout: float = 40.0, cache: bool = True
) -> dict:
    """Fetch (or read from cache) the raw CBOE delayed-quote payload.

    Cached under the *fetch* date: the feed has no as-of parameter, so a cache entry can only
    ever mean "the chain as it stood when we asked on that day". Naming it by date makes that
    limitation visible instead of letting a stale file masquerade as today's market.
    """
    path = _CACHE_DIR / f"{underlying}_{date.today():%Y%m%d}.json"
    if cache and path.exists():
        return json.loads(path.read_text())

    request = urllib.request.Request(cboe_url(underlying), headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(  # noqa: S310 (fixed CBOE CDN host)
        request, timeout=timeout, context=_SSL_CONTEXT
    ) as response:
        payload = json.loads(response.read())

    if cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
    return payload


def parse_chain(
    payload: dict,
    underlying: Underlying,
    *,
    as_of: date | None = None,
    risk_free_rate: float = 0.042,
    funding_spread: float = 0.008,
    dividend_yield: float = 0.013,
    require_two_sided: bool = True,
) -> RawMarketData:
    """Turn a CBOE delayed-quote payload into :class:`RawMarketData`.

    ``require_two_sided`` drops contracts without a genuine bid **and** ask. A zero bid is not a
    price of zero — it means no one is currently willing to buy at any price, so the ask alone
    conveys almost nothing about fair value. Keeping such rows would let the widest, least
    informative contracts into the calibration under the appearance of data.

    The mid of the two-sided market becomes ``settlement_price``, so every existing consumer of
    ``RawMarketData`` works unchanged; the raw bid and ask ride alongside for the cost models
    that need them.
    """
    data = payload.get("data", {})
    spot = data.get("current_price") or data.get("close")
    if not spot:
        raise ValueError("CBOE payload carries no underlying price")

    if as_of is None:
        stamp = payload.get("timestamp") or data.get("last_trade_time")
        as_of = _parse_stamp(stamp) or date.today()

    quotes: list[RawOptionQuote] = []
    for row in data.get("options", []):
        parsed = parse_occ_symbol(row.get("option", ""))
        if parsed is None:
            continue
        expiry, strike, is_call = parsed
        if expiry <= as_of:
            continue
        bid, ask = float(row.get("bid") or 0.0), float(row.get("ask") or 0.0)
        if require_two_sided and not (ask >= bid > 0.0):
            continue
        mid = 0.5 * (bid + ask) if ask >= bid > 0.0 else float(row.get("last_trade_price") or 0.0)
        if mid <= 0.0:
            continue
        quotes.append(
            RawOptionQuote(
                expiry=expiry,
                strike=strike,
                is_call=is_call,
                settlement_price=mid,
                contracts_traded=float(row.get("volume") or 0.0),
                open_interest=float(row.get("open_interest") or 0.0),
                bid=bid or None,
                ask=ask or None,
            )
        )
    if not quotes:
        raise ValueError(f"no usable {underlying} quote in the CBOE payload")

    expiries = sorted({q.expiry for q in quotes})
    ois_zero_rates = {e: risk_free_rate for e in expiries}
    funding_spread_knots = {expiries[0]: funding_spread, expiries[-1]: funding_spread}

    return RawMarketData(
        date=as_of,
        underlying=underlying,
        spot=float(spot),
        option_chain=tuple(quotes),
        ois_zero_rates=ois_zero_rates,
        funding_spread_knots=funding_spread_knots,
        dividend_yield=dividend_yield,
        source=SourceTag.OBSERVED,
    )


def _parse_stamp(stamp: str | None) -> date | None:
    """Best-effort date from CBOE's assorted timestamp formats."""
    if not stamp:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(stamp[: len(fmt) + 2].strip(), fmt).date()
        except ValueError:
            continue
    return None


class CboeSource:
    """CBOE delayed-quote source implementing the ``MarketDataSource`` interface.

    Note the interface mismatch this class deliberately does not hide: ``fetch`` takes an
    ``as_of``, but the feed only ever serves *now*. Passing a historical date raises rather
    than quietly returning today's chain stamped with the requested date, which would
    manufacture a point-in-time snapshot that never existed.
    """

    def __init__(
        self,
        *,
        risk_free_rate: float = 0.042,
        funding_spread: float = 0.008,
        dividend_yield: float = 0.013,
        require_two_sided: bool = True,
        timeout: float = 40.0,
        cache: bool = True,
    ) -> None:
        self.risk_free_rate = risk_free_rate
        self.funding_spread = funding_spread
        self.dividend_yield = dividend_yield
        self.require_two_sided = require_two_sided
        self.timeout = timeout
        self.cache = cache

    def fetch(self, as_of: date, underlying: Underlying = "SPX") -> RawMarketData:
        today = date.today()
        if as_of < today:
            raise ValueError(
                f"CBOE delayed quotes serve the current chain only; {as_of} is historical. "
                "Use spdt.data.ingest.nse_historical for point-in-time dates."
            )
        payload = download_chain(underlying, timeout=self.timeout, cache=self.cache)
        return parse_chain(
            payload,
            underlying,
            as_of=today,
            risk_free_rate=self.risk_free_rate,
            funding_spread=self.funding_spread,
            dividend_yield=self.dividend_yield,
            require_two_sided=self.require_two_sided,
        )
