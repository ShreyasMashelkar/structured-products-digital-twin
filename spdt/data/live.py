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
from spdt.data.ingest.fbil import fetch_fbil_ois_instruments
from spdt.data.ingest.nse_bhavcopy import NseBhavcopySource
from spdt.data.snapshot_builder import build_snapshot


def fetch_live_raw(
    as_of: date,
    underlying: str = "NIFTY",
    *,
    dividend_yield: float = 0.013,
    funding_spread: float = 0.012,
    timeout: float = 30.0,
) -> RawMarketData:
    """Fetch the raw live market data (NSE option chain + FBIL-bootstrapped rates) for ``as_of``.

    Hits the network. The NSE F&O bhavcopy source walks back to the latest *published* EOD file, so
    this works any time of day (mid-session it serves the previous close). Exposed separately from
    :func:`build_live_snapshot` so callers that also need the raw option chain (e.g. surface
    calibration) don't have to fetch it twice.
    """
    _, rate_instruments = fetch_fbil_ois_instruments(anchor=as_of, timeout=timeout)
    engine = NseBhavcopySource(
        dividend_yield=dividend_yield, funding_spread=funding_spread,
        rate_instruments=rate_instruments, timeout=timeout,
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
