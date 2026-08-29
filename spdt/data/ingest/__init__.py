"""L1 ingestion: raw market-data sources and the shape they all produce.

Every source — real (NSE bhavcopy, FBIL) or fallback (synthetic) — emits the same
immutable :class:`RawMarketData` for a business date. Curation and snapshot-building
downstream depend only on this shape, never on where it came from; the provenance tag on
the raw data records that distinction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date as Date  # aliased: the RawMarketData.date field shadows the type
from typing import Protocol

from spdt.core.types import SourceTag, Underlying


@dataclass(frozen=True)
class RawOptionQuote:
    """One option contract's settlement print from the F&O bhavcopy.

    ``contracts_traded`` and ``open_interest`` are carried alongside the price because a
    settlement price is **not** evidence that anyone traded at it. The exchange publishes a
    settlement mark for every listed contract, including ones with zero volume and zero open
    interest, and those marks invert to implied vols that look entirely plausible while
    describing no market at all. Without volume the curation layer has no way to tell a real
    quote from a computed one; with it, the distinction is a filter (see
    :func:`spdt.data.curate.invert_chain`). Both default to 0.0 so sources that genuinely
    cannot supply them (synthetic, or a feed without the columns) still construct — but a zero
    then means "unknown", and a liquidity filter will correctly treat it as untradeable.
    """

    expiry: Date
    strike: float
    is_call: bool
    settlement_price: float
    contracts_traded: float = 0.0
    open_interest: float = 0.0
    # Two-sided market, where the source publishes one. NSE settlement files do not — they
    # carry a single mark — so these stay ``None`` there and every downstream cost model must
    # cope with their absence. CBOE does, which is what makes a spread-crossing cost (rather
    # than an assumed one) possible at all. ``None`` means "not published", which is a
    # different statement from a zero-width spread and must not be silently read as one.
    bid: float | None = None
    ask: float | None = None
    # Contract multiplier, where the source publishes an instrument master (XTS does; the NSE
    # bhavcopy does not). Zero means "unknown", and any caller sizing a real order must refuse
    # rather than assume: a wrong lot size silently misstates every quantity on a term sheet.
    lot_size: int = 0

    @property
    def mid(self) -> float:
        """Mid price when a two-sided market exists, else the settlement mark."""
        if self.bid is not None and self.ask is not None and self.ask >= self.bid > 0.0:
            return 0.5 * (self.bid + self.ask)
        return self.settlement_price

    @property
    def spread(self) -> float | None:
        """Absolute bid-ask spread, or ``None`` when the source publishes no two-sided market."""
        if self.bid is None or self.ask is None:
            return None
        return max(self.ask - self.bid, 0.0)

    @property
    def relative_spread(self) -> float | None:
        """Spread as a fraction of mid — the comparable liquidity measure across strikes.

        Deep out-of-the-money options routinely quote a spread wider than their own mid, which
        is exactly the signal that the "price" carries almost no information.
        """
        s, m = self.spread, self.mid
        return None if s is None or m <= 0.0 else s / m


@dataclass(frozen=True)
class RawMarketData:
    """Everything a single source provides for one underlying on one business date.

    Rates are supplied as **continuously-compounded zero rates** at pillar dates. Real
    sources bootstrap these from traded FBIL/T-bill instruments (W1); the synthetic source
    supplies them directly. The funding curve is given as a parametric spread over OIS
    (ADR-0002), i.e. a small set of spread knots.
    """

    date: Date
    underlying: Underlying
    spot: float
    option_chain: tuple[RawOptionQuote, ...]
    ois_zero_rates: Mapping[Date, float]
    funding_spread_knots: Mapping[Date, float]
    dividend_yield: float
    source: SourceTag


class MarketDataSource(Protocol):
    """A source that can produce :class:`RawMarketData` for a date/underlying."""

    def fetch(self, as_of: Date, underlying: Underlying) -> RawMarketData: ...


__all__ = ["MarketDataSource", "RawMarketData", "RawOptionQuote"]
