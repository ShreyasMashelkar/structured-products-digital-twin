"""Decompose a Barrier Reverse Convertible into risk components (exact).

The BRC is the cleanest decomposition in the catalog — it maps directly to the three-leg
identity proven in ``spdt.products.legs``::

    BRC = ZeroCouponNote(par) + FixedCoupon(c) − DownAndIn_Put(strike, barrier)

This decomposition is **exact**: the sum of component PVs equals the monolithic BRC PV on
every path, to floating-point tolerance.  The existing ``legs.py`` proves this numerically;
here we produce the same decomposition as typed :class:`RiskComponent` objects that the
replication engine can consume.
"""

from __future__ import annotations

from spdt.decomposition.components import (
    BarrierComponent,
    CouponComponent,
    FundingComponent,
)
from spdt.decomposition.decomposer import Decomposition
from spdt.products.catalog import BarrierReverseConvertible
from spdt.products.graph import Leg


def decompose_brc(product: BarrierReverseConvertible) -> Decomposition:
    """Exact decomposition of a BRC into funding + coupons + short barrier put."""
    maturity = product.observation_times[-1]
    monitoring = product.barrier_monitoring or product.observation_times

    components = (
        # 1. Zero-coupon bond: par redemption at maturity (funding curve).
        FundingComponent(
            notional=product.notional,
            expiry=maturity,
            underlying="NIFTY",
            direction=+1,
            leg=Leg.FUNDING,
        ),
        # 2. Fixed coupons: unconditional payments on each observation date (funding curve).
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
        # 3. Short down-and-in put: the optionality the investor has sold (OIS curve).
        #    The issuer is *long* this option (they benefit from the knock-in), so from the
        #    issuer's perspective direction = +1 (asset), but the cashflow is negative for the
        #    investor, so the product tags it as a short position.
        BarrierComponent(
            notional=product.notional,
            expiry=maturity,
            underlying="NIFTY",
            direction=-1,  # investor is short the put
            leg=Leg.OPTION,
            initial_fixing=product.initial_fixing,
            strike=product.strike,
            barrier=product.knock_in,
            is_call=False,
            knock_in=True,
            monitoring=monitoring,
        ),
    )

    return Decomposition(
        product_type="barrier_reverse_convertible",
        components=components,
        is_exact=True,
        notes="BRC = ZCB(par) + FixedCoupons(c) − DI_Put(K, H). "
              "Mirrors the legs.py identity; sum of component PVs = product PV.",
    )
