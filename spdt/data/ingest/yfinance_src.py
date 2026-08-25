"""yfinance EOD index history — the long spot series the backtest runs on (README §2.2).

The project's primary data path is NSE bhavcopy + FBIL (:mod:`spdt.data.ingest.nse_bhavcopy`,
:mod:`spdt.data.ingest.nse_historical`, :mod:`spdt.data.ingest.fbil`), and that stays true: the
option chain and the curve — the parts that are hard to source and easy to get wrong — come
from the exchange and the benchmark administrator.

This source covers one thing those cannot cheaply provide: a *continuous multi-year daily close
series* for the index. Reconstructing 15 years of NIFTY closes from bhavcopy would mean ~3,700
separate archive downloads to extract one number from each. The realised-path backtest
(:mod:`spdt.validation.realized`) needs exactly that series and nothing else from it — no
option prices, no rates — so the weaker source is confined to the weakest requirement.

Scope contract: **spot history only**. Anything that touches a price the model calibrates to
must come from the exchange path. The returned series is tagged so downstream provenance
records which of the two it was.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

# NIFTY 50 on Yahoo. Kept as a mapping rather than a format string because ticker conventions
# are per-index and irregular (^NSEI, ^NSEBANK) — guessing them silently returns empty frames.
_YAHOO_TICKERS = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
}
_CACHE_DIR = Path("data/spot_history_cache")


def _cache_path(underlying: str, start: date, end: date) -> Path:
    return _CACHE_DIR / f"{underlying}_{start:%Y%m%d}_{end:%Y%m%d}.csv"


def yfinance_spot_history(
    underlying: str,
    start: date,
    end: date,
    *,
    cache: bool = True,
) -> pd.Series:
    """Daily close series for ``underlying`` between ``start`` and ``end`` inclusive.

    Returns a ``pd.Series`` indexed by ``datetime.date``. Cached on disk so a validation sweep
    hits the network once regardless of how many regimes replay the same history.

    Raises ``ValueError`` for an unmapped underlying — silently returning an empty series would
    let a backtest "pass" on no data at all, which is worse than failing.
    """
    if underlying not in _YAHOO_TICKERS:
        raise ValueError(
            f"no Yahoo ticker mapped for {underlying!r}; known: {sorted(_YAHOO_TICKERS)}"
        )

    path = _cache_path(underlying, start, end)
    if cache and path.exists():
        frame = pd.read_csv(path, parse_dates=["date"])
        return pd.Series(frame["close"].to_numpy(), index=[d.date() for d in frame["date"]])

    import yfinance as yf

    raw = yf.download(
        _YAHOO_TICKERS[underlying],
        start=start.isoformat(),
        end=end.isoformat(),
        progress=False,
        auto_adjust=False,
    )
    if raw.empty:
        raise ValueError(f"yfinance returned no data for {underlying} {start}..{end}")

    close = raw["Close"]
    if isinstance(close, pd.DataFrame):  # yfinance ≥0.2.51 returns column-multiindexed frames
        close = close.iloc[:, 0]
    series = pd.Series(
        close.to_numpy(dtype=float), index=[ts.date() for ts in close.index]
    ).dropna()

    if cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"date": series.index, "close": series.to_numpy()}).to_csv(path, index=False)
    return series


def spot_series_from(
    underlying: str, start: date, end: date, *, cache: bool = True
) -> np.ndarray:
    """Bare float array of closes — the shape :func:`spdt.backtest.roll_issuance` consumes."""
    return yfinance_spot_history(underlying, start, end, cache=cache).to_numpy(dtype=float)
