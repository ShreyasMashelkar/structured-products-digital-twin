"""Tests for Persistent Parquet Exposure Cube."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
import tempfile
from src.exposure.exposure_cube import ExposureCube


@pytest.fixture
def temp_cube(tmp_path):
    """Create a fresh cube in a temporary directory for each test."""
    cube_path = str(tmp_path / "test_cube.parquet")
    return ExposureCube(cube_path)


@pytest.fixture
def sample_paths():
    """100 paths, 20 time steps of realistic swap NPV."""
    rng = np.random.default_rng(42)
    time_grid = np.linspace(0, 5, 20)
    # Simulate bell-shaped exposure: positive in middle, near-zero at ends
    t = time_grid
    base = 5.0 * np.sin(np.pi * t / 5.0)
    noise = rng.normal(0, 1.0, (100, 20))
    npv_paths = base + noise
    return time_grid, npv_paths


class TestExposureCube:

    def test_write_and_flush(self, temp_cube, sample_paths):
        """Writing and flushing should not raise and create the file."""
        time_grid, npv_paths = sample_paths
        temp_cube.write_paths("IRS-001", time_grid, npv_paths)
        temp_cube.flush()
        assert temp_cube.cube_path.exists()

    def test_read_back_same_rows(self, temp_cube, sample_paths):
        """Reading back a trade should return n_paths × n_steps rows."""
        time_grid, npv_paths = sample_paths
        n_paths, n_steps = npv_paths.shape
        temp_cube.write_paths("IRS-001", time_grid, npv_paths)
        temp_cube.flush()
        df = temp_cube.read_trade("IRS-001")
        assert len(df) == n_paths * n_steps

    def test_ee_equals_mean_positive_npv(self, temp_cube, sample_paths):
        """
        EE at each time step must equal mean(max(NPV, 0)) across paths.
        This is the definition of Expected Exposure.
        """
        time_grid, npv_paths = sample_paths
        temp_cube.write_paths("IRS-001", time_grid, npv_paths)
        temp_cube.flush()

        profile = temp_cube.compute_ee_profile("IRS-001")

        # Verify EE at each time step
        for i, t in enumerate(time_grid):
            expected_ee = float(np.mean(np.maximum(npv_paths[:, i], 0.0)))
            actual_ee_row = profile[profile['time_years'].round(6) == round(t, 6)]
            if len(actual_ee_row) > 0:
                actual_ee = float(actual_ee_row['EE'].iloc[0])
                assert abs(actual_ee - expected_ee) < 0.01, \
                    f"EE mismatch at t={t:.2f}: expected {expected_ee:.4f}, got {actual_ee:.4f}"

    def test_pfe95_exceeds_ee(self, temp_cube, sample_paths):
        """PFE(95%) must be >= EE at every time step."""
        time_grid, npv_paths = sample_paths
        temp_cube.write_paths("IRS-001", time_grid, npv_paths)
        temp_cube.flush()
        profile = temp_cube.compute_ee_profile("IRS-001")
        assert (profile['PFE_95'] >= profile['EE'] - 1e-10).all()

    def test_portfolio_ee_uses_netting(self, temp_cube, sample_paths):
        """
        Portfolio EE should be less than or equal to sum of individual EEs.
        (Netting benefit — offsetting trades reduce portfolio exposure.)
        """
        time_grid, npv_paths = sample_paths
        # Trade 1: positive NPV
        temp_cube.write_paths("IRS-001", time_grid, npv_paths)
        # Trade 2: negative (offsetting) NPV
        temp_cube.write_paths("IRS-002", time_grid, -npv_paths * 0.7)
        temp_cube.flush()

        portfolio_profile = temp_cube.compute_portfolio_ee(["IRS-001", "IRS-002"])
        profile_001 = temp_cube.compute_ee_profile("IRS-001")
        profile_002 = temp_cube.compute_ee_profile("IRS-002")

        sum_ee = (profile_001['EE'].values + profile_002['EE'].values)
        portfolio_ee = portfolio_profile['EE'].values

        # With netting, portfolio EE ≤ sum of individual EEs
        assert np.all(portfolio_ee <= sum_ee + 1e-6)

    def test_get_summary_after_write(self, temp_cube, sample_paths):
        """Summary should report correct trade count and path count."""
        time_grid, npv_paths = sample_paths
        temp_cube.write_paths("IRS-001", time_grid, npv_paths)
        temp_cube.flush()
        summary = temp_cube.get_summary()
        assert summary['exists'] is True
        assert summary['n_trades'] == 1
        assert summary['n_paths'] == npv_paths.shape[0]

    def test_clear_removes_file(self, temp_cube, sample_paths):
        """clear() should delete the Parquet file."""
        time_grid, npv_paths = sample_paths
        temp_cube.write_paths("IRS-001", time_grid, npv_paths)
        temp_cube.flush()
        assert temp_cube.cube_path.exists()
        temp_cube.clear()
        assert not temp_cube.cube_path.exists()
