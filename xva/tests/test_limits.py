"""Tests for Counterparty Limit Management engine (Phase 4)."""
from src.limits.limit_engine import LimitEngine

def test_limit_engine_checks():
    limits = [
        {'LegalEntityID': 'LE_HDFC', 'Metric': 'PFE_95', 'LimitAmount': 100.0},
        {'LegalEntityID': 'LE_HDFC', 'Metric': 'EAD', 'LimitAmount': 500.0},
        {'LegalEntityID': 'LE_SBI', 'Metric': 'PFE_95', 'LimitAmount': 50.0}
    ]
    
    eng = LimitEngine(limits)
    
    metrics = {
        'LE_HDFC': {'PFE_95': 85.0, 'EAD': 400.0},
        'LE_SBI': {'PFE_95': 60.0}
    }
    
    res = eng.check_limits(metrics)
    assert len(res) == 3
    
    # HDFC PFE is 85/100 = 85% -> AMBER
    hdfc_pfe = res[(res['LegalEntityID'] == 'LE_HDFC') & (res['Metric'] == 'PFE_95')].iloc[0]
    assert hdfc_pfe['Status'] == 'AMBER'
    
    # HDFC EAD is 400/500 = 80% -> AMBER
    hdfc_ead = res[(res['LegalEntityID'] == 'LE_HDFC') & (res['Metric'] == 'EAD')].iloc[0]
    assert hdfc_ead['Status'] == 'AMBER'
    
    # SBI PFE is 60/50 = 120% -> BREACH
    sbi_pfe = res[(res['LegalEntityID'] == 'LE_SBI') & (res['Metric'] == 'PFE_95')].iloc[0]
    assert sbi_pfe['Status'] == 'BREACH'

def test_pre_trade_check():
    limits = [{'LegalEntityID': 'LE_HDFC', 'Metric': 'PFE_95', 'LimitAmount': 100.0}]
    eng = LimitEngine(limits)
    
    base = {'LE_HDFC': {'PFE_95': 70.0}}
    trade_incr = {'PFE_95': 40.0}
    
    res = eng.pre_trade_check(base, trade_incr, 'LE_HDFC')
    # 70 + 40 = 110 -> BREACH
    assert res.iloc[0]['Status'] == 'BREACH'
