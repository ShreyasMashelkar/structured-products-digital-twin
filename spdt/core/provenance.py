"""Per-field provenance tagging (design doc §7, ADR-0001).

Every value in a ``MarketSnapshot`` carries a tag saying whether it was *observed* in the
market, *interpolated* from observed points, or *synthetic* (a declared fallback). This is
what lets a risk report state, e.g., "surface = 80% observed / 20% interpolated" rather than
presenting every number as if it were a hard market quote.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from spdt.core.types import SourceTag


@dataclass(frozen=True)
class Provenance:
    """An immutable map from field key to its :class:`SourceTag`.

    Keys are dotted paths into the snapshot, e.g. ``"spot.NIFTY"`` or
    ``"surface.NIFTY.2024-12-26"`` — the granularity is the caller's choice; this class
    only stores and summarises.
    """

    tags: Mapping[str, SourceTag]

    def tag(self, field: str) -> SourceTag:
        """Source tag for ``field``; raises ``KeyError`` if untagged."""
        return self.tags[field]

    def summary(self) -> dict[SourceTag, float]:
        """Fraction of tagged fields in each source bucket (empty map → empty dict)."""
        total = len(self.tags)
        if total == 0:
            return {}
        counts: dict[SourceTag, int] = {}
        for tag in self.tags.values():
            counts[tag] = counts.get(tag, 0) + 1
        return {tag: n / total for tag, n in counts.items()}
