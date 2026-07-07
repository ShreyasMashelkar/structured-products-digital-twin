"""Recalibration state machine.

Manages the daily evaluation cycle for a replication portfolio:
1. Evaluate tracking error.
2. Evaluate barrier-hit probability and surface drift.
3. Emit an action recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from spdt.decomposition.components import BarrierComponent, RiskComponent
from spdt.replication.portfolio import ReplicationPortfolio
from spdt.semistatic.monitor import ReplicationMonitor, MonitorSnapshot
from spdt.semistatic.pre_unwind import PreUnwindOptimizer, UnwindRecommendation
from spdt.semistatic.probability import BarrierProbabilityEngine


class RecalibrationActionType(Enum):
    NO_ACTION = "no_action"
    RECOMPUTE_GREEKS = "recompute_greeks"
    REBUILD_HEDGE = "rebuild_hedge"
    PRE_UNWIND = "pre_unwind"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class RecalibrationAction:
    action_type: RecalibrationActionType
    rationale: str
    snapshot: MonitorSnapshot | None = None
    unwind: UnwindRecommendation | None = None


class RecalibrationManager:
    """The daily state machine for replication maintenance."""

    def __init__(self, monitor: ReplicationMonitor, p_hit_threshold_unwind: float = 0.5):
        self.monitor = monitor
        self.p_hit_threshold_unwind = p_hit_threshold_unwind

    def evaluate(
        self,
        component: RiskComponent,
        portfolio: ReplicationPortfolio,
        model: Any,
        current_unwound_fraction: float = 0.0,
        time_elapsed: float = 0.0,
    ) -> RecalibrationAction:
        """Evaluate the component and portfolio under the current model to determine the next action."""

        # 1. Check tracking error
        snapshot = self.monitor.evaluate(component, portfolio, model)

        # 2. Knock-outs can be progressively unwound. Knock-ins instead become a vanilla
        # exposure once breached and must transition to that hedge, not be closed outright.
        if isinstance(component, BarrierComponent):
            r = model.r
            q = getattr(model, 'q', 0.0)

            p_hit = BarrierProbabilityEngine.p_hit(
                spot=model.spot,
                barrier=component.barrier * component.fixing(model.spot),
                sigma=model.sigma,
                t=max(component.expiry - time_elapsed, 0.0),
                r=r,
                q=q,
                is_down=(not component.is_call),
            )

            barrier_level = component.barrier * component.fixing(model.spot)
            breached = model.spot <= barrier_level if not component.is_call else model.spot >= barrier_level
            if component.knock_in and breached:
                return RecalibrationAction(
                    action_type=RecalibrationActionType.REBUILD_HEDGE,
                    rationale="Knock-in activated; replace the conditional strip with vanilla exposure.",
                    snapshot=snapshot,
                )

            if not component.knock_in and p_hit >= self.p_hit_threshold_unwind:
                unwind = PreUnwindOptimizer.recommend(p_hit, portfolio, current_unwound_fraction)
                if unwind.unwind_fraction > 0.0:
                    return RecalibrationAction(
                        action_type=RecalibrationActionType.PRE_UNWIND,
                        rationale=f"P(hit) {p_hit:.1%} exceeded threshold. Unwind {unwind.unwind_fraction:.1%}.",
                        snapshot=snapshot,
                        unwind=unwind,
                    )

        # 3. If tracking error is breached, rebuild
        if snapshot.rebuild_recommended:
            return RecalibrationAction(
                action_type=RecalibrationActionType.REBUILD_HEDGE,
                rationale=f"Tracking error {snapshot.tracking_error:.2f} exceeded threshold.",
                snapshot=snapshot,
            )

        # 4. Otherwise, just recompute Greeks and carry on
        return RecalibrationAction(
            action_type=RecalibrationActionType.RECOMPUTE_GREEKS,
            rationale="Within tolerances.",
            snapshot=snapshot,
        )
