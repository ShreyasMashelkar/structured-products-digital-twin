"""Tests for the Replication Analytics Engine."""

from datetime import date, timedelta

import pytest

from spdt.analytics.replication_history import DailyTrackingError, ReplicationAnalyticsEngine


class TestReplicationAnalyticsEngine:

    def test_record_and_aggregate_ytd(self):
        engine = ReplicationAnalyticsEngine()

        today = date(2026, 1, 10)

        # Day 1: Lost $1000 on product, Hedge made $800 => Unexplained -200 (gap risk)
        engine.record_daily_pnl(DailyTrackingError(
            date=today - timedelta(days=2),
            product_pnl=-1000.0,
            hedge_pnl=800.0,
            unexplained_pnl=-200.0,
            primary_driver="gap_risk"
        ))

        # Day 2: Made $500 on product, Hedge lost $400 => Unexplained +100 (cross gamma)
        engine.record_daily_pnl(DailyTrackingError(
            date=today - timedelta(days=1),
            product_pnl=500.0,
            hedge_pnl=-400.0,
            unexplained_pnl=100.0,
            primary_driver="cross_gamma"
        ))

        ytd_error = engine.compute_ytd_tracking_error()
        assert ytd_error == -100.0  # -200 + 100

        volatility = engine.compute_tracking_error_volatility()
        assert volatility > 0.0

    def test_attribute_variance(self):
        engine = ReplicationAnalyticsEngine()
        today = date(2026, 1, 10)

        engine.record_daily_pnl(DailyTrackingError(
            date=today - timedelta(days=2),
            product_pnl=0.0, hedge_pnl=0.0, unexplained_pnl=-200.0, primary_driver="gap_risk"
        ))
        engine.record_daily_pnl(DailyTrackingError(
            date=today - timedelta(days=1),
            product_pnl=0.0, hedge_pnl=0.0, unexplained_pnl=100.0, primary_driver="cross_gamma"
        ))

        # Total absolute unexplained = 300
        # gap_risk = 200 / 300 = 66.6%
        # cross_gamma = 100 / 300 = 33.3%
        attr = engine.attribute_variance()

        assert pytest.approx(attr["gap_risk"]) == 2.0 / 3.0
        assert pytest.approx(attr["cross_gamma"]) == 1.0 / 3.0
