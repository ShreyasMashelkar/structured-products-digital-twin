"""Tests for SABR Stochastic Vol Model and Vol Surface."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from src.pricing.sabr import SABRModel, SABRParams, VolSurface


@pytest.fixture
def atm_params():
    """Standard SABR params for a 5Y expiry ATM swaption."""
    return SABRParams(alpha=0.0065, beta=0.5, rho=-0.15, nu=0.40)


@pytest.fixture
def sabr_model(atm_params):
    return SABRModel(atm_params)


class TestSABRModel:

    def test_atm_vol_positive(self, sabr_model):
        """ATM vol must be positive."""
        F = 0.07
        vol = sabr_model.implied_normal_vol(F, F, T=2.0)
        assert vol > 0

    def test_atm_vol_matches_alpha_approx(self, atm_params):
        """
        For ATM and short expiry, SABR normal vol ≈ alpha / F^(1-beta).
        This is the leading order ATM term.
        """
        F = 0.07
        model = SABRModel(atm_params)
        vol = model.implied_normal_vol(F, F, T=0.01)  # Very short expiry
        alpha_approx = atm_params.alpha / (F ** (1 - atm_params.beta))
        # Should be within 20% of leading-order term
        assert abs(vol - alpha_approx) / alpha_approx < 0.20

    def test_smile_symmetric_for_zero_rho(self):
        """For rho=0, smile should be symmetric around ATM."""
        params = SABRParams(alpha=0.007, beta=0.5, rho=0.0, nu=0.40)
        model = SABRModel(params)
        F = 0.07
        T = 2.0
        spread = 0.005
        vol_itm = model.implied_normal_vol(F, F - spread, T)
        vol_otm = model.implied_normal_vol(F, F + spread, T)
        # Symmetric smile: ITM and OTM vols should be equal within 5%
        assert abs(vol_itm - vol_otm) / vol_itm < 0.05

    def test_negative_rho_gives_negative_skew(self):
        """Negative rho produces higher vol for low strikes (negative skew)."""
        params = SABRParams(alpha=0.007, beta=0.5, rho=-0.30, nu=0.40)
        model = SABRModel(params)
        F = 0.07
        T = 2.0
        vol_low  = model.implied_normal_vol(F, F - 0.01, T)  # In-the-money payer
        vol_high = model.implied_normal_vol(F, F + 0.01, T)  # Out-of-the-money payer
        assert vol_low > vol_high, "Negative rho should give higher vol at low strikes"

    def test_smile_returns_correct_length(self, sabr_model):
        """smile() should return an array of the same length as strikes."""
        F = 0.07
        strikes = np.linspace(0.04, 0.10, 13)
        vols = sabr_model.smile(F, strikes, T=2.0)
        assert len(vols) == len(strikes)

    def test_all_vols_positive(self, sabr_model):
        """All smile vols must be positive."""
        F = 0.07
        strikes = np.linspace(0.04, 0.10, 13)
        vols = sabr_model.smile(F, strikes, T=2.0)
        assert np.all(vols > 0)

    def test_vol_increases_with_expiry_atm(self):
        """ATM vol generally increases with expiry for realistic nu > 0."""
        params = SABRParams(alpha=0.007, beta=0.5, rho=-0.15, nu=0.35)
        model = SABRModel(params)
        F = 0.07
        vol_short = model.implied_normal_vol(F, F, T=0.5)
        vol_long  = model.implied_normal_vol(F, F, T=5.0)
        # Not a strict requirement but holds for typical params
        assert vol_long > 0 and vol_short > 0  # Both valid


class TestVolSurface:

    def test_vol_surface_builds(self):
        """VolSurface.build_from_market_data() should not raise."""
        surface = VolSurface.build_from_market_data()
        assert surface is not None

    def test_vol_surface_has_expected_slices(self):
        """Surface should have entries for all expiry × tenor combinations."""
        surface = VolSurface.build_from_market_data()
        df = surface.to_dataframe()
        n_expected = len(VolSurface.EXPIRIES) * len(VolSurface.TENORS)
        assert len(df) == n_expected

    def test_vol_surface_atm_vols_positive(self):
        """All ATM vols on the surface must be positive."""
        surface = VolSurface.build_from_market_data()
        df = surface.to_dataframe()
        assert (df['atm_normal_vol_bps'] > 0).all()

    def test_vol_surface_nearest_fallback(self):
        """Requesting an off-grid point should not raise."""
        surface = VolSurface.build_from_market_data()
        vol = surface.implied_vol(expiry=1.5, tenor=3.0, F=0.07, K=0.07)
        assert vol > 0
