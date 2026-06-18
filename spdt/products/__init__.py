"""L3 Product Definition Framework: the payoff DSL and the product catalog."""

from spdt.products.catalog import Autocallable
from spdt.products.graph import Cashflow, PathSet, PriceResult, Product, present_value
from spdt.products.primitives import CashOrNothingDigital, DownBarrierPut, EuropeanOption
from spdt.products.termsheet import TermSheet

__all__ = [
    "Autocallable",
    "CashOrNothingDigital",
    "Cashflow",
    "DownBarrierPut",
    "EuropeanOption",
    "PathSet",
    "PriceResult",
    "Product",
    "TermSheet",
    "present_value",
]
