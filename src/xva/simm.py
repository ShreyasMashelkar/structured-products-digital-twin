"""
ISDA SIMM v2.7 Initial Margin Calculator and MVA Engine.

Calculates Initial Margin (IM) under the ISDA Standard Initial Margin Model.
Calculates MVA (Margin Valuation Adjustment) over the life of the trade using
Dynamic Initial Margin simulation.

Data Source:
  SIMM Risk Weights and Correlations are sourced directly from the publicly
  available ISDA SIMM v2.7 methodology document (free).
"""

import numpy as np


class SIMMCalculator:
    """
    Computes Initial Margin for an INR Interest Rate Swap portfolio.
    Implements a simplified version of ISDA SIMM v2.7 for a single currency
    Interest Rate delta risk class.
    """

    # ISDA SIMM v2.7 Risk Weights for Regular Volatility Currencies (like INR)
    # Tenors: 2W, 1M, 3M, 6M, 1Y, 2Y, 3Y, 5Y, 10Y, 15Y, 20Y, 30Y
    RW_RATES = {
        '2W': 114,
        '1M': 114,
        '3M': 89,
        '6M': 70,
        '1Y': 54,
        '2Y': 43,
        '3Y': 38,
        '5Y': 34,
        '10Y': 34,
        '15Y': 34,
        '20Y': 34,
        '30Y': 34
    }

    # ISDA SIMM v2.7 Correlation matrix across tenors (12x12)
    CORR_RATES = np.array([
        [1.00, 1.00, 0.98, 0.92, 0.85, 0.74, 0.66, 0.53, 0.37, 0.28, 0.23, 0.16], # 2W
        [1.00, 1.00, 0.98, 0.92, 0.85, 0.74, 0.66, 0.53, 0.37, 0.28, 0.23, 0.16], # 1M
        [0.98, 0.98, 1.00, 0.96, 0.90, 0.80, 0.73, 0.60, 0.43, 0.33, 0.28, 0.19], # 3M
        [0.92, 0.92, 0.96, 1.00, 0.96, 0.88, 0.81, 0.69, 0.51, 0.40, 0.34, 0.24], # 6M
        [0.85, 0.85, 0.90, 0.96, 1.00, 0.95, 0.89, 0.78, 0.60, 0.48, 0.42, 0.30], # 1Y
        [0.74, 0.74, 0.80, 0.88, 0.95, 1.00, 0.97, 0.89, 0.73, 0.61, 0.53, 0.40], # 2Y
        [0.66, 0.66, 0.73, 0.81, 0.89, 0.97, 1.00, 0.95, 0.81, 0.69, 0.62, 0.48], # 3Y
        [0.53, 0.53, 0.60, 0.69, 0.78, 0.89, 0.95, 1.00, 0.91, 0.81, 0.74, 0.59], # 5Y
        [0.37, 0.37, 0.43, 0.51, 0.60, 0.73, 0.81, 0.91, 1.00, 0.96, 0.91, 0.78], # 10Y
        [0.28, 0.28, 0.33, 0.40, 0.48, 0.61, 0.69, 0.81, 0.96, 1.00, 0.97, 0.87], # 15Y
        [0.23, 0.23, 0.28, 0.34, 0.42, 0.53, 0.62, 0.74, 0.91, 0.97, 1.00, 0.92], # 20Y
        [0.16, 0.16, 0.19, 0.24, 0.30, 0.40, 0.48, 0.59, 0.78, 0.87, 0.92, 1.00]  # 30Y
    ])

    def __init__(self):
        self.tenor_labels = ['2W', '1M', '3M', '6M', '1Y', '2Y', '3Y', '5Y', '10Y', '15Y', '20Y', '30Y']
        self.rw = np.array([self.RW_RATES[t] for t in self.tenor_labels])

    def compute_im_rates_delta(self, sensitivities: dict) -> float:
        """
        Compute SIMM IM for Interest Rate Delta.
        Args:
            sensitivities: Dict of DV01 sensitivities per tenor (e.g., {'5Y': 1000})
        Returns:
            Initial Margin in INR
        """
        # 1. Map sensitivities to SIMM buckets
        s = np.zeros(len(self.tenor_labels))
        for i, t in enumerate(self.tenor_labels):
            s[i] = sensitivities.get(t, 0.0)

        # 2. Multiply by Risk Weights
        ws = s * self.rw

        # 3. Aggregate using correlation matrix
        # Variance = Sum(ws_i^2) + Sum(ws_i * ws_j * corr_ij)
        variance = ws.T @ self.CORR_RATES @ ws

        # SIMM IM is the square root of the variance
        return np.sqrt(max(variance, 0.0))


