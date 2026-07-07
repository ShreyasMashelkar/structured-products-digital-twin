"""Decompose a Worst-of Autocallable into risk components (approximate).

The worst-of is the single-name autocallable run on ``minₐ Sₐ(t)/Kₐ`` plus a pure
**correlation component** — the dispersion the investor is short.  Lower correlation widens
the worst-performer distribution and increases knock-in probability; this is un-hedgeable
with single-name instruments and requires a dispersion trade.

    WorstOf ≈ Autocallable_components(on basket)
            + CorrelationComponent(underlyings, ρ)

The single-name components (barrier, coupons, autocall) are the same as the autocallable
decomposition but tagged with all underlyings.  The correlation component is additive.
"""

from __future__ import annotations

from spdt.decomposition.components import (
    AutocallComponent,
    BarrierComponent,
    CorrelationComponent,
    CouponComponent,
    FundingComponent,
)
from spdt.decomposition.decomposer import Decomposition
from spdt.products.catalog import WorstOfAutocallable
from spdt.products.graph import Leg


def decompose_worst_of(product: WorstOfAutocallable) -> Decomposition:
    """Approximate decomposition of a worst-of autocallable."""
    maturity = product.observation_times[-1]
    obs = product.observation_times
    autocall_dates = obs[:-1] if len(obs) > 1 else ()
    underlying_str = "/".join(product.underlyings) if product.underlyings else "BASKET"

    components = [
        # 1. Bond: par redemption at maturity.
        FundingComponent(
            notional=product.notional,
            expiry=maturity,
            underlying=underlying_str,
            direction=+1,
            leg=Leg.FUNDING,
        ),
        # 2. Conditional coupons on the basket.
        CouponComponent(
            notional=product.notional,
            expiry=maturity,
            underlying=underlying_str,
            direction=+1,
            leg=Leg.FUNDING,
            coupon_rate=product.coupon_rate,
            dates=obs,
            is_conditional=True,
            barrier=product.coupon_barrier,
            memory=product.memory,
        ),
        # 3. Short down-and-in put on the worst performer.
        BarrierComponent(
            notional=product.notional,
            expiry=maturity,
            underlying=underlying_str,
            direction=-1,
            leg=Leg.FUNDING,
            strike=1.0,
            barrier=product.knock_in,
            is_call=False,
            knock_in=True,
            monitoring=(maturity,),
        ),
        # 4. Correlation component: the pure dispersion risk.
        CorrelationComponent(
            notional=product.notional,
            expiry=maturity,
            underlying=underlying_str,
            direction=-1,  # investor is short correlation (short dispersion)
            leg=Leg.OPTION,
            underlyings=product.underlyings,
            correlation=0.0,  # filled at runtime from the correlation matrix
        ),
    ]

    # 5. Autocall triggers on the basket.
    if autocall_dates:
        components.append(
            AutocallComponent(
                notional=product.notional,
                expiry=maturity,
                underlying=underlying_str,
                direction=+1,
                leg=Leg.FUNDING,
                autocall_level=product.autocall_level,
                observation_dates=autocall_dates,
            ),
        )

    return Decomposition(
        product_type="worst_of_autocallable",
        components=tuple(components),
        is_exact=False,
        notes="Approximate decomposition. Same as single-name autocallable plus a pure "
              "correlation component capturing the dispersion the investor is short. "
              "Correlation risk cannot be hedged with single-name instruments.",
    )
