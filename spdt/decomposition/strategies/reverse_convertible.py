"""Decompose a Reverse Convertible into risk components (exact).

The RC is the barrier-free sibling of the BRC::

    RC = ZeroCouponNote(par) + FixedCoupon(c) − vanilla Put(strike)

No barrier, no knock-in — the investor's short put is always live, yielding a higher coupon.
This decomposition is exact.
"""

from __future__ import annotations

from spdt.decomposition.components import (
    CouponComponent,
    FundingComponent,
    VanillaComponent,
)
from spdt.decomposition.decomposer import Decomposition
from spdt.products.catalog import ReverseConvertible
from spdt.products.graph import Leg


def decompose_reverse_convertible(product: ReverseConvertible) -> Decomposition:
    """Exact decomposition of an RC into funding + coupons + short vanilla put."""
    maturity = product.observation_times[-1]

    components = (
        # 1. Zero-coupon bond: par at maturity.
        FundingComponent(
            notional=product.notional,
            expiry=maturity,
            underlying="NIFTY",
            direction=+1,
            leg=Leg.FUNDING,
        ),
        # 2. Fixed coupons: unconditional.
        CouponComponent(
            notional=product.notional,
            expiry=maturity,
            underlying="NIFTY",
            direction=+1,
            leg=Leg.FUNDING,
            coupon_rate=product.coupon_rate,
            dates=product.observation_times,
            is_conditional=False,
        ),
        # 3. Short vanilla put: the investor sold optionality (always live).
        VanillaComponent(
            notional=product.notional,
            expiry=maturity,
            underlying="NIFTY",
            direction=-1,  # investor is short the put
            leg=Leg.OPTION,
            initial_fixing=product.initial_fixing,
            strike=product.strike,
            is_call=False,
        ),
    )

    return Decomposition(
        product_type="reverse_convertible",
        components=components,
        is_exact=True,
        notes="RC = ZCB(par) + FixedCoupons(c) − vanilla_Put(K). "
              "Exact decomposition; the RC is the BRC's barrier-free limit.",
    )
