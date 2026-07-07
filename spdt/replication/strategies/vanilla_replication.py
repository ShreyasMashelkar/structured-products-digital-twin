"""Pass-through replication for Vanilla components.

Vanilla options (calls and puts) do not need complex static replication; they *are* the liquid
instruments. The strategy simply maps the component 1:1 to a HedgeInstrument, which the desk
will then delta-hedge or hold against inventory.
"""

from __future__ import annotations

from typing import Any

from spdt.decomposition.components import RiskComponent, VanillaComponent
from spdt.products.primitives import EuropeanOption
from spdt.replication.portfolio import HedgeInstrument
from spdt.replication.strategies.base import AbstractReplicationStrategy


class VanillaReplicationStrategy(AbstractReplicationStrategy):
    """Pass-through strategy: vanillas hedge themselves."""

    def replicate(
        self, component: RiskComponent, model: Any, surface: Any = None
    ) -> tuple[HedgeInstrument, ...]:
        if not isinstance(component, VanillaComponent):
            raise TypeError("Expected VanillaComponent")

        fixing = component.fixing(model.spot)
        strike = component.strike * fixing

        primitive = EuropeanOption(
            strike=strike, expiry=component.expiry, is_call=component.is_call
        )

        instr_type = "vanilla_call" if component.is_call else "vanilla_put"

        quantity = component.notional * component.direction / fixing
        instruments = [
            HedgeInstrument(
                instrument=primitive,
                weight=quantity,
                instrument_type=instr_type,
                purpose="vanilla_pass_through",
            )
        ]
        if component.cap is not None:
            if not component.is_call or component.cap <= component.strike:
                raise ValueError("A cap is only supported for calls with cap > strike")
            instruments.append(
                HedgeInstrument(
                    instrument=EuropeanOption(component.cap * fixing, component.expiry, True),
                    weight=-quantity,
                    instrument_type="vanilla_call",
                    purpose="vanilla_cap",
                )
            )
        return tuple(instruments)
