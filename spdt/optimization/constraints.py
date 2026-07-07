"""Constraints for the Hedge Optimization Engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HedgeConstraints:
    """Constraints applied when solving for the optimal hedge portfolio."""

    max_notional_per_instrument: float = 1_000_000.0
    max_total_notional: float = 5_000_000.0
    delta_limit: float = 10_000.0        # Residual delta allowed
    vega_limit: float = 10_000.0         # Residual vega allowed
    gamma_limit: float = 10_000.0        # Residual gamma allowed
    allow_short_selling: bool = True     # If False, weights must be >= 0
