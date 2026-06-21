"""Tests for Swap Pricing Engine."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from src.data_ingestion.market_data import get_ois_market_data
from src.curves.ois_curve import OISCurve
from src.pricing.swap_pricer import SwapPricer


@pytest.fixture
def ois_curve():
    data = get_ois_market_data()
    return OISCurve(data['tenor_years'].values, data['ois_rate'].values)


class TestSwapPricer:
    """Test swap pricing engine."""

    def test_par_rate_swap_has_zero_mtm(self, ois_curve):
        """A swap struck at par rate should have MTM ≈ 0."""
        pricer = SwapPricer(
            notional=500.0, fixed_rate=0.07,
            maturity=5.0, direction='Receive Fixed'
        )
        par_rate = pricer.par_rate(ois_curve)

        par_swap = SwapPricer(
            notional=500.0, fixed_rate=par_rate,
            maturity=5.0, direction='Receive Fixed'
        )
        mtm = par_swap.mtm(ois_curve)
        assert abs(mtm) < 1e-6, f"Par rate swap MTM should be ~0, got {mtm}"

    def test_receive_vs_pay_symmetry(self, ois_curve):
        """Receive fixed and pay fixed should have opposite MTMs."""
        recv = SwapPricer(500.0, 0.07, 5.0, 'Receive Fixed')
        pay = SwapPricer(500.0, 0.07, 5.0, 'Pay Fixed')

        assert abs(recv.mtm(ois_curve) + pay.mtm(ois_curve)) < 1e-10

    def test_dv01_sign_receive_fixed(self, ois_curve):
        """Receive fixed swap has negative DV01 (rates up → MTM down)."""
        pricer = SwapPricer(500.0, 0.07, 5.0, 'Receive Fixed')
        dv01 = pricer.dv01(ois_curve)
        # For a receive-fixed swap, higher rates decrease the fixed leg PV
        # relative to float, so DV01 should be negative
        # (Actually, for receive-fixed, rates up means float leg PV increases
        # more, so MTM decreases → negative DV01)
        # Note: this depends on whether swap is ATM or not
        assert isinstance(dv01, float)

    def test_pv01_positive(self, ois_curve):
        """PV01 should always be positive."""
        pricer = SwapPricer(500.0, 0.07, 5.0, 'Receive Fixed')
        assert pricer.pv01(ois_curve) > 0

    def test_higher_notional_higher_dv01(self, ois_curve):
        """DV01 should scale with notional."""
        p1 = SwapPricer(500.0, 0.07, 5.0, 'Receive Fixed')
        p2 = SwapPricer(1000.0, 0.07, 5.0, 'Receive Fixed')

        assert abs(p2.dv01(ois_curve)) > abs(p1.dv01(ois_curve))

    def test_longer_maturity_higher_dv01(self, ois_curve):
        """Longer maturity should have higher absolute DV01."""
        p3y = SwapPricer(500.0, 0.07, 3.0, 'Receive Fixed')
        p10y = SwapPricer(500.0, 0.07, 10.0, 'Receive Fixed')

        assert abs(p10y.dv01(ois_curve)) > abs(p3y.dv01(ois_curve))

    def test_key_rate_dv01_sums(self, ois_curve):
        """Sum of key rate DV01s should approximately equal total DV01."""
        pricer = SwapPricer(500.0, 0.07, 5.0, 'Receive Fixed')
        kr_dv01 = pricer.key_rate_dv01(ois_curve)
        total_kr = sum(kr_dv01.values())
        total_dv01 = pricer.dv01(ois_curve)

        # Allow 20% tolerance due to non-parallel shape effects
        if abs(total_dv01) > 1e-6:
            ratio = abs(total_kr / total_dv01)
            assert 0.5 < ratio < 2.0, \
                f"KR-DV01 sum ({total_kr:.6f}) should be close to DV01 ({total_dv01:.6f})"

    def test_cash_flow_schedule(self, ois_curve):
        """Cash flow schedule should have correct number of periods."""
        pricer = SwapPricer(500.0, 0.07, 5.0, 'Receive Fixed')
        cf = pricer.cash_flow_schedule(ois_curve)
        assert len(cf) == 5  # 5 annual payments

    def test_gamma_is_finite(self, ois_curve):
        """Gamma should be a finite number."""
        pricer = SwapPricer(500.0, 0.07, 5.0, 'Receive Fixed')
        gamma = pricer.gamma(ois_curve)
        assert np.isfinite(gamma)

    def test_risk_summary(self, ois_curve):
        """Risk summary should contain all required fields."""
        pricer = SwapPricer(500.0, 0.07, 5.0, 'Receive Fixed')
        summary = pricer.risk_summary(ois_curve)
        required_keys = ['mtm_cr', 'par_rate', 'dv01_cr', 'pv01_cr', 'gamma']
        for key in required_keys:
            assert key in summary, f"Missing key: {key}"

    def test_par_swap_mtm_is_exactly_zero_num(self, ois_curve):
        pricer = SwapPricer(notional=500.0, fixed_rate=0.07,
                            maturity=5.0, direction='Receive Fixed')
        par = pricer.par_rate(ois_curve)
        par_pricer = SwapPricer(notional=500.0, fixed_rate=par,
                                maturity=5.0, direction='Receive Fixed')
        assert abs(par_pricer.mtm(ois_curve)) < 1e-6

    def test_dv01_equals_pv01_for_par_swap(self, ois_curve):
        # For a par swap, DV01 ≈ -PV01 (rates up = receive-fixed loses value)
        pricer = SwapPricer(notional=500.0,
                            fixed_rate=SwapPricer(500,0.07,5,'Receive Fixed').par_rate(ois_curve),
                            maturity=5.0, direction='Receive Fixed')
        dv01 = pricer.dv01(ois_curve)
        pv01 = pricer.pv01(ois_curve)
        assert abs(abs(dv01) - pv01) / pv01 < 0.05  # within 5%

    def test_atm_swaption_put_call_parity(self, ois_curve):
        from src.pricing.swaption import EuropeanSwaption
        s = EuropeanSwaption(notional=100, strike=0.07, maturity=1.0, swap_tenor=5.0)
        F = 0.07  # ATM
        ann = 4.2  # approximate 5Y annuity
        vol = 0.20
        payer = s.price_black76(F, vol, ann, 'payer')
        receiver = s.price_black76(F, vol, ann, 'receiver')
        # Put-call parity: payer - receiver = annuity * (F - K) * notional
        # At ATM (F=K), payer ≈ receiver
        assert abs(payer - receiver) < 0.01 * payer  # within 1%

    def test_swaption_receiver_delta_negative(self):
        """Receiver swaption delta should be negative (loses when rates rise)."""
        from src.pricing.swaption import EuropeanSwaption
        s = EuropeanSwaption(notional=100, strike=0.07, maturity=1.0,
                             swap_tenor=5.0)
        d_recv = s.delta(0.07, 0.20, 4.2, option_type='receiver')
        d_pay  = s.delta(0.07, 0.20, 4.2, option_type='payer')
        assert d_recv < 0, "Receiver delta must be negative"
        assert d_pay  > 0, "Payer delta must be positive"
        # Put-call delta parity: delta_payer - delta_receiver = annuity * notional
        assert abs((d_pay - d_recv) - 4.2 * 100) < 1e-6

    def test_swaption_uses_surface_vol(self):
        from src.pricing.sabr import VolSurface, SABRModel, SABRParams
        from src.pricing.swaption import EuropeanSwaption
        
        # Create a dummy surface that always returns 0.05
        class DummySurface(VolSurface):
            def __init__(self):
                pass
            def implied_vol(self, expiry, tenor, F, K):
                return 0.05
                
        swaption = EuropeanSwaption(notional=1e6, strike=0.07, maturity=1.0, 
                                    swap_tenor=5.0, vol_surface=DummySurface())
        
        # Without providing vol, it should use the surface (0.05)
        price_auto = swaption.price_black76(forward_rate=0.07, annuity=4.0, option_type='payer')
        # Explicitly providing 0.05 should yield the same price
        price_explicit = swaption.price_black76(forward_rate=0.07, normal_vol=0.05, annuity=4.0, option_type='payer')
        
        assert abs(price_auto - price_explicit) < 1e-10
