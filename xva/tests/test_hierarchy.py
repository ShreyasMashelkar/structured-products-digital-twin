"""Tests for Hierarchy module (Phase 3)."""
from src.workflow.hierarchy import HierarchyManager


def test_hierarchy_manager_aggregation():
    entities = [
        {'EntityID': 'LE_HDFC', 'EntityName': 'HDFC Bank Ltd'},
        {'EntityID': 'LE_SBI', 'EntityName': 'State Bank of India'}
    ]
    netting_sets = [
        {'NettingSetID': 'NS_HDFC_COLL', 'EntityID': 'LE_HDFC', 'CSA_ID': 'CSA_HDFC_01'},
        {'NettingSetID': 'NS_HDFC_UNCOLL', 'EntityID': 'LE_HDFC', 'CSA_ID': 'UNCOLLATERALISED'}
    ]
    
    trades = [
        {'TradeID': 1, 'Counterparty': 'HDFC', 'CSA_ID': 'CSA_HDFC_01'},
        {'TradeID': 2, 'Counterparty': 'HDFC', 'CSA_ID': 'UNCOLLATERALISED'},
        {'TradeID': 3, 'Counterparty': 'SBI', 'CSA_ID': 'UNCOLLATERALISED'}
    ]
    
    hm = HierarchyManager(entities, netting_sets)
    
    le_grouped = hm.aggregate_by_legal_entity(trades)
    assert 'LE_HDFC' in le_grouped
    assert len(le_grouped['LE_HDFC']) == 2
    assert len(le_grouped['LE_SBI']) == 1  # Fallback to LE_{Counterparty}
    
    ns_grouped = hm.aggregate_by_netting_set(trades)
    assert 'NS_HDFC_COLL' in ns_grouped
    assert 'NS_HDFC_UNCOLL' in ns_grouped
    assert 'NS_SBI_UNCOLL' in ns_grouped  # Fallback
