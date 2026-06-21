"""Tests for CSA Collateral Engine."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from src.csa.collateral import CSAEngine, compare_csa_scenarios
from src.data_ingestion.market_data import get_csa_scenarios


@pytest.fixture
def sample_mtm_paths():
    """Create sample MTM paths for testing."""
    rng = np.random.default_rng(42)
    n_paths, n_steps = 500, 30
    # Simulate a swap-like MTM profile
    mtm = rng.normal(0, 5, (n_paths, n_steps + 1))
    mtm[:, 0] = 0.0  # Start at zero
    mtm = np.cumsum(mtm * 0.3, axis=1)
    return mtm


@pytest.fixture
def time_grid():
    return np.linspace(0, 5, 31)


class TestCSAEngine:
    """Test CSA collateral engine."""

    def test_uncollateralised_exposure(self, sample_mtm_paths, time_grid):
        """Uncollateralised exposure = max(MTM, 0)."""
        engine = CSAEngine(
            threshold=float('inf'),
            margin_frequency='none'
        )
        exposure = engine.compute_collateralised_exposure(
            sample_mtm_paths, time_grid
        )
        expected = np.maximum(sample_mtm_paths, 0.0)
        np.testing.assert_array_almost_equal(exposure, expected)

    def test_collateralised_less_than_uncollateralised(
            self, sample_mtm_paths, time_grid):
        """Collateralised EE should be <= uncollateralised EE."""
        uncoll = CSAEngine(threshold=float('inf'), margin_frequency='none')
        coll = CSAEngine(threshold=0.0, mta=0.0, mpor_days=5,
                          margin_frequency='daily')

        uncoll_metrics = uncoll.compute_exposure_metrics(
            sample_mtm_paths, time_grid
        )
        coll_metrics = coll.compute_exposure_metrics(
            sample_mtm_paths, time_grid
        )

        assert coll_metrics['EPE'] <= uncoll_metrics['EPE'] + 1e-6

    def test_zero_threshold_reduces_exposure(
            self, sample_mtm_paths, time_grid):
        """Zero-threshold daily margin should significantly reduce exposure."""
        high_th = CSAEngine(threshold=1000.0, margin_frequency='daily')
        zero_th = CSAEngine(threshold=0.0, mta=0.0, margin_frequency='daily')

        high_metrics = high_th.compute_exposure_metrics(
            sample_mtm_paths, time_grid
        )
        zero_metrics = zero_th.compute_exposure_metrics(
            sample_mtm_paths, time_grid
        )

        assert zero_metrics['EPE'] <= high_metrics['EPE'] + 1e-6

    def test_compare_scenarios(self, sample_mtm_paths, time_grid):
        """Scenario comparison should return results for all scenarios."""
        scenarios = get_csa_scenarios()
        results = compare_csa_scenarios(
            sample_mtm_paths, time_grid, scenarios
        )

        assert len(results) == len(scenarios)
        for name in scenarios:
            assert name in results
            assert 'EE' in results[name]
            assert 'PFE' in results[name]

    def test_collateral_non_negative(self, sample_mtm_paths, time_grid):
        """Collateral held should be non-negative."""
        engine = CSAEngine(threshold=5.0, mta=1.0,
                            margin_frequency='daily')
        collateral = engine.compute_collateral(
            sample_mtm_paths, time_grid
        )
        assert np.all(collateral >= -1e-10)

    def test_epe_capped_at_one_year(self):
        """Test that EPE and EEPE appropriately cap the denominator at 1.0."""
        time_grid = np.linspace(0, 5, 51)  # 5 years
        dt = time_grid[1] - time_grid[0]
        mtm = np.zeros((1, 51))
        # Force EE = 100 everywhere
        mtm[0, :] = 100.0

        engine = CSAEngine(threshold=float('inf'), margin_frequency='none')
        metrics = engine.compute_exposure_metrics(mtm, time_grid)
        
        # EPE should be exactly 100.0. Under the old bug (dividing by 5.0), it would be 20.0
        np.testing.assert_almost_equal(metrics['EPE'], 100.0, decimal=2)
        np.testing.assert_almost_equal(metrics['EEPE'], 100.0, decimal=2)
