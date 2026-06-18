"""L12 Stress Testing Engine: coherent macro scenarios applied across the book."""

from spdt.stress.scenarios import (
    CORR_BREAKDOWN,
    EQUITY_CRASH,
    MILD_SELLOFF,
    RATE_SHOCK_UP,
    STANDARD_SCENARIOS,
    VOL_SPIKE,
    Scenario,
    StressResult,
    stress_book,
)

__all__ = [
    "CORR_BREAKDOWN",
    "EQUITY_CRASH",
    "MILD_SELLOFF",
    "RATE_SHOCK_UP",
    "STANDARD_SCENARIOS",
    "VOL_SPIKE",
    "Scenario",
    "StressResult",
    "stress_book",
]
