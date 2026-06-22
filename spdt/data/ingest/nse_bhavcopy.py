"""NSE F&O bhavcopy source — real EOD ingestion (design doc §2.2).

Downloads the daily **UDiFF common bhavcopy** for the F&O segment from the NSE archive,
parses every option contract's settlement price for the requested underlying, and emits a
:class:`~spdt.data.ingest.RawMarketData`. The underlying spot comes from the bhavcopy's own
``UndrlygPric`` column, so no second download is needed for the index level.

Download and parse are deliberately separated: :func:`parse_fo_bhavcopy` is a pure function
over a DataFrame (unit-tested on a sample of the real schema), while :meth:`fetch` adds the
network I/O. NSE serves these archives over a CDN that accepts a browser-like ``User-Agent``.

Rates: this source pairs the observed option chain with a **flat** OIS/funding curve built
from the constructor's ``risk_free_rate`` / ``funding_spread``. Bootstrapping the FBIL OIS and
T-bill curve (design doc §2.2) is the remaining refinement and slots in by replacing
``_rate_inputs`` — the option surface, which is the hard-to-source part, is already real.
"""

from __future__ import annotations

import io
import ssl
import urllib.error
import urllib.request
import zipfile
from datetime import date, timedelta

import pandas as pd

try:  # use certifi's CA bundle when present — robust across machines (esp. macOS python.org)
    import certifi

    _SSL_CONTEXT: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover - falls back to the system default trust store
    _SSL_CONTEXT = None

from spdt.core.types import SourceTag, Underlying
from spdt.data.curate.rate_bootstrap import RateInstrument, bootstrap_zero_rates
from spdt.data.ingest import RawMarketData, RawOptionQuote

_ARCHIVE = "https://nsearchives.nseindia.com"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def fo_bhavcopy_url(as_of: date) -> str:
    """URL of the UDiFF F&O common bhavcopy ZIP for ``as_of``."""
    return f"{_ARCHIVE}/content/fo/BhavCopy_NSE_FO_0_0_0_{as_of:%Y%m%d}_F_0000.csv.zip"


def download_fo_bhavcopy(as_of: date, *, timeout: float = 30.0) -> pd.DataFrame:
    """Fetch and unzip the F&O bhavcopy for ``as_of`` into a DataFrame (network I/O)."""
    request = urllib.request.Request(fo_bhavcopy_url(as_of), headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(  # noqa: S310 (fixed NSE archive host)
        request, timeout=timeout, context=_SSL_CONTEXT
    ) as response:
        payload = response.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = archive.namelist()[0]
        with archive.open(name) as handle:
            return pd.read_csv(handle)


def latest_available_bhavcopy(
    as_of: date, *, max_lookback: int = 7, timeout: float = 30.0
) -> tuple[date, pd.DataFrame]:
    """The most recent published F&O bhavcopy on or before ``as_of`` — walks back over 404s.

    Intraday (before today's EOD file publishes) and on weekends/holidays the exact-date file is a
    404; this returns the latest *available* one, so a live build mid-session serves the previous
    close's full chain. Returns ``(actual_date, frame)`` — the actual file date anchors the curve.
    """
    last_error: Exception | None = None
    for back in range(max_lookback + 1):
        d = as_of - timedelta(days=back)
        if d.weekday() >= 5:  # skip Sat/Sun
            continue
        try:
            return d, download_fo_bhavcopy(d, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            last_error = e
    raise FileNotFoundError(
        f"no F&O bhavcopy published in the {max_lookback} days before {as_of}"
    ) from last_error


def parse_fo_bhavcopy(
    frame: pd.DataFrame,
    as_of: date,
    underlying: Underlying,
    *,
    risk_free_rate: float,
    funding_spread: float,
    dividend_yield: float,
    rate_instruments: list[RateInstrument] | None = None,
) -> RawMarketData:
    """Turn a UDiFF F&O bhavcopy DataFrame into :class:`RawMarketData` for one underlying.

    Keeps the call/put option rows for ``underlying`` with a positive settlement price and reads
    the spot from ``UndrlygPric``. If ``rate_instruments`` (FBIL T-bills/OIS) are supplied the
    OIS curve is **bootstrapped** from them; otherwise a flat ``risk_free_rate`` is used.
    """
    frame = frame.rename(columns=lambda c: c.strip())
    is_option = frame["OptnTp"].isin(["CE", "PE"])
    rows = frame[(frame["TckrSymb"] == underlying) & is_option].copy()
    if rows.empty:
        raise ValueError(f"no option rows for {underlying!r} in the {as_of} bhavcopy")

    rows["XpryDt"] = pd.to_datetime(rows["XpryDt"]).dt.date
    rows = rows[rows["SttlmPric"] > 0.0]

    quotes = tuple(
        RawOptionQuote(
            expiry=r.XpryDt,
            strike=float(r.StrkPric),
            is_call=(r.OptnTp == "CE"),
            settlement_price=float(r.SttlmPric),
        )
        for r in rows.itertuples(index=False)
    )
    spot = float(rows["UndrlygPric"].dropna().iloc[0])

    if rate_instruments:
        ois_zero_rates = bootstrap_zero_rates(as_of, rate_instruments)
    else:
        ois_zero_rates = {e: risk_free_rate for e in sorted({q.expiry for q in quotes})}
    pillars = sorted(ois_zero_rates)
    funding_spread_knots = {pillars[0]: funding_spread, pillars[-1]: funding_spread}

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


class NseBhavcopySource:
    """Real EOD F&O bhavcopy source implementing the ``MarketDataSource`` interface."""

    def __init__(
        self,
        *,
        risk_free_rate: float = 0.065,
        funding_spread: float = 0.012,
        dividend_yield: float = 0.013,
        rate_instruments: list[RateInstrument] | None = None,
        timeout: float = 30.0,
        fallback_to_latest: bool = True,
    ) -> None:
        self.risk_free_rate = risk_free_rate
        self.funding_spread = funding_spread
        self.dividend_yield = dividend_yield
        self.rate_instruments = rate_instruments
        self.timeout = timeout
        self.fallback_to_latest = fallback_to_latest

    def fetch(self, as_of: date, underlying: Underlying) -> RawMarketData:
        """Download the F&O bhavcopy and build a snapshot input.

        With ``fallback_to_latest`` (the default) the most recent *published* file on or before
        ``as_of`` is used — so a live build runs intraday/weekends off the previous close.
        """
        if self.fallback_to_latest:
            actual, frame = latest_available_bhavcopy(as_of, timeout=self.timeout)
        else:
            actual, frame = as_of, download_fo_bhavcopy(as_of, timeout=self.timeout)
        return parse_fo_bhavcopy(
            frame,
            actual,
            underlying,
            risk_free_rate=self.risk_free_rate,
            funding_spread=self.funding_spread,
            dividend_yield=self.dividend_yield,
            rate_instruments=self.rate_instruments,
        )
