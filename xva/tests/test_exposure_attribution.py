"""Tests for Exposure Attribution Engine (Phase 7)."""
from src.workflow.exposure_attribution import ExposureAttributionEngine

def test_explain_exposure_change():
    t0_port = [{'TradeID': '1', 'EstimatedEAD': 50.0}, {'TradeID': '2', 'EstimatedEAD': 30.0}]
    t1_port = [{'TradeID': '1', 'EstimatedEAD': 55.0}, {'TradeID': '3', 'EstimatedEAD': 40.0}]
    
    t0_exp = 80.0
    t1_exp = 95.0
    market_move = 5.0 # M2M increased by 5 due to rates on Trade 1
    
    eng = ExposureAttributionEngine()
    res = eng.explain_exposure_change(t0_port, t0_exp, t1_port, t1_exp, market_move)
    
    # New trade: Trade 3 (+40)
    # Matured trade: Trade 2 (-30)
    # Market Move: +5
    # Total Explained = 40 - 30 + 5 = +15
    # Actual Change = 95 - 80 = +15
    # Unexplained = 0
    
    assert res['New_Trades'] == 40.0
    assert res['Matured_Trades'] == -30.0
    assert res['Market_Moves'] == 5.0
    assert abs(res['Unexplained']) < 1e-6
    assert res['Total_Change'] == 15.0

def test_explain_cva_change():
    eng = ExposureAttributionEngine()
    
    t0_cva = 100.0
    t1_cva = 120.0
    
    res = eng.explain_cva_change(t0_cva, t1_cva, exposure_change_impact=10.0,
                                 spread_change_impact=15.0, time_decay_impact=-2.0)
    
    # Total Explained = 10 + 15 - 2 = 23
    # Actual Change = 20
    # Unexplained = 20 - 23 = -3
    assert res['Total_Change'] == 20.0
    assert abs(res['Unexplained'] - (-3.0)) < 1e-6
