"""Decompose a Capital-Protected Note into risk components (exact).

The CPN is::

    CPN = ZeroCouponNote(protection · N) + participation · Call(strike, cap)

The investor is **long** a call (financed by giving up the coupon the zero-coupon bond would
otherwise have paid).  This decomposition is exact.
"""

from __future__ import annotations

from spdt.decomposition.components import FundingComponent, VanillaComponent
from spdt.decomposition.decomposer import Decomposition
from spdt.products.catalog import CapitalProtectedNote
from spdt.products.graph import Leg


def decompose_capital_protected(product: CapitalProtectedNote) -> Decomposition:
    """Exact decomposition of a CPN into funding (protected principal) + participation call."""
    components = (
        # 1. Zero-coupon bond: protected fraction of notional at maturity.
        FundingComponent(
            notional=product.notional * product.protection,
            expiry=product.maturity,
            underlying="NIFTY",
            direction=+1,
            leg=Leg.FUNDING,
        ),
        # 2. Long participation call: the upside the investor bought.
        VanillaComponent(
            notional=product.notional * product.participation,
            expiry=product.maturity,
            underlying="NIFTY",
            direction=+1,  # investor is long the call
            leg=Leg.OPTION,
            initial_fixing=product.initial_fixing,
            strike=product.strike,
            is_call=True,
            cap=product.cap,
        ),
    )

    return Decomposition(
        product_type="capital_protected_note",
        components=components,
        is_exact=True,
        notes="CPN = ZCB(protection · N) + participation · Call(K, cap). "
              "Exact decomposition; the call is financed by foregoing the bond coupon.",
    )
