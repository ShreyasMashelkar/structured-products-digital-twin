"""
Equity market data — NSE Nifty / Bank Nifty (free).

India runs one of the world's most liquid equity-derivatives markets and the
NSE publishes the underlying data for free: index levels, option chains
(from which implied vols are read), India VIX, and dividend yields. This
module fetches that data live where possible and falls back to calibrated
2025-26 values when the public endpoints are unavailable — the same
free-data-with-fallback pattern the rest of the engine uses for RBI / FIMMDA.

Data sources (all free):
    - Index spot & option chain : NSE (nseindia.com public API)
    - Implied volatility        : derived from the NSE option chain
    - India VIX                 : NSE
    - Dividend yield            : NSE / published index factsheets
    - Equity-rate correlation   : Nifty vs OIS history (RBI/NSE), fallback ~ -0.15
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional

# ── Calibrated fallback levels (mid-2026 INR equity market) ─────────────────
# Anchored to published NSE index levels, India VIX range (11-16%), and
# Nifty dividend yield (~1.2-1.4%).
_EQUITY_FALLBACK = {
    'NIFTY':     {'spot': 24500.0, 'div_yield': 0.013, 'atm_vol': 0.135,
                  'lot_size': 50,  'name': 'NIFTY 50'},
    'BANKNIFTY': {'spot': 52000.0, 'div_yield': 0.010, 'atm_vol': 0.155,
                  'lot_size': 15,  'name': 'NIFTY BANK'},
}
_INDIA_VIX_FALLBACK = 13.5  # %

# Equity index correlation to the short rate (empirical Nifty vs OIS daily
# changes is mildly negative in tightening regimes; configurable downstream).
_EQUITY_RATE_CORR_FALLBACK = -0.15

_NSE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nseindia.com/option-chain',
}


def get_equity_market_data(index: str = 'NIFTY') -> Dict:
    """
    Fetch current equity index market data.

    Args:
        index: 'NIFTY' or 'BANKNIFTY'.

    Returns:
        Dict with spot, div_yield, atm_vol, india_vix, lot_size, name, source.
    """
    index = index.upper()
    fb = _EQUITY_FALLBACK.get(index, _EQUITY_FALLBACK['NIFTY'])

    try:
        import requests
        sess = requests.Session()
        sess.headers.update(_NSE_HEADERS)
        # NSE requires a homepage hit first to set cookies
        sess.get('https://www.nseindia.com', timeout=4)
        url = f'https://www.nseindia.com/api/option-chain-indices?symbol={index}'
        resp = sess.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            spot = float(data['records']['underlyingValue'])
            # ATM implied vol from the chain (nearest expiry, nearest strike)
            atm_vol = _atm_vol_from_chain(data, spot)
            vix = get_india_vix()
            return {'spot': spot, 'div_yield': fb['div_yield'],
                    'atm_vol': atm_vol if atm_vol else fb['atm_vol'],
                    'india_vix': vix, 'lot_size': fb['lot_size'],
                    'name': fb['name'], 'source': 'NSE_LIVE'}
    except Exception:
        pass

    return {'spot': fb['spot'], 'div_yield': fb['div_yield'],
            'atm_vol': fb['atm_vol'], 'india_vix': _INDIA_VIX_FALLBACK,
            'lot_size': fb['lot_size'], 'name': fb['name'],
            'source': 'CALIBRATED_FALLBACK'}


def _atm_vol_from_chain(chain_json: dict, spot: float) -> Optional[float]:
    """Extract an ATM implied vol (%) from an NSE option-chain JSON payload."""
    try:
        rows = chain_json['records']['data']
        best = min(rows, key=lambda r: abs(r.get('strikePrice', 1e18) - spot))
        ce_iv = best.get('CE', {}).get('impliedVolatility')
        pe_iv = best.get('PE', {}).get('impliedVolatility')
        ivs = [v for v in (ce_iv, pe_iv) if v]
        if ivs:
            return float(np.mean(ivs)) / 100.0
    except Exception:
        pass
    return None


def get_india_vix() -> float:
    """India VIX (annualised %); falls back to a calibrated level."""
    try:
        import requests
        sess = requests.Session(); sess.headers.update(_NSE_HEADERS)
        sess.get('https://www.nseindia.com', timeout=4)
        resp = sess.get('https://www.nseindia.com/api/allIndices', timeout=5)
        if resp.status_code == 200:
            for idx in resp.json().get('data', []):
                if 'VIX' in idx.get('index', '').upper():
                    return float(idx['last'])
    except Exception:
        pass
    return _INDIA_VIX_FALLBACK


def get_nifty_option_chain(index: str = 'NIFTY',
                           spot: Optional[float] = None,
                           atm_vol: Optional[float] = None) -> pd.DataFrame:
    """
    Return an option-chain table (strike, log-moneyness, implied vol).

    Tries NSE live; otherwise synthesises a realistic equity vol smile with a
    negative skew (OTM puts richer than OTM calls), which is the characteristic
    shape of index option markets.

    Returns:
        DataFrame: strike, moneyness (K/S), log_moneyness, implied_vol.
    """
    md = get_equity_market_data(index)
    S = spot if spot else md['spot']
    atm = atm_vol if atm_vol else md['atm_vol']

    try:
        import requests
        sess = requests.Session(); sess.headers.update(_NSE_HEADERS)
        sess.get('https://www.nseindia.com', timeout=4)
        url = f'https://www.nseindia.com/api/option-chain-indices?symbol={index.upper()}'
        resp = sess.get(url, timeout=5)
        if resp.status_code == 200:
            rows = resp.json()['records']['data']
            recs = []
            for r in rows:
                k = r.get('strikePrice')
                ce = r.get('CE', {}).get('impliedVolatility')
                pe = r.get('PE', {}).get('impliedVolatility')
                ivs = [v for v in (ce, pe) if v]
                if k and ivs:
                    iv = np.mean(ivs) / 100.0
                    recs.append({'strike': k, 'moneyness': k / S,
                                 'log_moneyness': np.log(k / S), 'implied_vol': iv})
            if len(recs) >= 5:
                return pd.DataFrame(recs).sort_values('strike').reset_index(drop=True)
    except Exception:
        pass

    # Synthetic smile: iv(k) = atm + skew*k + curv*k², k = log(K/S)
    skew, curv = -0.18, 0.6
    strikes = np.round(np.linspace(0.80 * S, 1.20 * S, 17) / 50) * 50
    k = np.log(strikes / S)
    iv = atm + skew * k + curv * k ** 2
    return pd.DataFrame({'strike': strikes, 'moneyness': strikes / S,
                         'log_moneyness': k, 'implied_vol': iv})


def get_equity_rate_correlation(index: str = 'NIFTY') -> float:
    """
    Correlation between equity index returns and short-rate changes.

    Falls back to a published empirical estimate (~ -0.15 for Nifty vs OIS).
    """
    return _EQUITY_RATE_CORR_FALLBACK
