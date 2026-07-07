"""Barrier probability calculations.

Institutional desks use barrier-hit probabilities to drive lifecycle decisions. A high hit
probability supports pre-unwind for knock-outs; knock-ins instead transition to vanilla exposure
once activated.

This module provides closed-form (Merton) continuous barrier hit probabilities under
Black-Scholes, and distances in standard deviations.
"""

from __future__ import annotations

from math import erf, exp, log, sqrt

import numpy as np


class BarrierProbabilityEngine:
    """Calculates first-hitting-time probabilities for barriers."""

    @staticmethod
    def _norm_cdf(x: float) -> float:
        return 0.5 * (1.0 + erf(x / sqrt(2.0)))

    @classmethod
    def p_hit(
        cls, spot: float, barrier: float, sigma: float, t: float, r: float, q: float, is_down: bool
    ) -> float:
        """Probability of hitting the barrier before expiry T (continuous monitoring)."""
        if t <= 0.0 or sigma <= 0.0:
            return 1.0 if (spot <= barrier if is_down else spot >= barrier) else 0.0

        if (is_down and spot <= barrier) or (not is_down and spot >= barrier):
            return 1.0

        # Merton's formula for the maximum/minimum of geometric Brownian motion
        mu = r - q - 0.5 * sigma * sigma
        vol = sigma * sqrt(t)

        # We model X_t = ln(S_t / S_0), with barrier b = ln(B / S_0)
        b = log(barrier / spot)

        # The probability that min(X_t) <= b (for down barrier)
        # or max(X_t) >= b (for up barrier).
        # By symmetry, P(min(X_t) <= b) for mu is related to P(max(X_t) >= -b) for -mu.

        if not is_down:
            # Up barrier: we want P(max X_s >= b)
            # P = N((-b + mu * t) / vol) + exp(2 * mu * b / sigma^2) * N((-b - mu * t) / vol)
            term1 = (-b + mu * t) / vol
            term2 = (-b - mu * t) / vol
            return cls._norm_cdf(term1) + exp(2 * mu * b / (sigma * sigma)) * cls._norm_cdf(term2)
        else:
            # Down barrier: we want P(min X_s <= b) where b < 0
            # P = N((b - mu * t) / vol) + exp(2 * mu * b / sigma^2) * N((b + mu * t) / vol)
            term1 = (b - mu * t) / vol
            term2 = (b + mu * t) / vol
            return cls._norm_cdf(term1) + exp(2 * mu * b / (sigma * sigma)) * cls._norm_cdf(term2)

    @classmethod
    def distance_to_barrier(cls, spot: float, barrier: float, sigma: float, t: float) -> float:
        """Distance to the barrier in standard deviations (simplified log-normal space)."""
        if t <= 0.0 or sigma <= 0.0:
            return 0.0
        return abs(log(spot / barrier)) / (sigma * sqrt(t))

    @classmethod
    def p_hit_discrete(
        cls,
        spot: float,
        barrier: float,
        sigma: float,
        monitoring_times: tuple[float, ...],
        r: float,
        q: float,
        is_down: bool,
        *,
        n_paths: int = 40_000,
        seed: int = 811,
    ) -> float:
        """Risk-neutral hit probability on the *contractual* observation schedule.

        A terminal-only knock-in is not a continuously monitored barrier.  Using the Merton
        first-passage probability for it can overstate lifecycle risk by multiples, so the desk
        monitor evaluates the exact discrete schedule with deterministic Monte Carlo.
        """
        times = tuple(sorted(t for t in set(monitoring_times) if t > 0.0))
        if not times:
            return 1.0 if (spot <= barrier if is_down else spot >= barrier) else 0.0
        if sigma <= 0.0:
            levels = spot * np.exp((r - q) * np.asarray(times))
            hit = levels <= barrier if is_down else levels >= barrier
            return float(hit.any())
        rng = np.random.default_rng(seed)
        grid = np.asarray((0.0, *times), dtype=float)
        dt = np.diff(grid)
        z = rng.standard_normal((n_paths, len(dt)))
        log_increments = (
            (r - q - 0.5 * sigma * sigma) * dt[None, :]
            + sigma * np.sqrt(dt)[None, :] * z
        )
        levels = spot * np.exp(np.cumsum(log_increments, axis=1))
        hit = levels <= barrier if is_down else levels >= barrier
        return float(hit.any(axis=1).mean())
