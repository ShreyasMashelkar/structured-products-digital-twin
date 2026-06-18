"""Closed-form prices used as Monte-Carlo benchmarks (L4)."""

from spdt.pricing.analytic.black_scholes import bs_vanilla
from spdt.pricing.analytic.digital import bs_cash_or_nothing

__all__ = ["bs_cash_or_nothing", "bs_vanilla"]
