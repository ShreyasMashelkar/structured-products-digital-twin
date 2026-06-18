"""TermSheet: the economic terms of a product instance (design doc §7).

A plain, immutable record of what was sold — consumed by both the pricer (via the catalog,
which turns it into a priceable :class:`~spdt.products.graph.Product`) and, later, the
documentation engine (L13) that renders the indicative term sheet. Times are stored as
year fractions to the as-of date so the record is self-contained for pricing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TermSheet:
    """Economic terms of a structured note."""

    product_type: str
    underlyings: tuple[str, ...]
    notional: float
    observation_times: tuple[float, ...]  # year fractions; last is maturity
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def maturity(self) -> float:
        return self.observation_times[-1]
