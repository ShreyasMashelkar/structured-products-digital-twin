"""
Equity option pricing — Black-Scholes-Merton with dividends + vol smile.

European index options (Nifty / Bank Nifty) priced under Black-Scholes-Merton
with a continuous dividend yield q. Includes the full Greek set, implied-vol
inversion, and a vol-smile object calibrated to the NSE option chain so that
strike-dependent vols feed the exposure simulation correctly.

Pure NumPy / SciPy.
"""

import numpy as np
from scipy.stats import norm
from typing import Dict, Optional


def _d1_d2(S, K, T, r, q, vol):
    vt = vol * np.sqrt(T)
    d1 = (np.log(S / K) + (r - q + 0.5 * vol ** 2) * T) / vt
    return d1, d1 - vt


def bsm_price(S: float, K: float, T: float, r: float, q: float,
              vol: float, call: bool = True) -> float:
    """Black-Scholes-Merton European option price (per unit, dividend yield q)."""
    if T <= 0:
        return max(S - K, 0.0) if call else max(K - S, 0.0)
    d1, d2 = _d1_d2(S, K, T, r, q, vol)
    if call:
        return S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1)


def bsm_greeks(S: float, K: float, T: float, r: float, q: float,
               vol: float, call: bool = True) -> Dict[str, float]:
    """Full Greek set for a BSM European option."""
    if T <= 0:
        return {k: 0.0 for k in ('delta', 'gamma', 'vega', 'theta', 'rho')}
    d1, d2 = _d1_d2(S, K, T, r, q, vol)
    pdf = norm.pdf(d1)
    disc_q = np.exp(-q * T)
    disc_r = np.exp(-r * T)
    gamma = disc_q * pdf / (S * vol * np.sqrt(T))
    vega = S * disc_q * pdf * np.sqrt(T)          # per 1.00 vol (×0.01 for per %)
    if call:
        delta = disc_q * norm.cdf(d1)
        theta = (-S * disc_q * pdf * vol / (2 * np.sqrt(T))
                 - r * K * disc_r * norm.cdf(d2) + q * S * disc_q * norm.cdf(d1))
        rho = K * T * disc_r * norm.cdf(d2)
    else:
        delta = -disc_q * norm.cdf(-d1)
        theta = (-S * disc_q * pdf * vol / (2 * np.sqrt(T))
                 + r * K * disc_r * norm.cdf(-d2) - q * S * disc_q * norm.cdf(-d1))
        rho = -K * T * disc_r * norm.cdf(-d2)
    return {'delta': float(delta), 'gamma': float(gamma), 'vega': float(vega),
            'theta': float(theta), 'rho': float(rho)}


def implied_vol(price: float, S: float, K: float, T: float, r: float, q: float,
                call: bool = True, tol: float = 1e-7, max_iter: int = 100) -> float:
    """Invert BSM for implied vol (Newton with a bisection safety net)."""
    if T <= 0 or price <= 0:
        return float('nan')
    lo, hi = 1e-4, 5.0
    vol = 0.20
    for _ in range(max_iter):
        p = bsm_price(S, K, T, r, q, vol, call)
        v = bsm_greeks(S, K, T, r, q, vol, call)['vega']
        diff = p - price
        if abs(diff) < tol:
            return vol
        if v > 1e-10:
            step = diff / v
            new = vol - step
            if lo < new < hi:
                vol = new
                continue
        # bisection fallback
        if diff > 0:
            hi = vol
        else:
            lo = vol
        vol = 0.5 * (lo + hi)
    return vol


class EquityVolSmile:
    """
    Strike-dependent implied vol from an option chain (quadratic in
    log-moneyness), used to price/exposure-simulate index options with skew.
    """

    def __init__(self, atm_vol: float, skew: float = -0.18, curv: float = 0.6):
        self.atm_vol = atm_vol
        self.skew = skew
        self.curv = curv

    @classmethod
    def from_chain(cls, chain_df, atm_vol: float) -> 'EquityVolSmile':
        """Fit vol = a + skew·k + curv·k² to a chain DataFrame (k=log-moneyness)."""
        k = chain_df['log_moneyness'].values
        iv = chain_df['implied_vol'].values
        A = np.column_stack([np.ones_like(k), k, k ** 2])
        coef, *_ = np.linalg.lstsq(A, iv, rcond=None)
        smile = cls(atm_vol=float(coef[0]), skew=float(coef[1]), curv=float(coef[2]))
        return smile

    def vol(self, strike: float, forward: float) -> float:
        k = np.log(strike / forward)
        return float(max(self.atm_vol + self.skew * k + self.curv * k ** 2, 0.01))


class EquityOption:
    """A European index option with BSM pricing and Greeks."""

    def __init__(self, strike: float, maturity: float, call: bool = True,
                 lot_size: int = 50, n_lots: int = 1):
        self.strike = strike
        self.maturity = maturity
        self.call = call
        self.lot_size = lot_size
        self.n_lots = n_lots

    @property
    def units(self) -> int:
        return self.lot_size * self.n_lots

    def price(self, S: float, r: float, q: float, vol: float,
              t: float = 0.0) -> float:
        """Total option value (₹) at calendar time t with spot S."""
        T = max(self.maturity - t, 0.0)
        return self.units * bsm_price(S, self.strike, T, r, q, vol, self.call)

    def greeks(self, S: float, r: float, q: float, vol: float,
               t: float = 0.0) -> Dict[str, float]:
        T = max(self.maturity - t, 0.0)
        g = bsm_greeks(S, self.strike, T, r, q, vol, self.call)
        return {k: v * self.units for k, v in g.items()}
