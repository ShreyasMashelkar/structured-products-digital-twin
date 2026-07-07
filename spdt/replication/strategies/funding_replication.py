"""Curve hedge mapping for Funding and Coupon components.

Zero-coupon bonds and fixed cashflows carry only interest-rate (curve) risk.
For an equity exotics desk, these are typically passed through directly to the central
funding desk. The replication engine outputs a descriptive "funding" instrument that
represents the cash flow.
"""

from __future__ import annotations

from typing import Any

from spdt.decomposition.components import CouponComponent, FundingComponent, RiskComponent
from spdt.replication.portfolio import HedgeInstrument
from spdt.replication.strategies.base import AbstractReplicationStrategy


class FundingReplicationStrategy(AbstractReplicationStrategy):
    """Maps funding and fixed coupon components to zero-coupon bond instruments."""

    def replicate(
        self, component: RiskComponent, model: Any, surface: Any = None
    ) -> tuple[HedgeInstrument, ...]:
        if not isinstance(component, (FundingComponent, CouponComponent)):
            raise TypeError("Expected FundingComponent or CouponComponent")

        # Convert the component to its underlying product primitive (ZeroCouponLeg or FixedCouponLeg)
        primitive = component.as_product()
        if primitive is None:
            # Conditional coupons (path-dependent) cannot be trivially curve-hedged here.
            # They must be routed through digital replication if decomposed individually.
            return ()

        # For fixed cashflows, the instrument is just the leg itself, which the desk
        # treats as a pure interest rate exposure.
        return (
            HedgeInstrument(
                instrument=primitive,
                weight=1.0,  # weight is 1.0 because the notional/direction are baked into as_product()
                instrument_type="cashflow",
                purpose="curve_hedge",
            ),
        )
