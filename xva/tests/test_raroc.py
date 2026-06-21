"""Tests for RAROC Framework (Phase 5)."""
from src.raroc.raroc_engine import RAROCEngine

def test_raroc_computation():
    eng = RAROCEngine(hurdle_rate=0.15)
    
    # Profitable trade meeting hurdle
    res1 = eng.compute_raroc(revenue=100.0, expected_loss=10.0, expenses=5.0, xva_costs=20.0, allocated_capital=300.0)
    # Net income = 100 - 10 - 5 - 20 = 65
    # RAROC = 65 / 300 = 21.67%
    assert abs(res1['Net_Income'] - 65.0) < 1e-6
    assert abs(res1['RAROC'] - 0.216666666) < 1e-6
    assert res1['Is_Accretive'] is True
    
    # Unprofitable trade (or missing hurdle)
    res2 = eng.compute_raroc(revenue=50.0, expected_loss=15.0, expenses=5.0, xva_costs=20.0, allocated_capital=300.0)
    # Net income = 50 - 15 - 5 - 20 = 10
    # RAROC = 10 / 300 = 3.33%
    assert abs(res2['RAROC'] - 0.033333333) < 1e-6
    assert res2['Is_Accretive'] is False

def test_incremental_trade_evaluation():
    eng = RAROCEngine(hurdle_rate=0.12)
    
    base_rev = 1000.0
    base_el = 100.0
    base_xva = 200.0
    base_cap = 5000.0
    # Base Net Income = 700. Base RAROC = 14%
    
    incr_rev = 100.0
    incr_el = 20.0
    incr_xva = 30.0
    incr_cap = 1000.0
    # Incr Net Income = 50. Incr RAROC = 5%
    
    eval_res = eng.evaluate_incremental_trade(base_rev, base_el, base_xva, base_cap,
                                              incr_rev, incr_el, incr_xva, incr_cap)
    
    assert abs(eval_res['Base_RAROC'] - 0.14) < 1e-6
    assert eval_res['Trade_Standalone_RAROC'] == 0.05
    assert eval_res['Improves_Portfolio'] is False
    assert eval_res['Meets_Hurdle'] is False
