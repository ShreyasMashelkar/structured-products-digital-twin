"""
SABR Stochastic Volatility Model for INR Swaption Pricing.

DISCLAIMER: INR swaption vol surface is NOT freely available.
Synthetic surface uses realized vol from free DBIE data as the ATM anchor.
See module docstring for full data source details.
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import norm
from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class SABRParams:
    alpha: float   # initial vol (σ₀)
    beta: float    # CEV exponent
    rho: float     # fwd-vol correlation
    nu: float      # vol-of-vol


class SABRModel:
    """
    SABR stochastic vol model using Hagan et al. (2002) normal vol approximation.

    For INR rates (positive but close to bounds), the normal SABR approximation
    is more appropriate than the log-normal version.
    """

    def __init__(self, params: SABRParams):
        self.params = params

    def implied_normal_vol(self, F: float, K: float, T: float) -> float:
        """
        Hagan et al. (2002) SABR normal (Bachelier) vol approximation.

        Args:
            F: Forward rate
            K: Strike rate
            T: Option expiry in years

        Returns:
            Implied normal vol (absolute, not percentage)
        """
        alpha, beta, rho, nu = (self.params.alpha, self.params.beta,
                                 self.params.rho, self.params.nu)
        if abs(F - K) < 1e-8:
            # ATM formula
            FK_mid = F
            vol = (alpha / (FK_mid**(1-beta)) *
                   (1 + ((1-beta)**2/24 * alpha**2/FK_mid**(2*(1-beta))
                         + rho*beta*nu*alpha/(4*FK_mid**(1-beta))
                         + (2-3*rho**2)/24 * nu**2) * T))
        else:
            z = nu/alpha * (F*K)**((1-beta)/2) * np.log(F/K)
            x_z = np.log((np.sqrt(1 - 2*rho*z + z**2) + z - rho) / (1 - rho))
            if abs(x_z) < 1e-10:
                zx = 1.0
            else:
                zx = z / x_z
            fk_mid = (F*K)**((1-beta)/2)
            log_fk = np.log(F/K)
            vol = (alpha / (fk_mid * (1 + (1-beta)**2/24 * log_fk**2
                                       + (1-beta)**4/1920 * log_fk**4))
                   * zx
                   * (1 + ((1-beta)**2/24 * alpha**2/fk_mid**2
                           + rho*beta*nu*alpha/(4*fk_mid)
                           + (2-3*rho**2)/24 * nu**2) * T))
        return max(vol, 1e-6)

    def smile(self, F: float, strikes: np.ndarray, T: float) -> np.ndarray:
        """Vol smile across strikes for a given expiry."""
        return np.array([self.implied_normal_vol(F, K, T) for K in strikes])

    @classmethod
    def calibrate_to_smile(cls, F: float, strikes: np.ndarray,
                            market_vols: np.ndarray, T: float,
                            beta: float = 0.5) -> 'SABRModel':
        """
        Calibrate SABR to a single-expiry smile (fix beta, fit alpha/rho/nu).
        """
        def objective(params):
            alpha, rho, nu = params
            if alpha <= 0 or nu <= 0 or abs(rho) >= 1:
                return 1e10
            p = SABRParams(alpha=alpha, beta=beta, rho=rho, nu=nu)
            model = cls(p)
            model_vols = model.smile(F, strikes, T)
            return np.sum((model_vols - market_vols)**2)

        x0 = [market_vols[len(market_vols)//2], -0.15, 0.35]
        bounds = [(1e-4, 0.5), (-0.95, 0.95), (0.01, 3.0)]
        res = minimize(objective, x0, method='L-BFGS-B', bounds=bounds)
        alpha, rho, nu = res.x
        return cls(SABRParams(alpha=alpha, beta=beta, rho=rho, nu=nu))


class VolSurface:
    """
    Full INR swaption vol surface: expiry × tenor grid, one SABRModel per slice.

    DISCLAIMER: No free source for INR swaption vols exists.
    The synthetic surface uses realized vol from RBI DBIE MIBOR as the
    ATM anchor. The smile shape (rho, nu) uses parameters from published
    INR rates market research. This is suitable for SABR machinery
    demonstration; replace build_from_market_data() with a live feed
    for production use.
    """

    EXPIRIES = [0.25, 0.5, 1.0, 2.0, 5.0]      # years
    TENORS   = [1.0, 2.0, 5.0, 10.0]            # swap tenors in years

    def __init__(self):
        # key: (expiry, tenor) → SABRModel
        self._models: dict = {}
        self._atm_vols: dict = {}   # key: (expiry, tenor) → ATM normal vol

    def add_slice(self, expiry: float, tenor: float, sabr: SABRModel,
                   atm_vol: float):
        self._models[(expiry, tenor)] = sabr
        self._atm_vols[(expiry, tenor)] = atm_vol

    def implied_vol(self, expiry: float, tenor: float,
                    F: float, K: float) -> float:
        """Interpolate vol surface at given expiry/tenor/strike."""
        if not hasattr(self, '_models') or not self._models:
            return 0.0050  # Fallback 50 bps
            
        key = (expiry, tenor)
        if key in self._models:
            return self._models[key].implied_normal_vol(F, K, expiry)
        # Nearest-expiry fallback
        nearest = min(self._models.keys(), key=lambda k: abs(k[0]-expiry) + abs(k[1]-tenor))
        return self._models[nearest].implied_normal_vol(F, K, expiry)

    def to_dataframe(self) -> pd.DataFrame:
        """Export ATM vols across the surface grid."""
        rows = []
        for (exp, ten), vol in self._atm_vols.items():
            rows.append({'expiry_years': exp, 'tenor_years': ten,
                         'atm_normal_vol_bps': vol * 10000})
        return pd.DataFrame(rows).sort_values(['expiry_years', 'tenor_years'])

    @classmethod
    def build_from_market_data(cls, sigma_realized: Optional[float] = None) -> 'VolSurface':
        """
        Build synthetic INR vol surface anchored to free DBIE data.

        DISCLAIMER: INR swaption vols are NOT freely available.
        ATM vol is anchored to realized vol from RBI DBIE MIBOR history.
        The term structure and smile shape are informed by published
        research on INR rates markets.

        Args:
            sigma_realized: If provided (e.g. from HullWhiteCalibrator),
                            use as ATM vol anchor. Otherwise fetched from DBIE.
        """
        if sigma_realized is None:
            from src.data_ingestion.market_data import get_historical_mibor
            df = get_historical_mibor(n_days=252)
            daily_changes = np.diff(df['mibor_rate'].values)
            sigma_realized = float(np.std(daily_changes) * np.sqrt(252))

        surface = cls()

        # ATM vol term structure: short expiry higher, long expiry lower
        # Typical INR: 1M expiry ~80-100bps normal, 5Y expiry ~50-60bps normal
        expiry_multipliers = {0.25: 1.30, 0.5: 1.20, 1.0: 1.10, 2.0: 1.00, 5.0: 0.85}
        tenor_multipliers  = {1.0: 0.90, 2.0: 0.95, 5.0: 1.00, 10.0: 1.05}

        # INR smile params from published research (mild negative skew)
        # rho ≈ -0.15 to -0.25 (rates up → vol down, typical for INR)
        # nu ≈ 0.30-0.50 (moderate vol-of-vol)
        beta = 0.5   # CEV exponent: CIR-type

        for expiry in cls.EXPIRIES:
            for tenor in cls.TENORS:
                atm_vol = sigma_realized * expiry_multipliers[expiry] * tenor_multipliers[tenor]
                rho = -0.15 - 0.05 * (tenor / 10.0)    # mild negative skew
                nu  = 0.35 + 0.05 * expiry              # vol-of-vol rises with expiry
                alpha = atm_vol * (1 + (1-beta)**2/24 * atm_vol**2)  # approx
                params = SABRParams(alpha=alpha, beta=beta, rho=rho, nu=nu)
                sabr = SABRModel(params)
                surface.add_slice(expiry, tenor, sabr, atm_vol)

        return surface
