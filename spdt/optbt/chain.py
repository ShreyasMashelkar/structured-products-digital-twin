"""Point-in-time option chain snapshot.

Mirrors ``spdt.core.snapshot.MarketSnapshot``'s discipline: immutable, content-hashed, and
carrying enough provenance that a backtest result can state how much of it was real.

``mark_provenance`` has three states, and the transition is one-way:

    "settlement"  raw exchange print, not yet validated — untradeable   (set by ChainLoader)
    "traded"      the contract traded that day; the print is a market   (set by SurfaceMarker)
    "surface"     no trade; the mark is model-derived from the surface  (set by SurfaceMarker)

Any ``"settlement"`` surviving into the backtest loop is a bug, not a state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class OptionKey:
    """Identity of one option contract."""

    underlying: str
    expiry: date
    strike: float
    is_call: bool


@dataclass(frozen=True)
class OptionQuoteView:
    """One contract as the engine sees it: the print, the mark, and where the mark came from."""

    key: OptionKey
    settlement_price: float
    contracts_traded: float
    open_interest: float
    bid: float | None
    ask: float | None
    traded: bool
    mark: float
    mark_provenance: str  # "settlement" | "traded" | "surface"
    implied_vol: float | None


@dataclass(frozen=True)
class OptionChainSnapshot:
    """Every listed contract for one underlying on one date."""

    as_of: date
    underlying: str
    spot: float
    quotes: Mapping[OptionKey, OptionQuoteView]
    surface: Any  # spdt.vol.surface.VolSurface — None until SurfaceMarker runs
    ois_curve: Any  # spdt.core.types.Curve — None when a flat rate is used
    dividend_yield: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "quotes", MappingProxyType(dict(self.quotes)))

    @property
    def traded_fraction(self) -> float:
        """Fraction of listed contracts that actually traded — the honesty diagnostic."""
        if not self.quotes:
            return 0.0
        return sum(1 for v in self.quotes.values() if v.traded) / len(self.quotes)

    def strikes_for(self, expiry: date) -> list[float]:
        """Sorted, deduplicated strikes listed for ``expiry``."""
        return sorted({k.strike for k in self.quotes if k.expiry == expiry})

    def get(self, key: OptionKey) -> OptionQuoteView | None:
        return self.quotes.get(key)

    @cached_property
    def content_hash(self) -> str:
        """SHA-256 over economic contents, independent of insertion order."""
        rows = sorted(
            (k.expiry.isoformat(), k.strike, k.is_call, v.mark, v.mark_provenance, v.traded)
            for k, v in self.quotes.items()
        )
        blob = json.dumps(
            {"as_of": self.as_of.isoformat(), "underlying": self.underlying,
             "spot": self.spot, "rows": rows},
            sort_keys=True, separators=(",", ":"),
        )
        return hashlib.sha256(blob.encode()).hexdigest()
