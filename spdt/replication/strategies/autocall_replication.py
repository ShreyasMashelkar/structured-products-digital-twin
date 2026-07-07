"""Digital strip replication for Autocall components.

An autocall feature is economically equivalent to a strip of path-dependent digital options,
one for each observation date. If triggered, the note redeems at par.

The replication engine treats these as individual digital components and delegates to the
digital replication strategy (call spreads). However, because they are path-dependent
(a later trigger only fires if all earlier triggers did *not* fire), the hedge ratio must be
dynamically weighted by the probability of surviving to that date. This is an approximate,
bucketed hedge.
"""

from __future__ import annotations

from typing import Any

from spdt.decomposition.components import AutocallComponent, DigitalComponent, RiskComponent
from spdt.replication.portfolio import HedgeInstrument
from spdt.replication.strategies.base import AbstractReplicationStrategy
from spdt.replication.strategies.digital_replication import DigitalReplicationStrategy


class AutocallReplicationStrategy(AbstractReplicationStrategy):
    """Replicates an autocall trigger via a strip of call spreads."""

    def __init__(self, relative_spread_width: float = 0.01):
        self.digital_strategy = DigitalReplicationStrategy(relative_spread_width)

    def replicate(
        self, component: RiskComponent, model: Any, surface: Any = None
    ) -> tuple[HedgeInstrument, ...]:
        if not isinstance(component, AutocallComponent):
            raise TypeError("Expected AutocallComponent")

        instruments = []

        # For a full risk-managed desk, the weight of the digital on date T_i
        # is discounted by the model-implied probability of survival to T_i.
        # Since Phase 2 is about constructing the static instruments, we generate
        # the digitals. The dynamic weighting happens in the Greeks/Hedge optimization.
        # Here we just output the raw instruments that span the risk.

        for obs_date in component.observation_dates:
            # Create a synthetic DigitalComponent for this specific date
            sub_comp = DigitalComponent(
                notional=component.notional,
                expiry=obs_date,
                underlying=component.underlying,
                direction=component.direction,
                leg=component.leg,
                initial_fixing=component.initial_fixing,
                strike=component.autocall_level,
                payout=1.0,  # Autocall redeems 100% of par
                is_call=True,
            )

            # Delegate to the digital strategy to get the call spread
            leg_instruments = self.digital_strategy.replicate(sub_comp, model, surface)

            # Tag the purpose so we know which obs date it belongs to
            for inst in leg_instruments:
                instruments.append(
                    HedgeInstrument(
                        instrument=inst.instrument,
                        weight=inst.weight,
                        instrument_type=inst.instrument_type,
                        purpose=f"autocall_strip_{obs_date:.2f}",
                    )
                )

        return tuple(instruments)
