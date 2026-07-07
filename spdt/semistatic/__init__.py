"""L17 Semi-Static Hedging Framework: the institutional lifecycle manager.

Provides the tools to monitor, pre-unwind, and manage barrier and digital replication
portfolios over time, bridging the gap between theoretical pricing and actual desk execution.
"""

from spdt.semistatic.book import BarrierBookManager, BarrierExposure
from spdt.semistatic.monitor import MonitorSnapshot, ReplicationMonitor
from spdt.semistatic.pre_unwind import PreUnwindOptimizer, UnwindRecommendation
from spdt.semistatic.probability import BarrierProbabilityEngine
from spdt.semistatic.recalibration import (
    RecalibrationAction,
    RecalibrationActionType,
    RecalibrationManager,
)

__all__ = [
    "BarrierBookManager",
    "BarrierExposure",
    "BarrierProbabilityEngine",
    "MonitorSnapshot",
    "PreUnwindOptimizer",
    "RecalibrationAction",
    "RecalibrationActionType",
    "RecalibrationManager",
    "ReplicationMonitor",
    "UnwindRecommendation",
]
