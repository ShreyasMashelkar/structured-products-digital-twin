"""Legacy NSE F&O bhavcopy source — the pre-UDiFF archive (design doc §2.2).

:mod:`spdt.data.ingest.nse_bhavcopy` reads the **UDiFF** common bhavcopy, which NSE only
began publishing in mid-2024. Every business date before that lives in a different archive
under a different schema::

    /content/historical/DERIVATIVES/<YYYY>/<MON>/fo<DDMONYYYY>bhav.csv.zip

That archive is what makes historical model validation possible at all: it reaches back past
the 2018 IL&FS credit event, the March-2020 COVID crash and the 2022 hiking cycle, so a
surface can be calibrated *as it stood* on a stressed date rather than only on a calm one.

Two schema differences matter versus UDiFF:

* Columns are the legacy uppercase names (``OPTION_TYP``/``STRIKE_PR``/``SETTLE_PR``), not
  the ISO-20022-style UDiFF names (``OptnTp``/``StrkPric``/``SttlmPric``).
* There is **no ``UndrlygPric`` column**. The index level is recovered from the near-month
  index future in the same file: ``S = F·exp(−(r−q)·τ)``. That keeps spot, forward and the
  inverted smile mutually consistent — they all come from one file, at one instant, under
  one set of carry assumptions — which is exactly the property a point-in-time snapshot needs.

Downloads are cached on disk (``data/bhavcopy_cache/``) because a validation run replays the
same handful of dates repeatedly; after the first pass the whole harness runs offline.
"""

from __future__ import annotations

import io
import ssl
import urllib.error
import urllib.request
import zipfile
from datetime import date, timedelta
from math import exp
from pathlib import Path

import pandas as pd

try:  # certifi's CA bundle — robust across machines (esp. macOS python.org builds)
    import certifi

    _SSL_CONTEXT: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover - falls back to the system trust store
    _SSL_CONTEXT = None

from spdt.core.types import SourceTag, Underlying
from spdt.data.curate.rate_bootstrap import RateInstrument, bootstrap_zero_rates
from spdt.data.ingest import RawMarketData, RawOptionQuote

_ARCHIVE = "https://nsearchives.nseindia.com"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_CACHE_DIR = Path("data/bhavcopy_cache")

# ACT/365F, matching spdt.core.types.year_fraction — kept local so ingest stays leaf-level.
_DAYS_PER_YEAR = 365.0


def legacy_bhavcopy_url(as_of: date) -> str:
    """URL of the legacy F&O bhavcopy ZIP for ``as_of`` (e.g. ``fo23MAR2020bhav.csv.zip``)."""
    mon = f"{as_of:%b}".upper()  # NSE uses MAR, not Mar, in both the folder and the filename
    return (
        f"{_ARCHIVE}/content/historical/DERIVATIVES/{as_of:%Y}/{mon}/"
        f"fo{as_of:%d}{mon}{as_of:%Y}bhav.csv.zip"
    )


def _cache_path(as_of: date) -> Path:
    return _CACHE_DIR / f"fo_{as_of:%Y%m%d}.csv"


def download_legacy_bhavcopy(
    as_of: date, *, timeout: float = 30.0, cache: bool = True
) -> pd.DataFrame:
    """Fetch (or read from cache) the legacy F&O bhavcopy for ``as_of``.

    A cached miss is written as a plain CSV so the cache is inspectable and portable; the
    network is only touched the first time a date is requested.
    """
    path = _cache_path(as_of)
    if cache and path.exists():
        return pd.read_csv(path)

    url = legacy_bhavcopy_url(as_of)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(  # noqa: S310 (fixed NSE archive host)
        request, timeout=timeout, context=_SSL_CONTEXT
    ) as response:
        payload = response.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        with archive.open(archive.namelist()[0]) as handle:
            frame = pd.read_csv(handle)

    if cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
    return frame


def latest_available_legacy(
    as_of: date, *, max_lookback: int = 7, timeout: float = 30.0, cache: bool = True
) -> tuple[date, pd.DataFrame]:
    """Most recent published legacy bhavcopy on or before ``as_of`` — walks back over 404s.

    Indian market holidays are numerous and move year to year; rather than carry a holiday
    calendar, we simply walk back to the last date the exchange actually published, and
    return that date so it — not the requested one — anchors the snapshot.
    """
    last_error: Exception | None = None
    for back in range(max_lookback + 1):
        d = as_of - timedelta(days=back)
        if d.weekday() >= 5:  # skip Sat/Sun before spending a request
            continue
        try:
            return d, download_legacy_bhavcopy(d, timeout=timeout, cache=cache)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            last_error = e
    raise FileNotFoundError(
        f"no legacy F&O bhavcopy published in the {max_lookback} days before {as_of}"
    ) from last_error


def _implied_spot(rows: pd.DataFrame, as_of: date, rate: float, dividend_yield: float) -> float:
    """Back out the index level from the near-month index future in the same file.

    ``F = S·exp((r−q)·τ)`` inverted. Using the future rather than a separately-downloaded cash
    close keeps every number in the snapshot sourced from one file at one instant — a second
    download could straddle a session boundary and silently desynchronise spot from the smile.
    """
    futures = rows[(rows["INSTRUMENT"] == "FUTIDX") & (rows["SETTLE_PR"] > 0.0)].copy()
    if futures.empty:
        raise ValueError(f"no index futures rows to imply spot from in the {as_of} bhavcopy")
    futures["_tau"] = [
        (e - as_of).days / _DAYS_PER_YEAR for e in pd.to_datetime(futures["EXPIRY_DT"]).dt.date
    ]
    near = futures[futures["_tau"] > 0.0].nsmallest(1, "_tau")
    if near.empty:  # expiry day itself — the future has converged to spot
        near = futures.nlargest(1, "OPEN_INT")
        return float(near["SETTLE_PR"].iloc[0])
    tau = float(near["_tau"].iloc[0])
    return float(near["SETTLE_PR"].iloc[0]) * exp(-(rate - dividend_yield) * tau)


