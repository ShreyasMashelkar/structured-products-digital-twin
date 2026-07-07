"""Desk Router.

Routes aggregated Greek risks to the appropriate trading desks.
- Vanilla Delta and Vega -> Delta 1 / Vanilla Options Desk
- Curve Risk -> Funding / XVA Desk
- Residual Exotic Greeks (unhedged gamma/vega) -> Exotics Desk
"""

from __future__ import annotations

from dataclasses import dataclass
from spdt.greeks.bump import GreekSet
from spdt.greeks.reallocation import ReallocatedGreeks


@dataclass(frozen=True)
class DeskRoutingSlip:
    """The final risk allocation per desk."""
    delta_1_desk: GreekSet
    vanilla_options_desk: GreekSet
    exotics_desk: GreekSet
    funding_desk: GreekSet


class DeskRouter:
    """Routes reallocated Greeks to specific trading desks."""

    @classmethod
    def route(cls, reallocated: ReallocatedGreeks) -> DeskRoutingSlip:
        """
        Routes the risks based on standard institutional mapping:
        - Hedge Portfolio Delta -> Delta 1 Desk
        - Hedge Portfolio Vega/Gamma -> Vanilla Options Desk
        - Residual Greeks -> Exotics Desk
        - (Rho would go to Funding Desk, but we simplify here)
        """

        hedge = reallocated.hedge_portfolio_greeks
        residual = reallocated.residual_exotic_greeks

        delta_1 = GreekSet(delta=hedge.delta, gamma=0.0, vega=0.0, rho=0.0)
        vanilla = GreekSet(delta=0.0, gamma=hedge.gamma, vega=hedge.vega, rho=0.0)

        # Funding takes the interest rate risk from the hedge
        funding = GreekSet(delta=0.0, gamma=0.0, vega=0.0, rho=hedge.rho)

        # Exotics owns the mismatch
        exotics = residual

        return DeskRoutingSlip(
            delta_1_desk=delta_1,
            vanilla_options_desk=vanilla,
            exotics_desk=exotics,
            funding_desk=funding,
        )
