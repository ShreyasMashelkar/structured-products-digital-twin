"""L9 Hedging Engine: dynamic delta/vega hedge simulation and residual P&L."""

from spdt.hedging.delta_vega import (
    HedgeResult,
    VegaHedgeResult,
    simulate_delta_hedge,
    simulate_delta_vega_hedge,
)

__all__ = [
    "HedgeResult",
    "VegaHedgeResult",
    "simulate_delta_hedge",
    "simulate_delta_vega_hedge",
]
