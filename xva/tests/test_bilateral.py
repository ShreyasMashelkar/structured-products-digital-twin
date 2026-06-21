"""Tests for the Bilateral Valuation engine (Phase 2)."""
import numpy as np
from src.curves.ois_curve import OISCurve
from src.xva.cva import CreditCurve
from src.workflow.bilateral import BilateralValuationEngine


def test_first_to_default_cva_less_than_unilateral():
    ois = OISCurve(np.array([1.0, 5.0]), np.array([0.05, 0.05]))
    eng = BilateralValuationEngine(ois)
    tg = np.linspace(0, 5, 60)
    ee = np.ones_like(tg) * 100.0
    ene = -np.ones_like(tg) * 50.0

    cpty_curve = CreditCurve(500.0)  # High spread
    own_curve_safe = CreditCurve(1.0) # Near risk-free bank
    own_curve_risky = CreditCurve(500.0) # Risky bank
    
    res_safe = eng.compute_first_to_default_bcva(ee, ene, tg, cpty_curve, own_curve_safe)
    res_risky = eng.compute_first_to_default_bcva(ee, ene, tg, cpty_curve, own_curve_risky)
    
    # If bank is risky, FTD CVA should be strictly lower than if bank is safe
    # (since bank defaulting first prevents the counterparty default loss)
    assert res_risky['CVA_FTD'] < res_safe['CVA_FTD']


def test_dva01_is_positive():
    ois = OISCurve(np.array([1.0, 5.0]), np.array([0.05, 0.05]))
    eng = BilateralValuationEngine(ois)
    tg = np.linspace(0, 5, 60)
    ene = -np.ones_like(tg) * 50.0
    
    cpty_curve = CreditCurve(100.0)
    own_curve = CreditCurve(100.0)
    
    dva01 = eng.compute_dva01(ene, tg, cpty_curve, own_curve)
    # Widening bank spread = higher DVA benefit
    assert dva01 > 0.0
