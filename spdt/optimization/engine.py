"""Hedge Optimization Engine: find optimal instrument weights via SLSQP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.optimize import minimize

from spdt.greeks.bump import GreekSet
from spdt.optimization.constraints import HedgeConstraints
from spdt.optimization.costs import linear_transaction_cost, quadratic_market_impact
from spdt.replication.portfolio import HedgeInstrument, ReplicationPortfolio


@dataclass(frozen=True)
class OptimalHedge:
    """The result of a hedge optimization run."""
    portfolio: ReplicationPortfolio
    residual_risk: GreekSet
    estimated_cost: float
    success: bool
    message: str


class HedgeOptimizationEngine:
    """Optimizes the portfolio of hedges to minimize cost and impact subject to risk limits."""

    def __init__(
        self,
        w_txn: float = 1.0,
        w_impact: float = 1.0,
        w_risk: float = 1.0
    ):
        self.w_txn = w_txn
        self.w_impact = w_impact
        self.w_risk = w_risk

    def optimize(
        self,
        target_greeks: GreekSet,
        available_instruments: Sequence[HedgeInstrument],
        instrument_greeks: Sequence[GreekSet],
        constraints: HedgeConstraints,
    ) -> OptimalHedge:
        """Find the optimal weights for available instruments to neutralize target_greeks."""

        n = len(available_instruments)
        if n == 0:
            within_limits = (
                abs(target_greeks.delta) <= constraints.delta_limit
                and abs(target_greeks.gamma) <= constraints.gamma_limit
                and abs(target_greeks.vega) <= constraints.vega_limit
            )
            return OptimalHedge(
                portfolio=ReplicationPortfolio(()),
                residual_risk=target_greeks,
                estimated_cost=0.0,
                success=within_limits,
                message="No instruments available; risk within limits" if within_limits else
                        "No instruments available; risk limits breached",
            )

        if len(instrument_greeks) != n:
            raise ValueError("Must provide greeks for each available instrument.")

        # Convert greeks to arrays for fast computation
        # Row 0: delta, Row 1: gamma, Row 2: vega
        A = np.zeros((3, n))
        for i, g in enumerate(instrument_greeks):
            A[0, i] = g.delta
            A[1, i] = g.gamma
            A[2, i] = g.vega

        b = np.array([target_greeks.delta, target_greeks.gamma, target_greeks.vega])

        def objective(w: np.ndarray) -> float:
            # 1. Residual Risk Penalty
            # residual = target_greeks + hedge_greeks (since we want hedge to offset target)
            # wait, if target is the risk we *have*, the hedge needs to *offset* it.
            # So residual = target + A @ w
            residual = b + A @ w
            risk_penalty = np.sum(residual**2)

            # 2. Transaction Costs
            txn_cost = sum(linear_transaction_cost(wi) for wi in w)

            # 3. Market Impact
            impact = sum(quadratic_market_impact(wi) for wi in w)

            return self.w_risk * risk_penalty + self.w_txn * txn_cost + self.w_impact * impact

        def residual(w: np.ndarray) -> np.ndarray:
            return b + A @ w

        scipy_constraints = [
            {"type": "ineq", "fun": lambda w: constraints.max_total_notional - np.sum(np.abs(w))},
            {"type": "ineq", "fun": lambda w: constraints.delta_limit - abs(residual(w)[0])},
            {"type": "ineq", "fun": lambda w: constraints.gamma_limit - abs(residual(w)[1])},
            {"type": "ineq", "fun": lambda w: constraints.vega_limit - abs(residual(w)[2])},
        ]

        # Bounds
        if constraints.allow_short_selling:
            bnds = [(-constraints.max_notional_per_instrument, constraints.max_notional_per_instrument) for _ in range(n)]
        else:
            bnds = [(0.0, constraints.max_notional_per_instrument) for _ in range(n)]

        # Initial guess (zeros)
        w0 = np.zeros(n)

        # Optimization
        res = minimize(
            objective,
            w0,
            method='SLSQP',
            bounds=bnds,
            constraints=scipy_constraints,
            options={'ftol': 1e-9, 'disp': False}
        )

        optimal_weights = res.x

        # Construct optimized portfolio
        optimized_instruments = []
        for i, instr in enumerate(available_instruments):
            if abs(optimal_weights[i]) > 1e-6:
                optimized_instruments.append(
                    HedgeInstrument(
                        instrument=instr.instrument,
                        weight=float(optimal_weights[i]),
                        instrument_type=instr.instrument_type,
                        purpose="optimized_hedge"
                    )
                )

        # Calculate true residual
        final_greeks = b + A @ optimal_weights
        residual_risk = GreekSet(
            delta=float(final_greeks[0]),
            gamma=float(final_greeks[1]),
            vega=float(final_greeks[2]),
            rho=target_greeks.rho  # We didn't optimize rho in this basic implementation
        )

        execution_cost = sum(
            linear_transaction_cost(wi) + quadratic_market_impact(wi)
            for wi in optimal_weights
        )
        return OptimalHedge(
            portfolio=ReplicationPortfolio(tuple(optimized_instruments)),
            residual_risk=residual_risk,
            estimated_cost=float(execution_cost),
            success=res.success,
            message=res.message,
        )
