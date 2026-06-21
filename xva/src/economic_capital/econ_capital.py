"""
Economic Capital Engine (Phase 8).

Computes Economic Capital (EC) based on Unexpected Loss (UL) at a 
high confidence interval (e.g., 99.9% over 1 year) using an approximation of 
Credit Value at Risk (CVaR).
"""
import numpy as np
from typing import Dict, Any


class EconomicCapitalEngine:
    def __init__(self, confidence_level: float = 0.999):
        """
        confidence_level: The target confidence for EC (default 99.9%).
        """
        self.confidence_level = confidence_level
        # Rough multiplier mapping for Normal/Vasicek approximation 
        # (Inverse CDF of standard normal).
        # For 99.9%, norm.ppf(0.999) ~ 3.09
        if confidence_level == 0.999:
            self.z_score = 3.0902
        elif confidence_level == 0.99:
            self.z_score = 2.3263
        else:
            self.z_score = 3.0  # Fallback

    def compute_economic_capital(self,
                                 ead: float,
                                 pd_1y: float,
                                 lgd: float,
                                 asset_correlation: float = 0.15) -> Dict[str, float]:
        """
        Computes the standalone Economic Capital for a counterparty using the
        Asymptotic Single Risk Factor (ASRF) model approximation (Basel-style).
        
        EC = Unexpected Loss = EAD * LGD * [ N( (N^{-1}(PD) + sqrt(R)*N^{-1}(Conf)) / sqrt(1-R) ) - PD ]
        """
        from scipy.stats import norm
        
        if pd_1y <= 0 or pd_1y >= 1 or ead <= 0:
            return {'Expected_Loss': 0.0, 'Unexpected_Loss': 0.0, 'Economic_Capital': 0.0}
            
        el = ead * pd_1y * lgd
        
        # ASRF calculation
        inv_pd = norm.ppf(pd_1y)
        inv_conf = self.z_score
        
        r = asset_correlation
        
        # Stressed PD
        term1 = inv_pd + np.sqrt(r) * inv_conf
        term2 = np.sqrt(1 - r)
        pd_stressed = norm.cdf(term1 / term2)
        
        ul = ead * lgd * (pd_stressed - pd_1y)
        
        return {
            'Expected_Loss': el,
            'Unexpected_Loss': ul,
            'Economic_Capital': ul
        }
