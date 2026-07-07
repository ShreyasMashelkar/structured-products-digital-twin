"""Greek Reallocation Engine.

Instead of looking at the Greeks of the full product (which blends vanilla delta with
complex exotic risks), we decouple them. The Reallocation Engine maps the Greeks of the
Replication Portfolio to the Delta 1 desk, and calculates the unhedged residual risk
to keep on the Exotics desk.
"""

from __future__ import annotations

from dataclasses import dataclass

from spdt.greeks.bump import GreekSet
from spdt.replication.portfolio import HedgeInstrument


@dataclass(frozen=True)
class ReallocatedGreeks:
    """The split of Greeks between liquid hedges and exotic residuals."""

    total_product_greeks: GreekSet
    hedge_portfolio_greeks: GreekSet
    residual_exotic_greeks: GreekSet


class GreekReallocator:
    """Reallocates total product Greeks into hedge-able vs exotic risk."""

    @staticmethod
    def aggregate_hedge_greeks(
        instrument_greeks: dict[HedgeInstrument, GreekSet]
    ) -> GreekSet:
        """Sum the Greeks of the individual hedge instruments."""
        delta = 0.0
        gamma = 0.0
        vega = 0.0
        rho = 0.0

        for instr, greeks in instrument_greeks.items():
            delta += greeks.delta * instr.weight
            gamma += greeks.gamma * instr.weight
            vega += greeks.vega * instr.weight
            rho += greeks.rho * instr.weight

        return GreekSet(delta=delta, gamma=gamma, vega=vega, rho=rho)

    @classmethod
    def reallocate(
        cls,
        total_greeks: GreekSet,
        instrument_greeks: dict[HedgeInstrument, GreekSet]
    ) -> ReallocatedGreeks:
        """Split the total Greeks into hedge vs residual."""

        hedge_greeks = cls.aggregate_hedge_greeks(instrument_greeks)

        residual = GreekSet(
            delta=total_greeks.delta - hedge_greeks.delta,
            gamma=total_greeks.gamma - hedge_greeks.gamma,
            vega=total_greeks.vega - hedge_greeks.vega,
            rho=total_greeks.rho - hedge_greeks.rho,
        )

        return ReallocatedGreeks(
            total_product_greeks=total_greeks,
            hedge_portfolio_greeks=hedge_greeks,
            residual_exotic_greeks=residual,
        )
