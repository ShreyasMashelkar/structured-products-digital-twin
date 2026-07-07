"""Pre-Unwind Optimizer.

For a knock-out claim, institutional desks may progressively unwind the replication portfolio
as hit probability rises, avoiding the market impact of closing the entire hedge at the exact
moment the option terminates. Knock-ins follow a different lifecycle: on activation their
conditional hedge transitions into vanilla exposure and must not use this unwind schedule.
"""

from __future__ import annotations

from dataclasses import dataclass

from spdt.replication.portfolio import HedgeInstrument, ReplicationPortfolio


@dataclass(frozen=True)
class UnwindRecommendation:
    """A recommendation to partially or fully unwind a replication portfolio."""

    p_hit: float
    unwind_fraction: float  # 0.0 to 1.0 (1.0 = full unwind)
    instruments_to_close: tuple[HedgeInstrument, ...]


class PreUnwindOptimizer:
    """Recommends progressive unwinds based on barrier hit probabilities.

    Standard schedule:
    - P(hit) < 50%: 0% unwind
    - P(hit) 50-70%: 20% unwind
    - P(hit) 70-85%: 50% unwind
    - P(hit) 85-95%: 80% unwind
    - P(hit) > 95%: 100% unwind
    """

    UNWIND_SCHEDULE = (
        (0.50, 0.00),
        (0.70, 0.20),
        (0.85, 0.50),
        (0.95, 0.80),
        (1.00, 1.00),
    )

    @classmethod
    def get_unwind_fraction(cls, p_hit: float) -> float:
        """Get the target unwind fraction for a given hit probability."""
        for threshold, fraction in cls.UNWIND_SCHEDULE:
            if p_hit <= threshold:
                return fraction
        return 1.0

    @classmethod
    def recommend(
        cls, p_hit: float, portfolio: ReplicationPortfolio, current_unwound_fraction: float = 0.0
    ) -> UnwindRecommendation:
        """Recommend the incremental trades needed to reach the target unwind state."""
        target_fraction = cls.get_unwind_fraction(p_hit)

        # If we are already unwound more than the target (e.g. spot retreated),
        # desks usually *do not* rewind (re-hedge) due to transaction costs.
        if target_fraction <= current_unwound_fraction:
            return UnwindRecommendation(p_hit, 0.0, ())

        incremental_unwind = target_fraction - current_unwound_fraction

        trades_to_execute = []
        for instr in portfolio.instruments:
            # To unwind, we execute a trade in the opposite direction
            unwind_weight = -instr.weight * incremental_unwind
            if abs(unwind_weight) > 1e-8:
                trades_to_execute.append(
                    HedgeInstrument(
                        instrument=instr.instrument,
                        weight=unwind_weight,
                        instrument_type=instr.instrument_type,
                        purpose="pre_unwind",
                    )
                )

        return UnwindRecommendation(
            p_hit=p_hit,
            unwind_fraction=incremental_unwind,
            instruments_to_close=tuple(trades_to_execute),
        )
