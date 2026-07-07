"""Trader Decision Engine: analyzes risks and recommends concrete trading actions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from spdt.desk.aggregator import EndOfDayRiskReport
from spdt.greeks.routing import DeskRoutingSlip


class Action(Enum):
    """Specific recommendations output by the engine."""

    NO_ACTION = "no_action"
    DELTA_HEDGE = "delta_hedge"
    VEGA_HEDGE = "vega_hedge"
    BARRIER_PRE_UNWIND = "barrier_pre_unwind"
    REBUILD_REPLICATION = "rebuild_replication"
    RECALIBRATE_MODEL = "recalibrate_model"
    INCREASE_BID_OFFER = "increase_bid_offer"
    REJECT_TRADE = "reject_trade"
    INCREASE_MODEL_RESERVE = "increase_model_reserve"
    ESCALATE_TO_RISK = "escalate_to_risk"


@dataclass(frozen=True)
class Decision:
    """A recommended action with an institutional justification."""

    action: Action
    reason: str
    urgency: int  # 1 (low) to 5 (high)
    metric_value: float | None = None
    metric_name: str | None = None


class TraderDecisionEngine:
    """Expert system evaluating risk reports against institutional risk limits."""

    def __init__(
        self,
        delta_limit: float = 1_000_000.0,
        vega_limit: float = 500_000.0,
        residual_gamma_limit: float = 100_000.0,
    ):
        self.delta_limit = delta_limit
        self.vega_limit = vega_limit
        self.residual_gamma_limit = residual_gamma_limit

    def evaluate_eod_risk(self, report: EndOfDayRiskReport) -> list[Decision]:
        """Review the EOD risk report and output required trader actions."""
        decisions: list[Decision] = []
        slip: DeskRoutingSlip = report.net_desk_routing

        # 1. Delta 1 Hedge Check
        net_delta = abs(slip.delta_1_desk.delta)
        if net_delta > self.delta_limit:
            decisions.append(
                Decision(
                    action=Action.DELTA_HEDGE,
                    reason=f"Net Delta ({net_delta:,.0f}) exceeds desk limit ({self.delta_limit:,.0f}). Execute futures hedge.",
                    urgency=4,
                    metric_value=net_delta,
                    metric_name="Net Delta",
                )
            )

        # 2. Vanilla Flow Options Hedge Check
        net_vega = abs(slip.vanilla_options_desk.vega)
        if net_vega > self.vega_limit:
            decisions.append(
                Decision(
                    action=Action.VEGA_HEDGE,
                    reason=f"Net Vega ({net_vega:,.0f}) exceeds desk limit. Buy/Sell vanilla straddles.",
                    urgency=3,
                    metric_value=net_vega,
                    metric_name="Net Vega",
                )
            )

        # 3. Exotics Tracking Error Check
        net_residual_gamma = abs(slip.exotics_desk.gamma)
        if net_residual_gamma > self.residual_gamma_limit:
            decisions.append(
                Decision(
                    action=Action.REBUILD_REPLICATION,
                    reason="Unhedgeable gap risk (Residual Gamma) is dangerously high. Re-optimize the static hedge portfolio (e.g., add more strikes).",
                    urgency=5,
                    metric_value=net_residual_gamma,
                    metric_name="Residual Gamma",
                )
            )

        if not decisions:
            decisions.append(
                Decision(
                    action=Action.NO_ACTION,
                    reason="All risks are within desk limits. P&L attribution looks clean.",
                    urgency=1,
                )
            )

        # Sort by urgency descending
        return sorted(decisions, key=lambda d: d.urgency, reverse=True)
