"""Decompose a Capital-Protected Note into risk components (exact).

The CPN is::

    CPN = ZeroCouponNote(protection · N) + participation · Call(strike, cap)

The investor is **long** a call (financed by giving up the coupon the zero-coupon bond would
otherwise have paid).  This decomposition is exact.
"""

from __future__ import annotations

from spdt.decomposition.components import (
    BarrierComponent,
    FundingComponent,
    RiskComponent,
    VanillaComponent,
)
from spdt.decomposition.decomposer import Decomposition
from spdt.products.catalog import CapitalProtectedNote
from spdt.products.graph import Leg


def decompose_capital_protected(product: CapitalProtectedNote) -> Decomposition:
    """Decompose a CPN into funding (protected principal) + participation call.

    Exact for a plain or capped note. A *shark-fin* (knock-out) note is not exact here: its
    participation is an up-and-out call, and representing it as a vanilla call plus a separate
    barrier component describes the risk without reproducing the payoff — the two legs are not
    additive, because the barrier extinguishes the very call it sits beside. The decomposition
    flags itself inexact so nothing downstream treats the sum as a price.
    """
    components: tuple[RiskComponent, ...] = (
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

    if product.knock_out is not None:
        # 3. The knock-out itself: an up-and-out on the participation. Emitted so the barrier
        #    book, hit-probability heatmap and pre-unwind scheduler can see and manage it —
        #    the same reason the autocall level is emitted as a barrier on the autocallable.
        components = components + (
            BarrierComponent(
                notional=product.notional * product.participation,
                expiry=product.maturity,
                underlying="NIFTY",
                direction=-1,  # the barrier works against the investor: it removes their gain
                leg=Leg.OPTION,
                initial_fixing=product.initial_fixing,
                strike=product.strike,
                barrier=product.knock_out,
                is_call=True,
                knock_in=False,
                monitoring=product.monitoring_times(),
                descriptive_only=True,  # the participation call above carries the hedging
            ),
        )
        return Decomposition(
            product_type="capital_protected_note",
            components=components,
            is_exact=False,
            notes=(
                f"Shark-fin CPN = ZCB(protection · N) + participation · UpAndOutCall(K, "
                f"KO {product.knock_out:.2f}) + rebate. Descriptive, not additive: the barrier "
                "extinguishes the call beside it, so the components do not sum to the payoff."
            ),
        )

    return Decomposition(
        product_type="capital_protected_note",
        components=components,
        is_exact=True,
        notes="CPN = ZCB(protection · N) + participation · Call(K, cap). "
              "Exact decomposition; the call is financed by foregoing the bond coupon.",
    )
