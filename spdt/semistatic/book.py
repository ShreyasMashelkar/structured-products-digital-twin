"""Barrier Book Manager.

Manages the full barrier book at the institutional level, providing inventory aggregation,
probability heatmaps, and cross-barrier exposure netting.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from spdt.book.book import Trade
from spdt.decomposition import decompose
from spdt.decomposition.components import BarrierComponent
from spdt.semistatic.probability import BarrierProbabilityEngine


@dataclass(frozen=True)
class BarrierExposure:
    """Aggregated exposure at a specific barrier level."""
    barrier_level: float
    total_notional: float
    p_hit: float


class BarrierBookManager:
    """Aggregates and monitors all barrier risks across a trading book."""

    def __init__(self, trades: list[Trade]):
        self.trades = trades
        self._barrier_components = self._extract_barriers()

    def _extract_barriers(self) -> list[tuple[Trade, BarrierComponent]]:
        """Extract all barrier components from the book."""
        barriers = []
        for trade in self.trades:
            # Note: For massive books, we would cache the decomposition
            d = decompose(trade.product)
            for comp in d.by_type("barrier_knock_in_put"):
                if isinstance(comp, BarrierComponent):
                    barriers.append((trade, comp))
            for comp in d.by_type("barrier_knock_out_put"):
                if isinstance(comp, BarrierComponent):
                    barriers.append((trade, comp))
            for comp in d.by_type("barrier_knock_in_call"):
                if isinstance(comp, BarrierComponent):
                    barriers.append((trade, comp))
            for comp in d.by_type("barrier_knock_out_call"):
                if isinstance(comp, BarrierComponent):
                    barriers.append((trade, comp))
        return barriers

    def get_barrier_clusters(self, model: Any, bin_size: float = 0.05) -> list[BarrierExposure]:
        """Aggregate barrier notionals into proximity clusters."""
        clusters: dict[float, float] = defaultdict(float)
        probability_weighted: dict[float, float] = defaultdict(float)
        gross_notional: dict[float, float] = defaultdict(float)

        s0 = model.spot
        r = model.r
        q = getattr(model, "q", 0.0)

        for trade, comp in self._barrier_components:
            # Bucket the barrier to the nearest bin_size fraction (e.g. 80%, 85%)
            relative_barrier = comp.barrier
            bin_edge = round(relative_barrier / bin_size) * bin_size

            # The direction flips the sign for short vs long
            signed_notional = comp.notional * comp.direction * trade.direction
            clusters[bin_edge] += signed_notional
            gross = abs(signed_notional)
            probability_weighted[bin_edge] += gross * BarrierProbabilityEngine.p_hit(
                spot=s0,
                barrier=comp.barrier * comp.fixing(s0),
                sigma=model.sigma,
                t=comp.expiry,
                r=r,
                q=q,
                is_down=not comp.is_call,
            )
            gross_notional[bin_edge] += gross

        # Build the exposures with current probabilities
        exposures = []
        for b_level, notional in sorted(clusters.items()):
            if abs(notional) < 1e-6:
                continue

            p_hit = probability_weighted[b_level] / gross_notional[b_level]
            exposures.append(
                BarrierExposure(
                    barrier_level=b_level,
                    total_notional=notional,
                    p_hit=p_hit
                )
            )

        return exposures
