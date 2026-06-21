"""Tests for Monte Carlo Simulation Engine."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from src.data_ingestion.market_data import get_ois_market_data
from src.curves.ois_curve import OISCurve
from src.montecarlo.hull_white import HullWhite1F, run_exposure_simulation


@pytest.fixture
def ois_curve():
    data = get_ois_market_data()
    return OISCurve(data['tenor_years'].values, data['ois_rate'].values)


@pytest.fixture
def simulation(ois_curve):
    return run_exposure_simulation(
        ois_curve, notional=500.0, fixed_rate=0.07,
        maturity=5.0, direction='Receive Fixed',
        n_paths=2000, n_steps=30, seed=42
    )


class TestHullWhite1F:
    """Test Hull-White 1F simulation."""

    def test_rate_paths_shape(self, ois_curve):
        """Rate paths should have correct shape."""
        model = HullWhite1F(ois_curve)
        time_grid, rates = model.simulate_rates(n_paths=100, n_steps=10)

        assert rates.shape == (100, 11)
        assert len(time_grid) == 11

    def test_rates_positive(self, ois_curve):
        """Simulated rates should be positive."""
        model = HullWhite1F(ois_curve)
        _, rates = model.simulate_rates(n_paths=1000, n_steps=30)
        assert np.all(rates > 0)

    def test_mean_rate_near_forward(self, ois_curve):
        """Mean of simulated rates should be near forward rates."""
        model = HullWhite1F(ois_curve, a=0.10, sigma=0.01)
        time_grid, rates = model.simulate_rates(
            n_paths=5000, n_steps=60, horizon=5.0
        )

        # At t=1Y, mean rate should be near f(0,1)
        f_1y = ois_curve.instantaneous_forward(1.0)
        mean_1y = np.mean(rates[:, 12])  # 12th step ≈ 1Y

        # Allow 50bps tolerance due to convexity correction
        assert abs(mean_1y - f_1y) < 0.005, \
            f"Mean rate at 1Y ({mean_1y:.4f}) too far from forward ({f_1y:.4f})"

    def test_exposure_ee_non_negative(self, simulation):
        """Expected Exposure should be non-negative."""
        assert np.all(simulation['metrics']['EE'] >= 0)

    def test_pfe_exceeds_ee(self, simulation):
        """PFE should be >= EE at all times."""
        ee = simulation['metrics']['EE']
        pfe = simulation['metrics']['PFE']
        assert np.all(pfe >= ee - 1e-10)

    def test_epe_positive(self, simulation):
        """EPE should be positive."""
        assert simulation['metrics']['EPE'] >= 0

    def test_eepe_capped_at_one_year(self, simulation):
        """EEPE must equal the time-weighted average of effective_EE over the first year only."""
        metrics = simulation['metrics']
        ee = metrics['EE']
        time_grid = metrics['time_grid']
        dt_array = np.diff(time_grid)
        
        effective_ee = np.maximum.accumulate(ee)
        mask = time_grid[1:] <= 1.0 + 1e-9
        expected_eepe = np.sum(effective_ee[1:][mask] * dt_array[mask]) / 1.0
        
        assert abs(metrics['EEPE'] - expected_eepe) < 1e-8

    def test_reproducibility(self, ois_curve):
        """Same seed should produce identical results."""
        result1 = run_exposure_simulation(
            ois_curve, n_paths=100, n_steps=10, seed=123
        )
        result2 = run_exposure_simulation(
            ois_curve, n_paths=100, n_steps=10, seed=123
        )
        np.testing.assert_array_equal(
            result1['rate_paths'], result2['rate_paths']
        )

    def test_mtm_paths_at_maturity_zero(self, simulation):
        """MTM should be approximately zero at maturity."""
        mtm_at_end = simulation['mtm_paths'][:, -1]
        assert np.mean(np.abs(mtm_at_end)) < 1.0  # Near zero at maturity

def test_calibrate_hw1f_returns_valid_params():
    """calibrate_hw1f should return positive a and sigma within realistic bounds."""
    from src.montecarlo.hull_white import calibrate_hw1f
    from src.data_ingestion.market_data import get_historical_mibor
    import pandas as pd
    
    history = get_historical_mibor(n_days=504)
    params = calibrate_hw1f(history['mibor_rate'])
    
    assert 0.01 <= params['a'] <= 0.50, f"a={params['a']} out of range"
    assert 0.001 <= params['sigma'] <= 0.05, f"sigma={params['sigma']} out of range"
    assert 0.02 <= params['theta_longrun'] <= 0.20

def test_calibrate_hw1f_short_series_returns_defaults():
    """Should return safe defaults for short series rather than crash."""
    from src.montecarlo.hull_white import calibrate_hw1f
    import pandas as pd
    
    short = pd.Series([0.065, 0.066, 0.064])
    params = calibrate_hw1f(short)
    assert 'a' in params and 'sigma' in params

def test_mva_positive_and_discounted():
    """MVA should be positive and less than undiscounted sum."""
    from src.xva.mva import MVAEngine
    import numpy as np
    from src.data_ingestion.market_data import get_ois_market_data
    from src.curves.ois_curve import OISCurve
    
    data = get_ois_market_data()
    curve = OISCurve(data['tenor_years'].values, data['ois_rate'].values)
    
    engine = MVAEngine(ois_curve=curve, funding_spread_bps=40.0, dv01_cr=0.05)
    time_grid = np.linspace(0, 5, 61)
    ee = 5.0 * np.sin(np.pi * time_grid / 5.0) * np.exp(-0.1 * time_grid)
    
    im = engine.compute_im_profile(ee)
    mva = engine.compute_mva(im, time_grid)
    
    assert mva > 0
    # MVA must be less than undiscounted sum (discount factors < 1)
    undiscounted = engine.funding_spread * np.trapezoid(im, time_grid)
    assert mva < undiscounted

def test_antithetic_reduces_variance():
    """Antithetic variates should balance the sample mean closer to theoretical forward."""
    from src.data_ingestion.market_data import get_ois_market_data
    from src.curves.ois_curve import OISCurve
    from src.montecarlo.hull_white import HullWhite1F
    import numpy as np

    data = get_ois_market_data()
    curve = OISCurve(data['tenor_years'].values, data['ois_rate'].values)
    model = HullWhite1F(curve, a=0.1, sigma=0.01)

    _, rates_std = model.simulate_rates(n_paths=5000, seed=42, antithetic=False)
    _, rates_anti = model.simulate_rates(n_paths=5000, seed=42, antithetic=True)

    fwd = curve.instantaneous_forward(5.0)
    t = 5.0
    a = 0.1
    sigma = 0.01
    convexity = (sigma ** 2 / (2 * a ** 2)) * (1 - np.exp(-a * t)) ** 2
    theoretical_mean = fwd + convexity

    err_std = abs(np.mean(rates_std[:, -1]) - theoretical_mean)
    err_anti = abs(np.mean(rates_anti[:, -1]) - theoretical_mean)
    
    assert err_anti < err_std
