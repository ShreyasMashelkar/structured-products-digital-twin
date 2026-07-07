"""Decompose an Autocallable / Phoenix into risk components (approximate).

The autocallable is path-dependent: the autocall kills subsequent coupons and the terminal
barrier.  A trader nonetheless decomposes it for risk management purposes:

    Autocallable ≈ Bond(par)
                  + Conditional_Coupons(N × digital at coupon_barrier)
                  + Autocall_Triggers(N−1 × digital at autocall_level)
                  − Down-and-In Put(knock_in, maturity)

This decomposition is **approximate** — the components are not independent because the
autocall trigger at date t_i kills all flows after t_i.  The purpose is not exact pricing
(that happens through MC on the monolithic product) but **risk identification**: telling the
replication engine that the product's main hedgeable risks are a barrier put, a strip of
conditional digitals, and a strip of autocall digitals.
"""

from __future__ import annotations

from spdt.decomposition.components import (
    AutocallComponent,
    BarrierComponent,
    CouponComponent,
    FundingComponent,
)
from spdt.decomposition.decomposer import Decomposition
from spdt.products.catalog import Autocallable
from spdt.products.graph import Leg


def decompose_autocallable(product: Autocallable) -> Decomposition:
    """Approximate decomposition of an autocallable into its hedgeable risk components."""
    maturity = product.observation_times[-1]
    obs = product.observation_times
    # Autocall can fire on every obs date except the last (at maturity, principal is just
    # returned or knocked in — there's no "early" redemption on the final date).
    autocall_dates = obs[:-1] if len(obs) > 1 else ()

    components = [
        # 1. Bond: par redemption at maturity (conditional on surviving to maturity, but
        #    for risk decomposition we treat it as the base funding exposure).
        FundingComponent(
            notional=product.notional,
            expiry=maturity,
            underlying="NIFTY",
            direction=+1,
            leg=Leg.FUNDING,
        ),
        # 2. Conditional coupons: digital options at each obs date, paying coupon_rate · N
        #    if spot ≥ coupon_barrier · S₀.  Memory feature is captured in the component.
        CouponComponent(
            notional=product.notional,
            expiry=maturity,
            underlying="NIFTY",
            direction=+1,
            leg=Leg.FUNDING,
            initial_fixing=product.initial_fixing,
            coupon_rate=product.coupon_rate,
            dates=obs,
            is_conditional=True,
            barrier=product.coupon_barrier,
            memory=product.memory,
        ),
        # 3. Short down-and-in put: the knock-in at maturity.  Only fires if spot ≤ KI · S₀
        #    at the final date *and* the note was not autocalled.
        BarrierComponent(
            notional=product.notional,
            expiry=maturity,
            underlying="NIFTY",
            direction=-1,
            leg=Leg.FUNDING,  # KI loss reduces the principal (funding leg)
            initial_fixing=product.initial_fixing,
            strike=1.0,  # put struck at par (S₀)
            barrier=product.knock_in,
            is_call=False,
            knock_in=True,
            monitoring=(maturity,),  # terminal-only monitoring for the knock-in
        ),
    ]

    # 4. Autocall triggers: on each non-terminal obs date, a digital that redeems at par
    #    if spot ≥ autocall_level · S₀.  These are path-dependent (conditional on the note
    #    being alive), so they are descriptive, not independently priceable.
    if autocall_dates:
        components.append(
            AutocallComponent(
                notional=product.notional,
                expiry=maturity,
                underlying="NIFTY",
                direction=+1,
                leg=Leg.FUNDING,
                initial_fixing=product.initial_fixing,
                autocall_level=product.autocall_level,
                observation_dates=autocall_dates,
            ),
        )

    return Decomposition(
        product_type="autocallable",
        components=tuple(components),
        is_exact=False,
        notes="Approximate decomposition. Components are not independent: the autocall "
              "trigger at t_i kills all subsequent flows. Pricing uses the full MC product; "
              "this decomposition identifies the hedgeable risk components for the "
              "replication engine.",
    )
