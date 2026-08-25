"""One-call live snapshot: real NSE options + real FBIL rates (L1).

Ties the two live sources together — NSE F&O bhavcopy for the option chain and spot, FBIL's
MIBOR-OIS curve for the bootstrapped risk-free rates — into a single fully-observed
:class:`~spdt.core.snapshot.MarketSnapshot`. Both fetches hit the network, so this is for
real runs (not CI); the underlying components are unit-tested offline.
"""

from __future__ import annotations

from datetime import date

from spdt.core.snapshot import MarketSnapshot
from spdt.data.ingest import RawMarketData
from spdt.data.ingest.dhan import DhanSource
from spdt.data.ingest.fbil import fetch_fbil_ois_instruments
from spdt.data.ingest.nse_bhavcopy import NseBhavcopySource
from spdt.data.ingest.xts import XTSMarketDataClient, XTSSource
from spdt.data.snapshot_builder import build_snapshot

_fbil_cache: dict[date, list] = {}  # per-process: FBIL's curve is published daily


# US parameters. The rate is no longer a typed-in constant: it is read from the Treasury daily
# par-yield curve, bootstrapped to zeros, at the tenor most representative of the notes priced
# here (~2y). Still a single number into a source that models one flat rate — the curve *shape*
# is carried by spdt.data.ingest.ust for consumers that can use it (BlackScholesHW takes the
# full zero curve) — but the level now tracks the market instead of the day the constant was
# written. The dividend yield remains the broad-market level for indices; a single stock gets
# 0.0 rather than an index yield it does not pay.
_US_DIVIDEND_YIELD = 0.013
_usd_rate_cache: dict[date, float] = {}


def _usd_rate(as_of: date) -> float:
    """The ~2y USD zero, fetched once per day; falls back to the old constant offline."""
    if as_of not in _usd_rate_cache:
        try:
            from spdt.data.ingest.ust import usd_zero_curve

            curve = usd_zero_curve(as_of)
            pillar = min(curve, key=lambda t: abs(t - 2.0))
            _usd_rate_cache.clear()
            _usd_rate_cache[as_of] = curve[pillar]
        except Exception:  # noqa: BLE001 - offline runs still price, on the documented fallback
            _usd_rate_cache[as_of] = 0.042
    return _usd_rate_cache[as_of]
_US_INDICES = frozenset({"SPX", "SPY", "NDX", "QQQ", "RUT", "DIA"})


def fetch_live_raw(
    as_of: date,
    underlying: str = "NIFTY",
    *,
    dividend_yield: float = 0.013,
    funding_spread: float = 0.012,
    timeout: float = 30.0,
    source: str = "bhavcopy",
) -> RawMarketData:
    """Fetch the raw live market data (NSE option chain + FBIL-bootstrapped rates) for ``as_of``.

    Hits the network. ``source`` picks the option-chain engine:

    * ``"bhavcopy"`` (default) — NSE's public EOD F&O bhavcopy; walks back to the latest *published*
      file, so it works any time of day (mid-session it serves the previous close).
    * ``"dhan"`` — DhanHQ's live intraday option-chain API (needs ``DHAN_CLIENT_ID`` /
      ``DHAN_ACCESS_TOKEN``); an authenticated broker feed, so it isn't IP-blocked like the public
      NSE endpoints.

    * ``"xts"`` — Symphony XTS market data; the live intraday broker feed the desk runs on.
    * ``"cboe"`` — **US** chains (SPX, SPY, or any listed single name) from CBOE's delayed-quote
      feed. Two-sided markets with real open interest out past five years, which is the tenor
      range Indian exchange data cannot reach: after screening for contracts that actually
      traded, no NIFTY source supports a reliable quote past ~1.4 years, while SPX fits at
      ~24bps out to 5.3. Tenor, not fit quality, is why this source exists.

    The Indian sources pair with FBIL-bootstrapped rates. ``cboe`` does **not**: an INR
    MIBOR-OIS curve has no business discounting a USD payoff, so it is dispatched before the
    FBIL fetch and carries a flat USD rate instead. That is a real simplification — a proper
    SOFR curve is the follow-up — but it is a defensible placeholder, whereas the INR curve
    would be simply wrong.

    Exposed separately from :func:`build_live_snapshot` so callers that also need the raw option
    chain (e.g. surface calibration) don't have to refetch.
    """
    if source == "cboe":
        from spdt.data.ingest.cboe import CboeSource

        return CboeSource(
            risk_free_rate=_usd_rate(as_of),
            funding_spread=funding_spread,
            dividend_yield=_US_DIVIDEND_YIELD if underlying in _US_INDICES else 0.0,
            timeout=max(timeout, 40.0),
        ).fetch(as_of, underlying)

    if as_of not in _fbil_cache:  # FBIL publishes a daily curve — one fetch per day is plenty
        _fbil_cache.clear()
        _fbil_cache[as_of] = fetch_fbil_ois_instruments(anchor=as_of, timeout=timeout)[1]
    rate_instruments = _fbil_cache[as_of]
    if source == "dhan":
        engine: NseBhavcopySource | DhanSource | XTSSource = DhanSource(
            dividend_yield=dividend_yield, funding_spread=funding_spread,
            rate_instruments=rate_instruments, timeout=timeout,
        )
    elif source == "bhavcopy":
        engine = NseBhavcopySource(
            dividend_yield=dividend_yield, funding_spread=funding_spread,
            rate_instruments=rate_instruments, timeout=timeout,
        )
    elif source == "xts":
        # the NSEFO instrument master is ~17MB — the default 30s request timeout is too
        # tight, and it only changes daily so cache it on disk between fetches
        from tempfile import gettempdir

        engine = XTSSource(
            client=XTSMarketDataClient(timeout=max(timeout, 300.0),
                                       master_cache_dir=gettempdir()),
            dividend_yield=dividend_yield, funding_spread=funding_spread,
            rate_instruments=rate_instruments,
        )
    else:
        raise ValueError(
            f"unknown live source {source!r} (use 'bhavcopy', 'dhan', 'xts' or 'cboe')"
        )
    return engine.fetch(as_of, underlying)


def build_live_snapshot(
    as_of: date,
    underlying: str = "NIFTY",
    *,
    dividend_yield: float = 0.013,
    funding_spread: float = 0.012,
    timeout: float = 30.0,
) -> MarketSnapshot:
    """Build a fully-observed snapshot from live NSE options and a live FBIL-bootstrapped curve.

    The OIS curve is bootstrapped from FBIL's MIBOR-OIS quotes anchored at ``as_of``. FBIL's
    public endpoint serves the latest published curve, so for historical ``as_of`` the rates
    are the most recent ones (point-in-time FBIL history via ``fetchfiltered`` is a refinement).
    """
    return build_snapshot(
        fetch_live_raw(
            as_of, underlying, dividend_yield=dividend_yield,
            funding_spread=funding_spread, timeout=timeout,
        )
    )
