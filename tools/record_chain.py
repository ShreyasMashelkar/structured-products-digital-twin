"""Record one snapshot of the live NIFTY option chain (bid/ask) to the local archive.

    python3 -m tools.record_chain            # no-op outside Mon–Fri 09:15–15:35 IST
    python3 -m tools.record_chain --force    # record regardless (testing)

Run every ~15 minutes by ``com.spdt.chainrecorder`` (launchd). Single-shot by design: each
run logs in, pulls the NSEFO master (per-day disk cache), quotes the nearest three NIFTY
expiries, appends to ``data/chain_archive/chain_YYYY-MM-DD.parquet``, and exits.

Why: bhavcopy has no bid/ask and no broker offers historical quotes — spreads not recorded
today are gone forever, and the options-backtest cost model can only be calibrated on this.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from tempfile import gettempdir
from zoneinfo import ZoneInfo

ARCHIVE_DIR = Path(os.environ.get("SPDT_CHAIN_ARCHIVE_DIR", "data/chain_archive"))
IST = ZoneInfo("Asia/Kolkata")


def main() -> None:
    from spdt.data.ingest.chain_recorder import (
        in_market_hours, record_chain, select_chain, write_records,
    )
    from spdt.data.ingest.xts import XTSMarketDataClient

    now = datetime.now(IST)
    if "--force" not in sys.argv and not in_market_hours(now):
        return  # quiet no-op: launchd fires around the clock, the market does not

    client = XTSMarketDataClient(timeout=300.0, master_cache_dir=gettempdir())
    client.login()
    # NIFTY expiries are weekly (Tuesdays): 6 expiries ≈ 5–6 weeks of tenor, covering the
    # 14–21 DTE contracts a fortnightly-rebalance strategy actually trades.
    refs = select_chain(client.instruments("NSEFO"), underlying="NIFTY", n_expiries=6)
    if not refs:
        sys.exit("no NIFTY options in the NSEFO master — master parse changed?")
    records = record_chain(client, refs)
    path = write_records(records, ARCHIVE_DIR)
    fresh = sum(1 for r in records if not r.stale)
    print(f"{now:%H:%M} recorded {len(records)} contracts ({fresh} live) -> {path}")


if __name__ == "__main__":
    main()
