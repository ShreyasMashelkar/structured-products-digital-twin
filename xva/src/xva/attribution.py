class XVAAttribution:
    """Computes day-over-day attribution of XVA changes."""
    
    @staticmethod
    def explain_cva_change(cva_yesterday: float, cva_today: float, 
                           spread_move_bps: float, exposure_change_pct: float) -> dict:
        """
        Approximate first-order Taylor expansion for CVA attribution.
        In a real system, this is computed by bumping curves one by one.
        Here we use a simplified parametric attribution.
        """
        total_change = cva_today - cva_yesterday
        
        # Spread attribution (rough proxy: sensitivity to spread * move)
        # CS01 proxy ~ CVA / Spread
        # If spread is 100bps, 1bp move = 1% of CVA
        # We assume base spread is around 100bps for normalization
        base_spread = 100.0
        cs01 = cva_yesterday / base_spread
        spread_attribution = cs01 * spread_move_bps
        
        # Exposure attribution
        exposure_attribution = cva_yesterday * exposure_change_pct
        
        # Time decay and unexplained cross-gamma
        time_decay = - (cva_yesterday / 365.0)  # simple linear decay per day
        
        unexplained = total_change - (spread_attribution + exposure_attribution + time_decay)
        
        return {
            'Total Change': total_change,
            'Spread Move': spread_attribution,
            'Exposure Move': exposure_attribution,
            'Time Decay': time_decay,
            'Unexplained': unexplained
        }

def compute_cva_attribution(ee_profile, time_grid, credit_curve, ois_curve,
                             rate_shock_bps=1.0, spread_shock_bps=1.0):
    """
    Decomposes CVA change into:
      - IR01: sensitivity to 1bp parallel rate shift
      - CS01: sensitivity to 1bp CDS spread widening
    Returns dict with base_cva, ir01, cs01.
    """
    from src.xva.cva import CVAEngine
    engine = CVAEngine(ois_curve)
    base_cva = engine.compute_cva(ee_profile, time_grid, credit_curve)
    
    # CS01 (already in CVAEngine.cva_sensitivity — just call it)
    cs01 = engine.cva_sensitivity(ee_profile, time_grid, credit_curve, spread_shock_bps)
    
    # IR01: shift the OIS curve, recompute CVA (exposure unchanged, DF changes)
    shocked_ois = ois_curve.shift(rate_shock_bps)
    ir01_engine = CVAEngine(shocked_ois)
    ir01 = ir01_engine.compute_cva(ee_profile, time_grid, credit_curve) - base_cva
    
    return {'base_cva': base_cva, 'cs01': cs01, 'ir01': ir01}
