"""Tests for WWR Governance and Stress Testing Engine (Phase 9)."""
import numpy as np
from src.wwr.wwr_stress import WWREngine

def test_wwr_detection():
    eng = WWREngine()
    
    trade_specific = {'Direction': 'PAY', 'Tags': 'SPECIFIC_WWR'}
    assert eng.detect_wwr(trade_specific, 'TECH') == 'SPECIFIC'
    
    trade_general = {'Direction': 'PAY', 'Tags': ''}
    assert eng.detect_wwr(trade_general, 'HIGH_YIELD') == 'GENERAL'
    
    trade_none = {'Direction': 'RECEIVE', 'Tags': ''}
    assert eng.detect_wwr(trade_none, 'INVESTMENT_GRADE') == 'NONE'

def test_apply_wwr_stress():
    eng = WWREngine(general_wwr_multiplier=1.2, specific_wwr_multiplier=1.5)
    
    ee = np.array([100.0, 200.0, 300.0])
    
    assert np.allclose(eng.apply_wwr_stress(ee, 'SPECIFIC'), [150.0, 300.0, 450.0])
    assert np.allclose(eng.apply_wwr_stress(ee, 'GENERAL'), [120.0, 240.0, 360.0])
    assert np.allclose(eng.apply_wwr_stress(ee, 'NONE'), [100.0, 200.0, 300.0])

def test_calculate_stressed_cva():
    eng = WWREngine(general_wwr_multiplier=1.2, specific_wwr_multiplier=1.5)
    
    trades = [
        {'Direction': 'PAY', 'Tags': 'SPECIFIC_WWR'},
        {'Direction': 'PAY', 'Tags': ''},
        {'Direction': 'RECEIVE', 'Tags': ''}
    ]
    # Sector HIGH_YIELD means Trade 2 is GENERAL WWR. Trade 1 is SPECIFIC. Trade 3 is NONE.
    # Weights: 1/3 Specific (1.5), 1/3 General (1.2), 1/3 None (1.0). 
    # Effective Multiplier = (1.5 + 1.2 + 1.0) / 3 = 3.7 / 3 = 1.233333...
    
    res = eng.calculate_stressed_cva(base_cva=300.0, portfolio_trades=trades, cpty_sector='HIGH_YIELD')
    
    assert abs(res['Effective_Multiplier'] - 1.23333333) < 1e-6
    assert abs(res['Stressed_CVA'] - 370.0) < 1e-6
    assert abs(res['WWR_Impact'] - 70.0) < 1e-6
