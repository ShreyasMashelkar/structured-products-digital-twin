"""NSE F&O + cash bhavcopy source — the real backbone (design doc §2.2). STUBBED.

Architecturally present behind the :class:`~spdt.data.ingest.MarketDataSource` interface so
the rest of the system is already wired for real data; the download/parse implementation is
a declared placeholder (scope-contract: STUBBED). When implemented (W1), ``fetch`` will:

1. Download the daily F&O and cash bhavcopy ZIPs from the NSE archive for ``as_of``.
2. Parse per-contract option settlement prices, the underlying close, OI and volume.
3. Apply the trading-calendar + corporate-action adjustments.
4. Pair with the FBIL-bootstrapped OIS curve and issuer funding spread.

It deliberately raises rather than silently returning synthetic data — falling back is a
caller's explicit choice (use :class:`~spdt.data.ingest.synthetic.SyntheticSource`), never a
hidden default, per the "never silently mix" rule (§2.4).
"""

from __future__ import annotations

from datetime import date

from spdt.core.types import Underlying
from spdt.data.ingest import RawMarketData


class NseBhavcopySource:
    """Real EOD bhavcopy source. Network ingestion not yet implemented (W1)."""

    ARCHIVE_BASE = "https://nsearchives.nseindia.com"

    def fetch(self, as_of: date, underlying: Underlying) -> RawMarketData:
        raise NotImplementedError(
            "NSE bhavcopy ingestion is a declared stub (scope-contract: STUBBED); "
            "use SyntheticSource for offline runs until W1 implements the downloader."
        )
