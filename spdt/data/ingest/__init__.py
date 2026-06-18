"""L1 ingestion: raw market-data sources and the shape they all produce.

Every source — real (NSE bhavcopy, FBIL) or fallback (synthetic) — emits the same
immutable :class:`RawMarketData` for a business date. Curation and snapshot-building
downstream depend only on this shape, never on where it came from; the provenance tag on
the raw data records that distinction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from spdt.core.types import SourceTag, Underlying


@dataclass(frozen=True)
class RawOptionQuote:
    """One option contract's settlement print from the F&O bhavcopy."""

    expiry: date
    strike: float
    is_call: bool
    settlement_price: float


@dataclass(frozen=True)
class RawMarketData:
    """Everything a single source provides for one underlying on one business date.

    Rates are supplied as **continuously-compounded zero rates** at pillar dates. Real
    sources bootstrap these from traded FBIL/T-bill instruments (W1); the synthetic source
    supplies them directly. The funding curve is given as a parametric spread over OIS
    (ADR-0002), i.e. a small set of spread knots.
    """

    date: date
    underlying: Underlying
    spot: float
    option_chain: tuple[RawOptionQuote, ...]
    ois_zero_rates: Mapping[date, float]
    funding_spread_knots: Mapping[date, float]
    dividend_yield: float
    source: SourceTag


class MarketDataSource(Protocol):
    """A source that can produce :class:`RawMarketData` for a date/underlying."""

    def fetch(self, as_of: date, underlying: Underlying) -> RawMarketData: ...


__all__ = ["MarketDataSource", "RawMarketData", "RawOptionQuote"]
