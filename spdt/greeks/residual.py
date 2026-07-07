"""Residual Greek Calculator.

Given a pricing model, computes the exact residual Greeks (the "Tracking Error Greeks").
This uses finite difference or pathwise sensitivity to calculate the sensitivity of the
gap between the RiskComponent PV and the ReplicationPortfolio PV.
"""

from __future__ import annotations

from typing import Any

from spdt.decomposition.components import RiskComponent
from spdt.greeks.bump import GreekSet, bump_greeks
from spdt.replication.portfolio import HedgeInstrument, ReplicationPortfolio
from spdt.greeks.reallocation import GreekReallocator, ReallocatedGreeks


class ResidualGreekCalculator:
    """Calculates the residual Greeks by directly pricing the product and its hedge."""

    def __init__(self, rel_spot_bump: float = 1e-2):
        self.rel_spot_bump = rel_spot_bump

    def calculate_instrument_greeks(
        self, portfolio: ReplicationPortfolio, model: Any, n_paths: int = 100_000, seed: int = 0
    ) -> dict[HedgeInstrument, GreekSet]:
        """Calculate the Greeks for each instrument in the replication portfolio."""
        results = {}
        for instr in portfolio.instruments:
            greeks = bump_greeks(
                instr.instrument,
                model,
                n_paths=n_paths,
                seed=seed,
                rel_spot_bump=self.rel_spot_bump
            )
            results[instr] = greeks
        return results

    def calculate_residual(
        self,
        component: RiskComponent,
        portfolio: ReplicationPortfolio,
        model: Any,
        n_paths: int = 100_000,
        seed: int = 0,
    ) -> ReallocatedGreeks:
        """Calculate the full reallocation split for a component and its hedge."""

        primitive = component.as_product(model.spot)

        if primitive is None:
            # Cannot independently bump a component with no primitive (e.g. conditional cashflow)
            return ReallocatedGreeks(
                GreekSet(0.0, 0.0, 0.0, 0.0),
                GreekSet(0.0, 0.0, 0.0, 0.0),
                GreekSet(0.0, 0.0, 0.0, 0.0),
            )

        # Get primitive greeks
        prim_greeks = bump_greeks(
            primitive,
            model,
            n_paths=n_paths,
            seed=seed,
            rel_spot_bump=self.rel_spot_bump
        )

        instrument_greeks = self.calculate_instrument_greeks(portfolio, model, n_paths, seed)

        return GreekReallocator.reallocate(prim_greeks, instrument_greeks)
