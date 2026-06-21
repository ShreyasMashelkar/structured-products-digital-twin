"""
Bilateral Valuation & First-to-Default CVA/DVA Engine (Phase 2).

Computes the true first-to-default Bilateral CVA (BCVA) by incorporating the joint
survival probability of the bank and the counterparty.
    CVA_ftd = LGD_cpty * Sum[ EE(t) * SP_bank(t) * dPD_cpty(t) * DF(t) ]
    DVA_ftd = LGD_bank * Sum[ |ENE(t)| * SP_cpty(t) * dPD_bank(t) * DF(t) ]
    BCVA = CVA_ftd - DVA_ftd

Also provides sensitivities like DVA01 (sensitivity of DVA to own credit spread).
"""
import numpy as np
from typing import Dict
from src.curves.ois_curve import OISCurve
from src.xva.cva import CreditCurve


class BilateralValuationEngine:
    def __init__(self, ois_curve: OISCurve):
        self.ois_curve = ois_curve

    def compute_first_to_default_bcva(self, ee_profile: np.ndarray,
                                      ene_profile: np.ndarray,
                                      time_grid: np.ndarray,
                                      cpty_curve: CreditCurve,
                                      own_curve: CreditCurve) -> Dict[str, float]:
        """Compute FTD CVA, DVA and BCVA."""
        cva = 0.0
        dva = 0.0

        lgd_c = cpty_curve.lgd
        lgd_b = own_curve.lgd

        for i in range(1, len(time_grid)):
            t_prev = time_grid[i - 1]
            t_curr = time_grid[i]
            
            ee_mid = 0.5 * (ee_profile[i - 1] + ee_profile[i])
            ene_mid = 0.5 * (abs(ene_profile[i - 1]) + abs(ene_profile[i]))
            
            df = self.ois_curve.df(t_curr)
            
            # CVA component: Cpty defaults, bank survives
            dPD_c = cpty_curve.default_probability(t_prev, t_curr)
            SP_b = own_curve.survival_probability(t_curr)
            cva += ee_mid * dPD_c * SP_b * df
            
            # DVA component: Bank defaults, cpty survives
            dPD_b = own_curve.default_probability(t_prev, t_curr)
            SP_c = cpty_curve.survival_probability(t_curr)
            dva += ene_mid * dPD_b * SP_c * df
            
        return {
            'CVA_FTD': cva * lgd_c,
            'DVA_FTD': dva * lgd_b,
            'BCVA_FTD': (cva * lgd_c) - (dva * lgd_b)
        }

    def compute_dva01(self, ene_profile: np.ndarray, time_grid: np.ndarray,
                      cpty_curve: CreditCurve, own_curve: CreditCurve) -> float:
        """Sensitivity of FTD DVA to a 1bp widening of own credit spread."""
        # Note: Since DVA represents a benefit (positive in our convention),
        # an increase in own spread should increase DVA.
        base_res = self.compute_first_to_default_bcva(
            np.zeros_like(ene_profile), ene_profile, time_grid, cpty_curve, own_curve)
        
        bumped_curve = own_curve.shift(1.0)
        bumped_res = self.compute_first_to_default_bcva(
            np.zeros_like(ene_profile), ene_profile, time_grid, cpty_curve, bumped_curve)
            
        return bumped_res['DVA_FTD'] - base_res['DVA_FTD']

    def full_bilateral_report(self, ee_profile: np.ndarray, ene_profile: np.ndarray,
                              time_grid: np.ndarray, cpty_curve: CreditCurve,
                              own_curve: CreditCurve) -> Dict[str, float]:
        res = self.compute_first_to_default_bcva(ee_profile, ene_profile, time_grid, cpty_curve, own_curve)
        res['DVA01'] = self.compute_dva01(ene_profile, time_grid, cpty_curve, own_curve)
        return res
