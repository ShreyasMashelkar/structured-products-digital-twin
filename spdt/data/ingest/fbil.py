"""FBIL rate inputs: build calibrating instruments from published benchmarks (design doc §2.2).

FBIL (Financial Benchmarks India) publishes the daily T-bill curve (91/182/364-day) and the
MIBOR-OIS par rates that anchor the rupee risk-free curve. This module turns those published
quotes into :class:`~spdt.data.curate.rate_bootstrap.RateInstrument` objects ready for the
bootstrap; the short end (≤1y) comes in as simple-interest T-bills, the longer end as OIS par
swaps.

Values can be supplied manually (``fbil_instruments``) or fetched **live** from FBIL's public
``wasdm`` JSON API (``fetch_fbil_ois_instruments`` / ``fetch_fbil_tbill_instruments``), which
serves the MIBOR-OIS and T-bill curves anonymously (the site's own ``authenticated=false``
path). Tenors ≤ 1y are single-period money-market quotes (bootstrapped as zeros); yearly OIS
tenors are coupon-bearing par swaps.
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.request
from collections.abc import Mapping
from datetime import date, datetime, timedelta

from spdt.data.curate.rate_bootstrap import RateInstrument

_FBIL_BASE = "https://www.fbil.org.in/wasdm"
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0"

try:  # certifi's CA bundle for robust TLS (see also the NSE source)
    import certifi

    _SSL_CONTEXT: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover
    _SSL_CONTEXT = None

_DAYS_PER_YEAR = 365.0
_DAYS_PER_MONTH = _DAYS_PER_YEAR / 12.0


def fbil_instruments(
    anchor: date,
    *,
    tbill_yields: Mapping[int, float],
    ois_par_rates: Mapping[float, float],
) -> list[RateInstrument]:
    """Assemble bootstrap instruments from FBIL T-bill yields and OIS par rates.

    ``tbill_yields`` is keyed by tenor in **days** (e.g. ``{91: 0.0665, 182: 0.067}``);
    ``ois_par_rates`` by tenor in **years** (e.g. ``{1: 0.067, 2: 0.068, 5: 0.069}``).
    """
    instruments = [
        RateInstrument(anchor + timedelta(days=days), rate, kind="zero")
        for days, rate in tbill_yields.items()
    ]
    instruments += [
        RateInstrument(anchor + timedelta(days=round(365 * years)), rate, kind="ois")
        for years, rate in ois_par_rates.items()
    ]
    return sorted(instruments, key=lambda x: x.maturity)


# --- live FBIL API -----------------------------------------------------------------------

def _tenor_to_days(name: str) -> tuple[int, bool]:
    """Parse an FBIL tenor label to ``(days, is_yearly)`` — e.g. '6 Months'→(182,False), '2Y'."""
    match = re.match(r"\s*(\d+)\s*(days?|months?|m|y)\b", name.strip(), re.IGNORECASE)
    if not match:
        raise ValueError(f"unrecognised FBIL tenor {name!r}")
    n, unit = int(match.group(1)), match.group(2).lower()
    if unit.startswith("d"):
        return n, False
    if unit == "y":
        return round(n * _DAYS_PER_YEAR), True
    return round(n * _DAYS_PER_MONTH), False  # "m" or "month(s)"


def instruments_from_fbil_entries(entries: list[dict], anchor: date) -> list[RateInstrument]:
    """Convert FBIL JSON rows (``tenorName``, ``rate`` in %) into bootstrap instruments.

    Tenors ≤ 1y become single-period zeros; yearly tenors become coupon-bearing OIS swaps.
    Duplicate tenors (FBIL publishes two runs) keep the first occurrence.
    """
    seen: set[str] = set()
    instruments: list[RateInstrument] = []
    for row in entries:
        tenor = str(row["tenorName"]).strip()
        if tenor in seen:
            continue
        seen.add(tenor)
        days, is_yearly = _tenor_to_days(tenor)
        instruments.append(
            RateInstrument(
                maturity=anchor + timedelta(days=days),
                rate=float(row["rate"]) / 100.0,  # FBIL quotes percent
                kind="ois" if is_yearly else "zero",
            )
        )
    return sorted(instruments, key=lambda x: x.maturity)


def _download_fbil(resource: str, *, timeout: float) -> list[dict]:
    url = f"{_FBIL_BASE}/{resource}/fetch?authenticated=false"
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(  # noqa: S310 (fixed FBIL host)
        request, timeout=timeout, context=_SSL_CONTEXT
    ) as response:
        return json.loads(response.read())


def _run_date(entries: list[dict]) -> date:
    return datetime.strptime(entries[0]["processRunDate"][:10], "%Y-%m-%d").date()


def fetch_fbil_ois_instruments(*, timeout: float = 30.0) -> tuple[date, list[RateInstrument]]:
    """Download the latest published MIBOR-OIS curve and build bootstrap instruments."""
    entries = _download_fbil("miborois", timeout=timeout)
    anchor = _run_date(entries)
    return anchor, instruments_from_fbil_entries(entries, anchor)


def fetch_fbil_tbill_instruments(*, timeout: float = 30.0) -> tuple[date, list[RateInstrument]]:
    """Download the latest published T-bill curve and build bootstrap instruments (all zeros)."""
    entries = _download_fbil("tbill", timeout=timeout)
    anchor = _run_date(entries)
    return anchor, instruments_from_fbil_entries(entries, anchor)
