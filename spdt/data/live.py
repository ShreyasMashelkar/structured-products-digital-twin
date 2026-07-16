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

    Both pair with FBIL-bootstrapped rates. Exposed separately from :func:`build_live_snapshot` so
    callers that also need the raw option chain (e.g. surface calibration) don't have to refetch.
    """
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
        raise ValueError(f"unknown live source {source!r} (use 'bhavcopy', 'dhan' or 'xts')")
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
