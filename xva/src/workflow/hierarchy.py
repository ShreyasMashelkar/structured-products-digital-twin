"""
Legal Entity & Netting-Set Hierarchy (Phase 3).

Maps Trades -> CSAs -> Netting Sets -> Legal Entities.
Institutional XVA requires aggregation at the Netting Set level for Exposure
and at the Legal Entity level for Capital and Limits.
"""
from typing import Dict, List, Any
import pandas as pd


class HierarchyManager:
    """Manages the resolution of trades to their legal hierarchies."""

    def __init__(self, entities: List[Dict[str, Any]],
                 netting_sets: List[Dict[str, Any]]):
        self.entities = {e['EntityID']: e for e in entities}
        self.netting_sets = {ns['NettingSetID']: ns for ns in netting_sets}
        # Build reverse maps
        # Since UNCOLLATERALISED is shared across counterparties, we map (EntityID, CSA_ID) to NettingSetID
        # For simplicity, we can also map from Counterparty (which often matches EntityID's prefix or similar)
        # but to be robust, we map just CSA_ID -> NettingSetID for unique CSAs.
        # For generic CSAs, we will use a fallback.
        self.csa_to_ns = {}
        for ns in netting_sets:
            if ns.get('CSA_ID') and ns.get('CSA_ID') != 'UNCOLLATERALISED':
                self.csa_to_ns[ns['CSA_ID']] = ns['NettingSetID']
        
        self.ns_to_le = {ns['NettingSetID']: ns['EntityID'] for ns in netting_sets}

    def resolve_trade(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        """Annotates a trade with its full hierarchy context."""
        csa_id = trade.get('CSA_ID', 'UNCOLLATERALISED')
        
        if csa_id != 'UNCOLLATERALISED' and csa_id in self.csa_to_ns:
            ns_id = self.csa_to_ns[csa_id]
        else:
            ns_id = f"NS_{trade.get('Counterparty')}_UNCOLL"
            
        le_id = self.ns_to_le.get(ns_id, f"LE_{trade.get('Counterparty')}")
        
        enriched = trade.copy()
        enriched['NettingSetID'] = ns_id
        enriched['LegalEntityID'] = le_id
        return enriched

    def aggregate_by_legal_entity(self, trades: List[Dict[str, Any]]) -> Dict[str, List[Dict]]:
        """Groups enriched trades by Legal Entity."""
        grouped = {}
        for t in trades:
            enriched = self.resolve_trade(t)
            le_id = enriched['LegalEntityID']
            if le_id not in grouped:
                grouped[le_id] = []
            grouped[le_id].append(enriched)
        return grouped

    def aggregate_by_netting_set(self, trades: List[Dict[str, Any]]) -> Dict[str, List[Dict]]:
        """Groups enriched trades by Netting Set."""
        grouped = {}
        for t in trades:
            enriched = self.resolve_trade(t)
            ns_id = enriched['NettingSetID']
            if ns_id not in grouped:
                grouped[ns_id] = []
            grouped[ns_id].append(enriched)
        return grouped
