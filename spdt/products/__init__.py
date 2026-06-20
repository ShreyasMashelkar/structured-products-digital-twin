"""L3 Product Definition Framework: the payoff DSL and the product catalog."""

from spdt.products.catalog import (
    Autocallable,
    BarrierReverseConvertible,
    CapitalProtectedNote,
    ReverseConvertible,
    WorstOfAutocallable,
)
from spdt.products.graph import (
    Cashflow,
    Discount,
    Discounter,
    Leg,
    PathSet,
    PriceResult,
    Product,
    present_value,
)
from spdt.products.legs import (
    CompositeNote,
    FixedCouponLeg,
    ParticipationCallLeg,
    ShortDownInPutLeg,
    ZeroCouponLeg,
    brc_from_legs,
    capital_protected_from_legs,
)
from spdt.products.primitives import CashOrNothingDigital, DownBarrierPut, EuropeanOption
from spdt.products.termsheet import TermSheet

__all__ = [
    "Autocallable",
    "BarrierReverseConvertible",
    "CapitalProtectedNote",
    "CashOrNothingDigital",
    "Cashflow",
    "CompositeNote",
    "Discount",
    "Discounter",
    "DownBarrierPut",
    "EuropeanOption",
    "FixedCouponLeg",
    "Leg",
    "ParticipationCallLeg",
    "PathSet",
    "PriceResult",
    "Product",
    "ReverseConvertible",
    "WorstOfAutocallable",
    "ShortDownInPutLeg",
    "TermSheet",
    "ZeroCouponLeg",
    "brc_from_legs",
    "capital_protected_from_legs",
    "present_value",
]
