"""Model Health Engine: continuously monitors if the pricing models are trustworthy."""

from __future__ import annotations

from dataclasses import dataclass
from spdt.pricing.models.bs import BlackScholes

@dataclass(frozen=True)
class HealthReport:
    """A comprehensive health score of the desk's models."""

    surface_stability: float     # 0–1 (SSVI param drift day-over-day)
    calibration_error: float     # RMS of model vs market IVs
    replication_error: float     # from the replication tracking error
    model_drift: float           # LSV vs LV price gap change
    smile_regime: str            # "sticky_strike" | "sticky_delta" | "transitioning"
    liquidity_score: float       # bid-offer width relative to history
    barrier_proximity: float     # closest barrier distance in the book
    overall_score: float         # weighted composite (0 = broken, 1 = healthy)

class ModelHealthEngine:
    """Evaluates the structural integrity of the desk's pricing models."""

    def __init__(self):
        pass

    def evaluate_health(
        self,
        model_today: BlackScholes,
        model_yesterday: BlackScholes,
        calibration_rmse: float,
        tracking_error_bps: float,
        min_distance_to_barrier_pct: float,
    ) -> HealthReport:
        """Run the daily model health check."""

        # 1. Surface Stability (Spot and Vol move day-over-day)
        spot_drift = abs(model_today.spot / model_yesterday.spot - 1.0)
        vol_drift = abs(model_today.sigma - model_yesterday.sigma)

        # Score decreases if drift is high. (Naive linear score for prototype)
        surface_stability = max(0.0, 1.0 - (spot_drift * 5 + vol_drift * 10))

        # 2. Smile Regime Detection
        # In a real system, we'd pass term structures. Here we mock it.
        # Sticky delta implies vol moves with spot. Sticky strike implies vol stays fixed.
        regime = "transitioning"
        if spot_drift > 0.01:
            if vol_drift < 0.005:
                regime = "sticky_strike"
            else:
                regime = "sticky_delta"

        # 3. Model Drift (Proxy: how big is the reserve requirement growing?)
        # Let's say if reserve requirement goes up, health goes down.
        # Hardcoding a proxy for now since reserve engine requires full product paths
        model_drift = max(0.0, 1.0 - calibration_rmse * 20)

        # 4. Replication Error Score
        rep_error_score = max(0.0, 1.0 - (tracking_error_bps / 50.0))  # 50 bps tracking error = 0 health

        # 5. Barrier Proximity Score
        # If spot is very close to a barrier, model health is "low" (high risk of local gamma/model breakdown)
        barrier_score = min(1.0, min_distance_to_barrier_pct / 0.10) # <10% distance reduces score

        # 6. Overall Composite Score
        overall = (
            surface_stability * 0.20 +
            model_drift * 0.20 +
            rep_error_score * 0.40 +
            barrier_score * 0.20
        )

        return HealthReport(
            surface_stability=surface_stability,
            calibration_error=calibration_rmse,
            replication_error=tracking_error_bps,
            model_drift=model_drift,
            smile_regime=regime,
            liquidity_score=1.0,  # Placeholder for bid/ask data
            barrier_proximity=min_distance_to_barrier_pct,
            overall_score=overall,
        )
