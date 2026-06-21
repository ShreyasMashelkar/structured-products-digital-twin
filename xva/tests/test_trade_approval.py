"""Tests for Trade Approval Workflow (Phase 6)."""
import numpy as np
from src.limits.limit_engine import LimitEngine
from src.raroc.raroc_engine import RAROCEngine
from src.workflow.trade_approval import TradeApprovalWorkflow

class DummyIncrementalXVA:
    def compute_incremental_impact(self, trade, base_portfolio):
        return {'Incremental_Total_XVA': 100.0}

def test_trade_approval_workflow():
    limits = [{'LegalEntityID': 'LE_TEST', 'Metric': 'EAD', 'LimitAmount': 1000.0}]
    limit_eng = LimitEngine(limits)
    raroc_eng = RAROCEngine(hurdle_rate=0.10)
    xva_eng = DummyIncrementalXVA()
    
    app_wf = TradeApprovalWorkflow(limit_eng, raroc_eng, xva_eng)
    
    base_metrics = {'Revenue': 500.0, 'Expected_Loss': 50.0, 'XVA_Costs': 100.0, 'Capital': 2000.0}
    base_limits = {'LE_TEST': {'EAD': 800.0}}
    
    # 1. Good trade (Accretive, no limit breach)
    good_trade = {
        'TradeID': 'T1',
        'Counterparty': 'TEST',
        'Notional': 10000.0,
        'ExpectedRevenue': 200.0,
        'ExpectedLoss': 10.0,
        'CapitalRequired': 500.0,
        'EstimatedEAD': 100.0,  # 800 + 100 = 900 (90% -> AMBER limit) -> wait, AMBER means MANUAL_REVIEW
        'EstimatedPFE': 100.0
    }
    
    res1 = app_wf.evaluate_trade(good_trade, [], base_metrics, base_limits)
    assert res1['Decision'] == 'MANUAL_REVIEW'
    assert 'Approaching Limit' in str(res1['Reasons'])
    
    # 2. Limit Breach
    breach_trade = {
        'TradeID': 'T2',
        'Counterparty': 'TEST',
        'Notional': 10000.0,
        'ExpectedRevenue': 200.0,
        'ExpectedLoss': 10.0,
        'CapitalRequired': 500.0,
        'EstimatedEAD': 300.0,  # 800 + 300 = 1100 (Breach)
        'EstimatedPFE': 100.0
    }
    
    res2 = app_wf.evaluate_trade(breach_trade, [], base_metrics, base_limits)
    assert res2['Decision'] == 'REJECTED'
    
    # 3. Bad RAROC, no limit breach
    bad_raroc_trade = {
        'TradeID': 'T3',
        'Counterparty': 'TEST',
        'Notional': 10000.0,
        'ExpectedRevenue': 10.0, # low revenue
        'ExpectedLoss': 10.0,
        'CapitalRequired': 500.0,
        'EstimatedEAD': 50.0, # 850 (85% -> AMBER limit, but RAROC is bad anyway)
        'EstimatedPFE': 100.0
    }
    
    res3 = app_wf.evaluate_trade(bad_raroc_trade, [], base_metrics, base_limits)
    # Even if limits are amber or pass, bad RAROC makes it MANUAL_REVIEW or REJECTED.
    assert res3['Decision'] == 'MANUAL_REVIEW'
    
    # 4. Perfect Trade
    perfect_trade = {
        'TradeID': 'T4',
        'Counterparty': 'TEST',
        'Notional': 10000.0,
        'ExpectedRevenue': 200.0,
        'ExpectedLoss': 10.0,
        'CapitalRequired': 500.0,
        'EstimatedEAD': 0.0,  # 800 + 0 = 800 (80% -> AMBER... wait, limits are >=0.8 AMBER)
        'EstimatedPFE': 0.0
    }
    # Let's adjust base limits to keep it GREEN
    base_limits_green = {'LE_TEST': {'EAD': 500.0}}
    res4 = app_wf.evaluate_trade(perfect_trade, [], base_metrics, base_limits_green)
    assert res4['Decision'] == 'APPROVED'