class MVAEngineV2:
    """
    Margin Valuation Adjustment Engine using SIMM.

    Calculates MVA by simulating Dynamic Initial Margin (DIM) over time.
    MVA = sum( IM(t) * funding_spread * dt * DF(t) )
    """

    def __init__(self, funding_spread: float = 0.01):
        """
        Args:
            funding_spread: Cost of funding IM (e.g., OIS + spread)
        """
        self.funding_spread = funding_spread
        self.simm = SIMMCalculator()

    def compute_mva(self,
                    time_grid: np.ndarray,
                    expected_im_profile: np.ndarray,
                    discount_factors: np.ndarray) -> float:
        """
        Compute MVA from a pre-calculated IM profile.

        Args:
            time_grid: 1D array of time steps
            expected_im_profile: 1D array of expected IM at each time step
            discount_factors: 1D array of discount factors

        Returns:
            MVA value
        """
        dt = np.diff(time_grid, prepend=0.0)
        mva_increments = expected_im_profile * self.funding_spread * dt * discount_factors
        return float(np.sum(mva_increments))

    def estimate_dim_profile(self,
                             trade_maturity: float,
                             time_grid: np.ndarray,
                             initial_sensitivities: dict) -> np.ndarray:
        """
        Estimate Dynamic Initial Margin (DIM) profile.

        In a full implementation, sensitivities are simulated pathwise.
        For a fast approximation, IM is assumed to scale with the remaining
        square root of time or proportional to the amortization of the trade.
        """
        im_t0 = self.simm.compute_im_rates_delta(initial_sensitivities)

        im_profile = np.zeros_like(time_grid)
        for i, t in enumerate(time_grid):
            if t >= trade_maturity:
                im_profile[i] = 0.0
            else:
                # Linear amortization proxy
                im_profile[i] = im_t0 * (trade_maturity - t) / trade_maturity

        return im_profile


# ─────────────────────────────────────────────────────────────────────
# SIMM FX Delta Risk Class  (ISDA SIMM v2.7 §4.3)
# ─────────────────────────────────────────────────────────────────────

class SIMMFXDeltaCalculator:
    """
    ISDA SIMM v2.7 FX Delta Risk Class.

    INR is Category 2 (regular volatility currency).

    Risk Weights (ISDA SIMM v2.7, Table 15, in %):
        Cat1 × Cat1: 7.4%
        Cat1 × Cat2 or Cat2 × Cat2: 13.6%
        Cat3: 21.0%

    Source: ISDA SIMM v2.7 Methodology (free at isda.org)
    """

    FX_RISK_WEIGHTS = {
        ('cat1','cat1'): 7.4,  ('cat1','cat2'): 13.6,
        ('cat2','cat1'): 13.6, ('cat2','cat2'): 13.6,
        ('cat2','cat3'): 13.6, ('cat3','cat2'): 13.6,
        ('cat3','cat3'): 21.0,
    }
    FX_CORR_SAME_CAT = 0.50
    FX_CORR_DIFF_CAT = 0.27
    CAT1 = {'USD','EUR','JPY','GBP','AUD','CHF','CAD'}
    CAT2 = {'INR','SGD','HKD','NZD','NOK','SEK','DKK',
            'ZAR','TRY','KRW','CNY','TWD','THB','IDR'}

    def _cat(self, ccy: str) -> str:
        ccy = ccy.upper()
        if ccy in self.CAT1: return 'cat1'
        if ccy in self.CAT2: return 'cat2'
        return 'cat3'

    def _rw(self, ccy1: str, ccy2: str) -> float:
        c1, c2 = self._cat(ccy1), self._cat(ccy2)
        return self.FX_RISK_WEIGHTS.get((c1,c2),
               self.FX_RISK_WEIGHTS.get((c2,c1), 13.6))

    def compute_fx_delta_im(self, fx_sensitivities: dict) -> float:
        """
        Compute SIMM IM for FX delta risk.

        Args:
            fx_sensitivities: {currency_pair: FX delta sensitivity}
                e.g. {'USD/INR': 50_000_000}
                Sensitivity units: base currency amount (₹ or USD).

        Returns:
            Initial Margin in same units as sensitivities.
        """
        pairs = list(fx_sensitivities.keys())
        if not pairs:
            return 0.0

        ws = {}
        pair_ccys = {}
        for pair in pairs:
            ccy1, ccy2 = pair.split('/') if '/' in pair else (pair[:3], pair[3:])
            pair_ccys[pair] = (ccy1, ccy2)
            ws[pair] = (self._rw(ccy1, ccy2) / 100.0) * abs(fx_sensitivities[pair])

        variance = 0.0
        for p1 in pairs:
            for p2 in pairs:
                if p1 == p2:
                    rho = 1.0
                else:
                    c1 = self._cat(pair_ccys[p1][0])
                    c2 = self._cat(pair_ccys[p2][0])
                    rho = self.FX_CORR_SAME_CAT if c1 == c2 else self.FX_CORR_DIFF_CAT
                variance += rho * ws[p1] * ws[p2]

        return float(np.sqrt(max(variance, 0.0)))


