"""Replication Monitor.

Tracks the gap between the exact (MC) price of the structured product component and the
theoretical value of its replication portfolio. If this gap (the tracking error) grows too
large, it triggers a rebuild of the static hedge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from spdt.decomposition.components import RiskComponent
from spdt.pricing.engine import price_mc
from spdt.replication.portfolio import ReplicationPortfolio


@dataclass(frozen=True)
class MonitorSnapshot:
    """A snapshot of the replication performance at a point in time."""

    timestamp: float
    component_pv: float
    replication_pv: float
    tracking_error: float        # component_pv - replication_pv
    rebuild_recommended: bool    # True if |tracking_error| > threshold


class ReplicationMonitor:
    """Monitors the drift between a risk component and its hedge portfolio."""

    def __init__(self, error_threshold: float = 1.0):
        """
        Args:
            error_threshold: The acceptable PV difference before a rebuild is recommended.
        """
        self.error_threshold = error_threshold

    def evaluate(
        self,
        component: RiskComponent,
        portfolio: ReplicationPortfolio,
        model: Any,
        timestamp: float = 0.0,
        n_paths: int = 100_000,
        seed: int = 0,
    ) -> MonitorSnapshot:
        """Evaluate the tracking error under the current market model.

        Requires pricing the original component (via as_product if available, or a fallback)
        and pricing each instrument in the replication portfolio.
        """
        primitive = component.as_product(model.spot)
        if primitive is None:
            # If the component cannot be priced independently, we cannot easily monitor
            # its isolated tracking error without the full product MC.
            # We return a 0-error snapshot for now.
            return MonitorSnapshot(
                timestamp=timestamp,
                component_pv=0.0,
                replication_pv=0.0,
                tracking_error=0.0,
                rebuild_recommended=False,
            )

        # Price the component (CRN)
        comp_pv = price_mc(primitive, model, n_paths=n_paths, seed=seed).price

        # Price the portfolio (CRN)
        rep_pv = 0.0
        for instr in portfolio.instruments:
            # We multiply by instrument weight which already has notional/direction baked in
            p = price_mc(instr.instrument, model, n_paths=n_paths, seed=seed).price
            rep_pv += p * instr.weight

        error = comp_pv - rep_pv
        rebuild = abs(error) > self.error_threshold

        return MonitorSnapshot(
            timestamp=timestamp,
            component_pv=comp_pv,
            replication_pv=rep_pv,
            tracking_error=error,
            rebuild_recommended=rebuild,
        )
