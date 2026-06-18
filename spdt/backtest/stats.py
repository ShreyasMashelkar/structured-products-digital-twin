"""Aggregate backtest outcomes into the distributions a desk actually looks at (L7).

Autocall frequency, coupon income, capital-loss rate and — the one that matters — the tail.
Autocallables "look great until they don't": most issuances autocall early for a tidy coupon,
and the strategy's character lives in the worst few percent, so the tail metric is reported
explicitly alongside the headline averages.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from spdt.backtest.issuance import IssuanceOutcome


@dataclass(frozen=True)
class BacktestStats:
    """Summary distribution over many rolled issuances."""

    n_issuances: int
    autocall_rate: float
    mean_total_return: float  # mean total payoff as a fraction of notional
    loss_rate: float  # fraction of issuances with a capital loss
    mean_capital_loss: float  # mean loss among loss-making issuances (0 if none)
    worst_5pct_return: float  # 5th-percentile total return (the tail)


def aggregate(outcomes: list[IssuanceOutcome], notional: float = 100.0) -> BacktestStats:
    """Reduce per-issuance outcomes to a :class:`BacktestStats` summary."""
    if not outcomes:
        raise ValueError("no issuances to aggregate")
    returns = np.array([o.total_payoff / notional for o in outcomes])
    losses = np.array([o.capital_loss for o in outcomes])
    loss_mask = losses > 0.0
    return BacktestStats(
        n_issuances=len(outcomes),
        autocall_rate=float(np.mean([o.autocalled for o in outcomes])),
        mean_total_return=float(returns.mean()),
        loss_rate=float(loss_mask.mean()),
        mean_capital_loss=float(losses[loss_mask].mean()) if loss_mask.any() else 0.0,
        worst_5pct_return=float(np.percentile(returns, 5)),
    )
