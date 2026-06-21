import numpy as np
from scipy.stats import norm
from typing import Literal, Optional
from src.pricing.sabr import VolSurface, SABRModel, SABRParams

class EuropeanSwaption:
    def __init__(self,
                 notional: float,
                 strike: float,
                 maturity: float,
                 swap_tenor: float,
                 vol_surface: Optional[VolSurface] = None):
        self.notional = notional
        self.strike = strike
        self.maturity = maturity
        self.swap_tenor = swap_tenor
        self.vol_surface = vol_surface

    def get_vol(self, forward_rate: float) -> float:
        """Fetch SABR implied normal vol from the attached VolSurface, or default to 0.20 if none."""
        if self.vol_surface:
            return self.vol_surface.implied_vol(
                expiry=self.maturity,
                tenor=self.swap_tenor,
                F=forward_rate,
                K=self.strike,
            )
        return 0.20

    def price_bachelier(self, forward_swap_rate, normal_vol, annuity):
        """Bachelier (Normal) model for negative rates"""
        d = (forward_swap_rate - self.strike) / (normal_vol * np.sqrt(self.maturity))
        price = annuity * ( (forward_swap_rate - self.strike) * norm.cdf(d) + normal_vol * np.sqrt(self.maturity) * norm.pdf(d) )
        return price * self.notional

    def price_black76(self,
                      forward_rate: float,
                      normal_vol: Optional[float] = None,
                      annuity: float = 1.0,
                      option_type: Literal['payer', 'receiver'] = 'payer') -> float:
        """
        Price European Swaption using Bachelier (Normal) model.
        If normal_vol is None, it is fetched from the attached VolSurface.
        """
        if normal_vol is None:
            normal_vol = self.get_vol(forward_rate)
            
        T = self.maturity
        d = (forward_rate - self.strike) / (normal_vol * np.sqrt(T))
        if option_type == 'payer':
            price = annuity * ((forward_rate - self.strike) * norm.cdf(d) + normal_vol * np.sqrt(T) * norm.pdf(d))
        else:
            price = annuity * ((self.strike - forward_rate) * norm.cdf(-d) + normal_vol * np.sqrt(T) * norm.pdf(d))
        return price * self.notional

    def delta(self, forward_swap_rate, vol, annuity, model='black76',
              option_type='payer'):
        """
        Compute swaption delta dPrice/dF.

        Args:
            forward_swap_rate: Forward swap rate.
            vol: Lognormal volatility (Black-76).
            annuity: Swap annuity factor.
            model: 'black76' (only supported model).
            option_type: 'payer' or 'receiver'.

        Returns:
            Delta in notional units.
        """
        if model == 'black76':
            d1 = (np.log(forward_swap_rate / self.strike) +
                  0.5 * vol**2 * self.maturity) / (vol * np.sqrt(self.maturity))
            if option_type == 'payer':
                return annuity * norm.cdf(d1) * self.notional
            else:
                # Receiver: delta = annuity * (N(d1) - 1) = -annuity * N(-d1)
                return annuity * (norm.cdf(d1) - 1.0) * self.notional
        return 0.0

# ─────────────────────────────────────────────────────────────────────────────
# SABR-enhanced swaption pricing — added as standalone function.
# Imports SABRModel from src.pricing.sabr. Does not modify EuropeanSwaption.
# ─────────────────────────────────────────────────────────────────────────────

def price_swaption_sabr(swaption: 'EuropeanSwaption',
                         forward_swap_rate: float,
                         annuity: float,
                         vol_surface,
                         option_type: str = 'payer') -> float:
    """
    Price a swaption using SABR-implied normal vol from VolSurface.

    This function is additive — it does not modify EuropeanSwaption.
    Fetches SABR vol for the swaption's (maturity, swap_tenor, strike),
    then prices using the existing price_bachelier() method.

    Args:
        swaption: An EuropeanSwaption instance (existing class, unchanged)
        forward_swap_rate: Current forward swap rate
        annuity: Swap annuity factor
        vol_surface: VolSurface instance (from src.pricing.sabr)
        option_type: 'payer' or 'receiver'

    Returns:
        SABR-priced swaption value in notional units
    """
    sabr_vol = vol_surface.implied_vol(
        expiry=swaption.maturity,
        tenor=swaption.swap_tenor,
        F=forward_swap_rate,
        K=swaption.strike
    )
    return swaption.price_bachelier(forward_swap_rate, sabr_vol, annuity)
