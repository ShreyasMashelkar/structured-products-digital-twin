import pytest
import numpy as np
from src.curves.ois_curve import OISCurve
from src.calibration.hw_calibrator import HullWhiteCalibrator
from src.data_ingestion.market_data import get_ois_market_data


def test_hw_calibrator():
    ois_df = get_ois_market_data()
    curve = OISCurve(ois_df['tenor_years'].values, ois_df['ois_rate'].values)
    calibrator = HullWhiteCalibrator(curve)

    a, sigma = calibrator.calibrate_to_historical_mibor()
    assert 0.0 < a <= 0.5
    assert 0.0 < sigma < 0.10  # Normal vol usually < 1000 bps

    hw = calibrator.get_calibrated_model()
    assert hw.a == a
    assert hw.sigma == sigma
    
    # Check summary
    summary = calibrator.get_calibration_summary()
    assert 'a' in summary
    assert 'sigma' in summary
    assert 'r_squared' in summary

def test_hw1f_analytical_b_function():
    ois_df = get_ois_market_data()
    curve = OISCurve(ois_df['tenor_years'].values, ois_df['ois_rate'].values)
    calibrator = HullWhiteCalibrator(curve)
    a, sigma = calibrator.calibrate_to_historical_mibor()
    hw = calibrator.get_calibrated_model()

    # B(T, T) should be 0
    assert np.isclose(hw._B(5.0, 5.0), 0.0)
    
    # B(t, T) should be positive for t < T
    b_val = hw._B(2.0, 5.0)
    assert b_val > 0.0

def test_hw1f_simulation_shapes():
    ois_df = get_ois_market_data()
    curve = OISCurve(ois_df['tenor_years'].values, ois_df['ois_rate'].values)
    calibrator = HullWhiteCalibrator(curve)
    calibrator.calibrate_to_historical_mibor()
    hw = calibrator.get_calibrated_model()

    n_paths = 100
    n_steps = 12
    horizon = 1.0
    t_grid, paths = hw.simulate_rates(n_paths=n_paths, n_steps=n_steps, horizon=horizon, seed=42)

    assert len(t_grid) == n_steps + 1
    assert paths.shape == (n_paths, n_steps + 1)
    
    dfs = hw.simulate_discount_factors(t_grid, paths)
    assert dfs.shape == (n_paths, n_steps + 1)
    
    # Initial discount factor should be 1.0
    assert np.allclose(dfs[:, 0], 1.0)
