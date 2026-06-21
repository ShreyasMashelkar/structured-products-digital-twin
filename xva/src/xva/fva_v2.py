"""
Pathwise FVA Engine (Funding Valuation Adjustment).

Calculates FVA precisely using Monte Carlo NPV paths, rather than relying on
time-averaged Expected Exposure. Handles asymmetric funding costs (borrow vs lend).

Dependencies: Requires the NPV path matrix from HullWhite1F simulation.
"""

import numpy as np


class FVAEngineV2:
    """
    Pathwise FVA Calculation Engine.
    FVA = FCA − FBA  (FCA and FBA are both positive magnitudes)
    """

    def __init__(self,
                 funding_spread_borrow: float = 0.0150,  # 150 bps to borrow
                 funding_spread_lend: float = 0.0050     # 50 bps earned on cash
                 ):
        self.fs_borrow = funding_spread_borrow
        self.fs_lend = funding_spread_lend

    def compute_fva_pathwise(self,
                             time_grid: np.ndarray,
                             npv_paths: np.ndarray,
                             discount_factors: np.ndarray,
                             bank_survival_curve=None,
                             cpty_survival_curve=None) -> dict:
        """
        Compute FVA by integrating the funding cost over each path, then averaging.

        Sign convention (differs from fva.py which uses signed FCA/FBA):
          FCA > 0  = cost of funding positive NPV positions (we borrow)
          FBA > 0  = benefit from negative NPV positions (counterparty funds us)
          FVA = FCA - FBA  (net funding cost; positive = we pay more than we earn)
        fva.py uses: FCA < 0, FBA > 0, FVA = FCA + FBA — equivalent result,
        different sign representation. Both are industry-standard conventions.

        Args:
            time_grid: 1D array of simulation time steps.
            npv_paths: 2D array (n_paths, n_steps) of net NPV per path.
            discount_factors: 1D array of OIS discount factors for time_grid.
            bank_survival_curve: Optional CreditCurve for bank survival probability.
            cpty_survival_curve: Optional CreditCurve for cpty survival probability.

        Returns:
            dict containing FVA, FCA (Cost), and FBA (Benefit)
        """
        n_paths, n_steps = npv_paths.shape
        dt = np.diff(time_grid, prepend=0.0)

        w = np.ones(n_steps)
        if bank_survival_curve is not None:
            if hasattr(bank_survival_curve, 'survival_probability_array'):
                w *= bank_survival_curve.survival_probability_array(time_grid)
            else:
                w *= np.array([bank_survival_curve.survival_probability(t) for t in time_grid])
        if cpty_survival_curve is not None:
            if hasattr(cpty_survival_curve, 'survival_probability_array'):
                w *= cpty_survival_curve.survival_probability_array(time_grid)
            else:
                w *= np.array([cpty_survival_curve.survival_probability(t) for t in time_grid])

        # We need the funding exposure per path, per step
        # If NPV > 0 (we are owed money), we must fund this -> Borrow at fs_borrow
        # If NPV < 0 (we owe money), we have cash -> Lend at fs_lend

        npv_positive = np.maximum(npv_paths, 0.0)
        npv_negative = np.minimum(npv_paths, 0.0)  # These are negative numbers

        # Pathwise Cost (FCA) and Benefit (FBA)
        # FCA = sum( NPV+ * spread_borrow * dt * DF * w ) across time, averaged over paths
        fca_paths = np.sum(npv_positive * self.fs_borrow * dt * discount_factors * w, axis=1)
        fca = float(np.mean(fca_paths))

        # FBA = sum( |NPV-| * spread_lend * dt * DF * w )
        fba_paths = np.sum(np.abs(npv_negative) * self.fs_lend * dt * discount_factors * w, axis=1)
        fba = float(np.mean(fba_paths))

        # FVA = FCA - FBA (Cost - Benefit)
        fva = fca - fba

        return {
            'FVA': fva,   # net = FCA_magnitude - FBA_magnitude
            'FCA': fca,
            'FBA': fba
        }
