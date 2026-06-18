"""Closed-form cash-or-nothing digital — the MC benchmark for discontinuous payoffs (L4).

The digital is the canonical case where pathwise Greeks fail and likelihood-ratio is needed
(L5); having its exact price here pins down both the price and, later, those Greeks.
"""

from __future__ import annotations

from math import exp

from spdt.pricing.analytic.black_scholes import _d1_d2, _norm_cdf


def bs_cash_or_nothing(
    spot: float,
    strike: float,
    t: float,
    r: float,
    q: float,
    sigma: float,
    is_call: bool,
    payout: float = 1.0,
) -> float:
    """Price of a cash-or-nothing digital paying ``payout`` if in the money at expiry."""
    if t <= 0.0 or sigma <= 0.0:
        hit = (spot > strike) if is_call else (spot < strike)
        return exp(-r * t) * payout * float(hit)
    _, d2 = _d1_d2(spot, strike, t, r, q, sigma)
    prob = _norm_cdf(d2) if is_call else _norm_cdf(-d2)
    return exp(-r * t) * payout * prob
