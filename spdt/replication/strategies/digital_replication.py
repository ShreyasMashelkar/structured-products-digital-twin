"""Call-spread replication for Digital components.

A cash-or-nothing digital has a discontinuous payoff (step function) and thus infinite gamma
at the strike at maturity. It is hedged in practice using a tight call spread (or put spread):

    Digital_Call(K) ≈ (1/dK) * [ Vanilla_Call(K - dK/2) - Vanilla_Call(K + dK/2) ]

The width ``dK`` (the overhedge) is chosen based on the desk's risk appetite: tighter means
better theoretical replication but higher transaction costs and local gamma; wider means lower
costs but leaves unhedged gap risk.
"""

from __future__ import annotations

from typing import Any

from spdt.decomposition.components import CouponComponent, DigitalComponent, RiskComponent
from spdt.products.primitives import EuropeanOption
from spdt.replication.portfolio import HedgeInstrument
from spdt.replication.strategies.base import AbstractReplicationStrategy


class DigitalReplicationStrategy(AbstractReplicationStrategy):
    """Call-spread or put-spread replication for digital components."""

    def __init__(self, relative_spread_width: float = 0.01):
        """
        Args:
            relative_spread_width: Width of the spread as a fraction of the strike (dK/K).
                                   1% is a typical institutional starting point.
        """
        self.spread_width = relative_spread_width

    def replicate(
        self, component: RiskComponent, model: Any, surface: Any = None
    ) -> tuple[HedgeInstrument, ...]:
        if isinstance(component, CouponComponent):
            if not component.is_conditional or component.barrier is None:
                raise TypeError("Expected a conditional CouponComponent")
            instruments: list[HedgeInstrument] = []
            for date in component.dates:
                digital = DigitalComponent(
                    notional=component.notional,
                    expiry=date,
                    underlying=component.underlying,
                    direction=component.direction,
                    leg=component.leg,
                    initial_fixing=component.initial_fixing,
                    strike=component.barrier,
                    payout=component.coupon_rate,
                    is_call=True,
                )
                instruments.extend(self.replicate(digital, model, surface))
            return tuple(instruments)
        if not isinstance(component, DigitalComponent):
            raise TypeError("Expected DigitalComponent or conditional CouponComponent")

        fixing = component.fixing(model.spot)
        strike = component.strike * fixing
        dk = strike * self.spread_width

        # We need the spread to pay 1 unit at maturity if we finish in the money.
        # A call spread pays max(S - K_low, 0) - max(S - K_high, 0).
        # The max payout is K_high - K_low = dK.
        # To get a payout of exactly `component.payout` (adjusted for notional and direction),
        # we need to hold `(payout / dK)` units of the spread.

        target_payout = component.payout * component.notional * component.direction
        units = target_payout / dk

        instruments = []

        if component.is_call:
            # Call spread: Long Call at K_low, Short Call at K_high
            k_low = strike - dk / 2.0
            k_high = strike + dk / 2.0

            long_leg = EuropeanOption(strike=k_low, expiry=component.expiry, is_call=True)
            short_leg = EuropeanOption(strike=k_high, expiry=component.expiry, is_call=True)

            instruments.append(
                HedgeInstrument(
                    instrument=long_leg,
                    weight=units,
                    instrument_type="vanilla_call",
                    purpose="call_spread_long",
                )
            )
            instruments.append(
                HedgeInstrument(
                    instrument=short_leg,
                    weight=-units,
                    instrument_type="vanilla_call",
                    purpose="call_spread_short",
                )
            )
        else:
            # Put spread: Long Put at K_high, Short Put at K_low
            k_low = strike - dk / 2.0
            k_high = strike + dk / 2.0

            long_leg = EuropeanOption(strike=k_high, expiry=component.expiry, is_call=False)
            short_leg = EuropeanOption(strike=k_low, expiry=component.expiry, is_call=False)

            instruments.append(
                HedgeInstrument(
                    instrument=long_leg,
                    weight=units,
                    instrument_type="vanilla_put",
                    purpose="put_spread_long",
                )
            )
            instruments.append(
                HedgeInstrument(
                    instrument=short_leg,
                    weight=-units,
                    instrument_type="vanilla_put",
                    purpose="put_spread_short",
                )
            )

        return tuple(instruments)
