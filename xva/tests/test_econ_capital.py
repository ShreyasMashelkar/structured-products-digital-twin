"""Tests for Economic Capital Engine (Phase 8)."""
from src.economic_capital.econ_capital import EconomicCapitalEngine

def test_economic_capital_computation():
    eng = EconomicCapitalEngine(confidence_level=0.999)
    
    ead = 1000.0
    pd_1y = 0.02  # 2% default probability
    lgd = 0.40    # 40% loss given default
    
    res = eng.compute_economic_capital(ead, pd_1y, lgd, asset_correlation=0.15)
    
    # EL = 1000 * 0.02 * 0.4 = 8.0
    assert abs(res['Expected_Loss'] - 8.0) < 1e-6
    
    # UL should be significantly higher than EL due to the 99.9% stress
    assert res['Unexpected_Loss'] > res['Expected_Loss'] * 5
    assert res['Economic_Capital'] == res['Unexpected_Loss']

def test_zero_pd():
    eng = EconomicCapitalEngine()
    res = eng.compute_economic_capital(100.0, 0.0, 0.4)
    assert res['Economic_Capital'] == 0.0
