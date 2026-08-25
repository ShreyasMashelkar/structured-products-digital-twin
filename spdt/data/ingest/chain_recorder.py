"""Record the live two-sided NIFTY option chain from XTS.

Why this module exists: the NSE F&O bhavcopy carries a single settlement mark per contract —
no bid, no ask. XTS publishes bid/ask **live only**; no broker offers a historical quote
endpoint. So the only way to ever own real NSE option spread data is to record it as it
happens. Every session not recorded is spread data gone forever; a historical options
backtest's cost model can only be calibrated against what this module captures.

Storage is one parquet file per trading day under ``data/chain_archive/`` (gitignored — the
recorded dataset is proprietary and, unlike code, cannot be reconstructed by anyone later).

# ponytail: touchline only (best bid/ask). XTS message code 1502 adds 5-level depth —
# switch _TOUCHLINE_CODE usage in ``XTSMarketDataClient.quotes`` if depth-aware impact
# modelling ever becomes the binding constraint.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from spdt.data.ingest.xts import InstrumentRef

_DEFAULT_BATCH = 25  # instruments per quotes() call — keep requests small and boring


@dataclass(frozen=True)
class ChainRecord:
    """One option contract's two-sided market at one instant."""

    as_of_ts: datetime  # exchange LastUpdateTime — stale for quiet strikes, and that's data
    poll_ts: datetime  # when WE polled — group snapshots by this, never by as_of_ts
    underlying: str
    expiry: date
    strike: float
    is_call: bool
    bid: float | None
    ask: float | None
    bid_qty: float | None
    ask_qty: float | None
    ltp: float | None
    stale: bool  # recorded, not dropped — an absent market is itself liquidity data


class _QuoteClient(Protocol):
    def quotes(self, instruments, *, now=None, max_age_s: float = 300.0): ...


def in_market_hours(now_ist: datetime) -> bool:
    """Mon–Fri 09:15–15:35 IST (mirrors the desk archiver's window)."""
    return now_ist.weekday() < 5 and (9, 15) <= (now_ist.hour, now_ist.minute) <= (15, 35)


def select_chain(
    master: list[InstrumentRef], underlying: str, *, n_expiries: int = 3
) -> list[InstrumentRef]:
    """Every listed option on ``underlying`` in the nearest ``n_expiries`` expiries.

    All strikes are kept deliberately: the far wings' (absent) markets are exactly the
    liquidity evidence a cost model needs.
    """
    # The expiry travels with the ref so the not-None filter is carried in the value: the
    # comprehension's narrowing does not survive into the later set, and an undated contract
    # must never reach sorted().
    dated = [
        (r.expiry, r) for r in master
        if r.symbol == underlying and r.option_type in ("CE", "PE") and r.expiry is not None
    ]
    keep = set(sorted({e for e, _ in dated})[:n_expiries])
    return [r for e, r in dated if e in keep]


def record_chain(
    client: _QuoteClient,
    refs: list[InstrumentRef],
    *,
    batch_size: int = _DEFAULT_BATCH,
    now: datetime | None = None,
) -> list[ChainRecord]:
    """Fetch touchline quotes for ``refs`` (chunked) and normalise to records.

    Quote payloads come back keyed by instrument id only, so contract terms are joined
    from the master refs. Stale quotes are recorded with their flag, never dropped.
    """
    from datetime import timezone

    poll_ts = now or datetime.now(timezone.utc)
    by_id = {r.exchange_instrument_id: r for r in refs}
    records: list[ChainRecord] = []
    for start in range(0, len(refs), batch_size):
        for q in client.quotes(refs[start:start + batch_size], now=now):
            ref = by_id.get(q.instrument.exchange_instrument_id)
            if ref is None or ref.expiry is None or q.timestamp is None:
                continue
            records.append(ChainRecord(
                as_of_ts=q.timestamp,
                poll_ts=poll_ts,
                underlying=ref.symbol,
                expiry=ref.expiry,
                strike=float(ref.strike or 0.0),
                is_call=ref.option_type == "CE",
                bid=q.bid, ask=q.ask, bid_qty=q.bid_qty, ask_qty=q.ask_qty,
                ltp=q.ltp, stale=q.stale,
            ))
    return records


def write_records(records: list[ChainRecord], root: Path) -> Path:
    """Append ``records`` to the parquet file for their trading date."""
    import pandas as pd

    if not records:
        raise ValueError("no records to write")
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"chain_{records[0].poll_ts.date().isoformat()}.parquet"
    frame = pd.DataFrame([asdict(r) for r in records])
    if path.exists():
        frame = pd.concat([pd.read_parquet(path), frame], ignore_index=True)
    frame.to_parquet(path, index=False)
    return path


def read_records(root: Path) -> list[ChainRecord]:
    """Every recorded chain under ``root``, oldest file first."""
    import pandas as pd

    frames = [pd.read_parquet(p) for p in sorted(root.glob("chain_*.parquet"))]
    if not frames:
        return []
    rows = pd.concat(frames, ignore_index=True).to_dict("records")
    for row in rows:  # parquet round-trips dates as pandas timestamps
        row["as_of_ts"] = pd.Timestamp(row["as_of_ts"]).to_pydatetime()
        row["poll_ts"] = pd.Timestamp(row["poll_ts"]).to_pydatetime()
        row["expiry"] = pd.Timestamp(row["expiry"]).date()
    return [ChainRecord(**row) for row in rows]
