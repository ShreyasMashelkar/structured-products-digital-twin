"""Netting Engine: compute netting benefits across the portfolio."""

from __future__ import annotations

from dataclasses import dataclass

from spdt.greeks.bump import GreekSet


@dataclass(frozen=True)
class NettingBenefit:
    """The benefit of hedging the portfolio as a whole vs trade-by-trade."""

    gross_risk: GreekSet
    net_risk: GreekSet
    delta_netting_pct: float
    gamma_netting_pct: float
    vega_netting_pct: float


class NettingEngine:

    def compute_netting_benefit(self, gross: GreekSet, net: GreekSet) -> NettingBenefit:
        """Calculate how much risk perfectly offsets internally."""

        def pct(g: float, n: float) -> float:
            if g < 1e-6:
                return 0.0
            return (g - abs(n)) / g

        return NettingBenefit(
            gross_risk=gross,
            net_risk=net,
            delta_netting_pct=pct(gross.delta, net.delta),
            gamma_netting_pct=pct(gross.gamma, net.gamma),
            vega_netting_pct=pct(gross.vega, net.vega),
        )