class SIMMEquityDeltaCalculator:
    """
    ISDA SIMM v2.7 Equity Delta Risk Class.

    Bucket definitions (ISDA SIMM v2.7 Table 11):
        1: Large cap Consumer   2: Large cap Telecom
        3: Large cap Industry   4: Large cap Financial (HDFC, SBI, ICICI)
        5: Large cap Tech/IT    6: Small/Mid cap Indian
        7: Large cap EM         8: Indices/ETFs (Nifty 50, Bank Nifty)

    Risk Weights (ISDA SIMM v2.7, Table 12, in %).
    Source: ISDA SIMM v2.7 Methodology (free at isda.org)
    """

    EQ_RISK_WEIGHTS = {
        1: 22.0, 2: 26.0, 3: 28.0, 4: 24.0,
        5: 23.0, 6: 32.0, 7: 26.0, 8: 21.0,
        'residual': 32.0,
    }
    EQ_SAME_BUCKET_CORR = 0.99
    EQ_DIFF_BUCKET_CORR = {
        (1,2):0.15,(1,3):0.14,(1,4):0.16,(1,5):0.16,
        (2,3):0.19,(2,4):0.19,(2,5):0.20,
        (3,4):0.21,(3,5):0.19,(4,5):0.21,
        (1,8):0.35,(2,8):0.35,(3,8):0.35,(4,8):0.35,
        (5,8):0.35,(6,8):0.35,(7,8):0.35,
    }

    def _corr(self, b1, b2) -> float:
        if b1 == b2: return self.EQ_SAME_BUCKET_CORR
        return self.EQ_DIFF_BUCKET_CORR.get(
            (min(b1,b2), max(b1,b2)), 0.15)

    def compute_equity_delta_im(self, equity_sensitivities: dict) -> float:
        """
        Compute SIMM IM for equity delta risk.

        Args:
            equity_sensitivities: {bucket_number: sensitivity_amount}
                e.g. {4: 10_000_000, 8: 5_000_000}
                Sensitivity = delta (₹ change per 1% equity move).

        Returns:
            Initial Margin in same units as sensitivities.
        """
        if not equity_sensitivities:
            return 0.0
        bucket_ws = {
            b: (self.EQ_RISK_WEIGHTS.get(b, self.EQ_RISK_WEIGHTS['residual']) / 100.0)
               * abs(s)
            for b, s in equity_sensitivities.items()
        }
        buckets  = list(bucket_ws.keys())
        variance = sum(
            self._corr(b1, b2) * bucket_ws[b1] * bucket_ws[b2]
            for b1 in buckets for b2 in buckets
        )
        return float(np.sqrt(max(variance, 0.0)))


class SIMMMultiClassCalculator:
    """
    Combined ISDA SIMM v2.7 calculator covering IR, FX, and Equity delta.

    Cross-risk-class correlations (ISDA SIMM v2.7 §5):
        ρ_IR_FX = 0.27,  ρ_IR_EQ = 0.22,  ρ_FX_EQ = 0.27
    """

    CROSS_CLASS_CORR = {
        ('IR','FX'): 0.27, ('FX','IR'): 0.27,
        ('IR','EQ'): 0.22, ('EQ','IR'): 0.22,
        ('FX','EQ'): 0.27, ('EQ','FX'): 0.27,
    }

    def __init__(self):
        self.ir_calc = SIMMCalculator()
        self.fx_calc = SIMMFXDeltaCalculator()
        self.eq_calc = SIMMEquityDeltaCalculator()

    def compute_total_im(self, ir_sensitivities: dict = None,
                         fx_sensitivities: dict = None,
                         equity_sensitivities: dict = None) -> dict:
        """
        Compute total SIMM IM across IR, FX, and Equity risk classes.

        Args:
            ir_sensitivities:     {tenor: DV01}
            fx_sensitivities:     {pair: delta}
            equity_sensitivities: {bucket: delta}

        Returns:
            Dict with IM_IR, IM_FX, IM_EQ, IM_Total.
        """
        im_ir = self.ir_calc.compute_im_rates_delta(ir_sensitivities or {})
        im_fx = self.fx_calc.compute_fx_delta_im(fx_sensitivities or {})
        im_eq = self.eq_calc.compute_equity_delta_im(equity_sensitivities or {})

        class_ims = {'IR': im_ir, 'FX': im_fx, 'EQ': im_eq}
        classes   = ['IR', 'FX', 'EQ']
        variance  = sum(
            self.CROSS_CLASS_CORR.get((c1,c2), (1.0 if c1==c2 else 0.20))
            * class_ims[c1] * class_ims[c2]
            for c1 in classes for c2 in classes
        )
        return {
            'IM_IR': im_ir, 'IM_FX': im_fx,
            'IM_EQ': im_eq, 'IM_Total': float(np.sqrt(max(variance, 0.0))),
        }