def parse_legacy_bhavcopy(
    frame: pd.DataFrame,
    as_of: date,
    underlying: Underlying,
    *,
    risk_free_rate: float,
    funding_spread: float,
    dividend_yield: float,
    rate_instruments: list[RateInstrument] | None = None,
) -> RawMarketData:
    """Turn a legacy F&O bhavcopy DataFrame into :class:`RawMarketData` for one underlying.

    Mirrors :func:`spdt.data.ingest.nse_bhavcopy.parse_fo_bhavcopy` — same output shape, same
    rate handling — differing only in the column names it reads and in recovering spot from
    the futures strip instead of an ``UndrlygPric`` column.
    """
    frame = frame.rename(columns=lambda c: str(c).strip())
    symbol_rows = frame[frame["SYMBOL"] == underlying].copy()
    if symbol_rows.empty:
        raise ValueError(f"no rows for {underlying!r} in the {as_of} bhavcopy")

    options = symbol_rows[
        symbol_rows["OPTION_TYP"].isin(["CE", "PE"]) & (symbol_rows["SETTLE_PR"] > 0.0)
    ].copy()
    if options.empty:
        raise ValueError(f"no option rows for {underlying!r} in the {as_of} bhavcopy")
    options["EXPIRY_DT"] = pd.to_datetime(options["EXPIRY_DT"]).dt.date

    quotes = tuple(
        RawOptionQuote(
            expiry=r.EXPIRY_DT,
            strike=float(r.STRIKE_PR),
            is_call=(r.OPTION_TYP == "CE"),
            settlement_price=float(r.SETTLE_PR),
            contracts_traded=float(getattr(r, "CONTRACTS", 0.0) or 0.0),
            open_interest=float(getattr(r, "OPEN_INT", 0.0) or 0.0),
        )
        for r in options.itertuples(index=False)
    )

    if rate_instruments:
        ois_zero_rates = bootstrap_zero_rates(as_of, rate_instruments)
    else:
        ois_zero_rates = {e: risk_free_rate for e in sorted({q.expiry for q in quotes})}
    pillars = sorted(ois_zero_rates)
    funding_spread_knots = {pillars[0]: funding_spread, pillars[-1]: funding_spread}

    # Spot is implied at the front-end rate, which is the tenor the near future spans.
    front_rate = ois_zero_rates[pillars[0]]
    spot = _implied_spot(symbol_rows, as_of, front_rate, dividend_yield)

    return RawMarketData(
        date=as_of,
        underlying=underlying,
        spot=spot,
        option_chain=quotes,
        ois_zero_rates=ois_zero_rates,
        funding_spread_knots=funding_spread_knots,
        dividend_yield=dividend_yield,
        source=SourceTag.OBSERVED,
    )


class NseHistoricalSource:
    """Legacy-archive EOD source implementing the ``MarketDataSource`` interface.

    Use this for any ``as_of`` before the UDiFF cutover (mid-2024);
    :class:`~spdt.data.ingest.nse_bhavcopy.NseBhavcopySource` handles dates after it.
    :func:`bhavcopy_source_for` picks between them.
    """

    def __init__(
        self,
        *,
        risk_free_rate: float = 0.065,
        funding_spread: float = 0.012,
        dividend_yield: float = 0.013,
        rate_instruments: list[RateInstrument] | None = None,
        timeout: float = 30.0,
        cache: bool = True,
    ) -> None:
        self.risk_free_rate = risk_free_rate
        self.funding_spread = funding_spread
        self.dividend_yield = dividend_yield
        self.rate_instruments = rate_instruments
        self.timeout = timeout
        self.cache = cache

    def fetch(self, as_of: date, underlying: Underlying) -> RawMarketData:
        """Download (or read cached) the legacy bhavcopy and build a snapshot input."""
        actual, frame = latest_available_legacy(as_of, timeout=self.timeout, cache=self.cache)
        return parse_legacy_bhavcopy(
            frame,
            actual,
            underlying,
            risk_free_rate=self.risk_free_rate,
            funding_spread=self.funding_spread,
            dividend_yield=self.dividend_yield,
            rate_instruments=self.rate_instruments,
        )


# NSE switched the F&O bhavcopy to the UDiFF schema on 2024-07-08; before that only the
# legacy archive exists, after it only UDiFF is reliably published.
UDIFF_CUTOVER = date(2024, 7, 8)


def bhavcopy_source_for(as_of: date, **kwargs: object):
    """Return whichever bhavcopy source can actually serve ``as_of``.

    Callers that sweep across regimes (the validation harness) should not have to know where
    NSE moved the file in 2024.
    """
    from spdt.data.ingest.nse_bhavcopy import NseBhavcopySource

    if as_of < UDIFF_CUTOVER:
        return NseHistoricalSource(**kwargs)  # type: ignore[arg-type]
    return NseBhavcopySource(**kwargs)  # type: ignore[arg-type]
