"""Transaction cost and market impact models."""

from __future__ import annotations


def linear_transaction_cost(weight: float, bid_offer_spread: float = 0.001) -> float:
    """Simple linear transaction cost based on half spread."""
    return abs(weight) * (bid_offer_spread / 2.0)


def quadratic_market_impact(weight: float, liquidity_depth: float = 1_000_000.0) -> float:
    """Almgren-Chriss style quadratic market impact.

    The larger the weight relative to the market depth, the more the price moves against us.
    Cost is proportional to the square of the size.
    """
    return (weight ** 2) / liquidity_depth
