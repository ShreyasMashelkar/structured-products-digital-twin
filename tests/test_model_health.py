"""Tests for the Model Health Engine."""

from spdt.health.engine import ModelHealthEngine
from spdt.pricing.models.bs import BlackScholes


class TestModelHealthEngine:

    def test_healthy_model(self):
        engine = ModelHealthEngine()

        m_yest = BlackScholes(spot=100.0, sigma=0.20, r=0.05, q=0.0)
        m_today = BlackScholes(spot=100.1, sigma=0.201, r=0.05, q=0.0)

        report = engine.evaluate_health(
            model_today=m_today,
            model_yesterday=m_yest,
            calibration_rmse=0.001,
            tracking_error_bps=2.0,
            min_distance_to_barrier_pct=0.15,
        )

        assert report.overall_score > 0.90  # Extremely healthy
        assert report.surface_stability > 0.90
        assert report.barrier_proximity == 0.15

    def test_unhealthy_model(self):
        engine = ModelHealthEngine()

        # Spot crashed 10%, vol spiked 10 points
        m_yest = BlackScholes(spot=100.0, sigma=0.20, r=0.05, q=0.0)
        m_today = BlackScholes(spot=90.0, sigma=0.30, r=0.05, q=0.0)

        report = engine.evaluate_health(
            model_today=m_today,
            model_yesterday=m_yest,
            calibration_rmse=0.05,
            tracking_error_bps=100.0, # Massive replication slippage
            min_distance_to_barrier_pct=0.01, # 1% away from barrier
        )

        assert report.overall_score < 0.30  # Very unhealthy
        assert report.surface_stability == 0.0 # Huge drift
        assert report.replication_error == 100.0
        assert report.smile_regime == "sticky_delta" # Spot moved and vol moved significantly
