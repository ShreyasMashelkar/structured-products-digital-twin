"""L15 Risk Decomposition Engine: decompose any product into typed, hedgeable risk components.

Every structured product — autocallable, BRC, worst-of, capital-protected — is first
decomposed into its constituent risks (barrier, digital, vanilla, funding, correlation)
before the replication engine (Phase 2) assigns hedge instruments.  This is the foundational
abstraction that separates *what risks a product carries* from *how those risks are hedged*.

Quick start::

    from spdt.decomposition import decompose
    from spdt.products.catalog import Autocallable

    note = Autocallable(notional=100, observation_times=(0.25, 0.5, 0.75, 1.0),
                        coupon_rate=0.03, knock_in=0.6)
    result = decompose(note)
    for c in result.components:
        print(f"{c.component_type:30s}  hedge: {c.hedge_strategy}")

Output::

    funding                         hedge: curve_hedge
    coupon_conditional              hedge: digital_replication
    barrier_knock_in_put            hedge: semi_static_replication
    autocall                        hedge: digital_strip_replication
"""

from spdt.decomposition.components import (
    AutocallComponent,
    BarrierComponent,
    CorrelationComponent,
    CouponComponent,
    DigitalComponent,
    ForwardComponent,
    FundingComponent,
    RiskComponent,
    VanillaComponent,
)
from spdt.decomposition.decomposer import (
    Decomposition,
    RiskDecompositionEngine,
    decompose,
    get_engine,
)

__all__ = [
    "AutocallComponent",
    "BarrierComponent",
    "CorrelationComponent",
    "CouponComponent",
    "Decomposition",
    "DigitalComponent",
    "ForwardComponent",
    "FundingComponent",
    "RiskComponent",
    "RiskDecompositionEngine",
    "VanillaComponent",
    "decompose",
    "get_engine",
]
