"""Semi-static vanilla-strip replication for discretely monitored down barriers.

Barrier claims cannot in general be replaced by one "mirror" vanilla.  Instead, this strategy
projects the barrier payoff onto a liquid strip of European puts under the supplied model.  The
projection is deterministic (fixed seed), honours the component's actual monitoring schedule and
produces an executable static portfolio.  Its remaining path-dependent error is intentionally left
for the monitoring and residual-Greek layers.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from spdt.decomposition.components import BarrierComponent, RiskComponent
from spdt.products.primitives import EuropeanOption
from spdt.replication.portfolio import HedgeInstrument
from spdt.replication.strategies.base import AbstractReplicationStrategy


class BarrierReplicationStrategy(AbstractReplicationStrategy):
    """Regress a down-barrier payoff onto a diversified vanilla-put strip."""

    def __init__(
        self,
        n_paths: int = 30_000,
        n_strikes: int = 19,
        seed: int = 1729,
        max_gross_multiple: float = 5.0,
    ):
        if n_paths < 1_000 or n_strikes < 7:
            raise ValueError("Barrier replication requires at least 1,000 paths and 7 strikes")
        self.n_paths = n_paths
        self.n_strikes = n_strikes
        self.seed = seed
        self.max_gross_multiple = max_gross_multiple

    def _down_in_strip(
        self, component: BarrierComponent, model: Any
    ) -> tuple[HedgeInstrument, ...]:
        fixing = component.fixing(model.spot)
        strike = component.strike * fixing
        barrier = component.barrier * fixing
        if not 0.0 < barrier < strike:
            raise ValueError("Down-in put replication requires 0 < barrier < strike")

        monitoring = tuple(sorted(set(component.monitoring or (component.expiry,))))
        times = np.array((0.0, *sorted(set(monitoring) | {component.expiry})), dtype=float)
        rng = np.random.default_rng(self.seed)
        normals = rng.standard_normal((self.n_paths, len(times) - 1))
        spots = model.simulate(times, normals)
        monitor_cols = [int(np.searchsorted(times, t)) for t in monitoring]
        terminal_col = int(np.searchsorted(times, component.expiry))
        terminal = spots[:, terminal_col]
        hit = (spots[:, monitor_cols] <= barrier).any(axis=1)

        quantity = component.notional * component.direction / fixing
        target = quantity * np.maximum(strike - terminal, 0.0) * hit

        broad = np.linspace(max(0.50 * strike, 1e-8), 1.05 * strike, self.n_strikes)
        around_barrier = barrier * np.array((0.90, 0.95, 0.975, 1.0, 1.025, 1.05, 1.10))
        # Snap to a listed-style strike grid (NIFTY options: 50-point grid at current levels;
        # unit-scale tests use a one-point grid). This prevents fictitious 15,096.96 strikes.
        strike_step = 50.0 if fixing >= 1_000.0 else 1.0
        strikes = np.unique(
            np.round(np.concatenate((broad, around_barrier, [strike])) / strike_step)
            * strike_step
        )
        basis = np.maximum(strikes[None, :] - terminal[:, None], 0.0)

        # Increase ridge until the strip respects a gross-underlying-equivalent inventory limit.
        # This sacrifices a little fit to avoid the thousands-per-100 oscillating portfolios that
        # an unconstrained least-squares projection produces.
        scale = max(float(np.mean(basis * basis)), 1.0)
        ridge = 1e-8 * scale
        rhs = basis.T @ target
        gross_limit = self.max_gross_multiple * component.notional
        for _ in range(14):
            lhs = basis.T @ basis + ridge * np.eye(len(strikes))
            weights = np.linalg.solve(lhs, rhs)
            if float(np.abs(weights).sum() * fixing) <= gross_limit:
                break
            ridge *= 10.0

        cutoff = max(abs(quantity) * 1e-5, 1e-10)
        return tuple(
            HedgeInstrument(
                instrument=EuropeanOption(float(k), component.expiry, is_call=False),
                weight=float(w),
                instrument_type="vanilla_put",
                purpose="barrier_static_strip",
            )
            for k, w in zip(strikes, weights)
            if abs(w) > cutoff
        )

    def replicate(
        self, component: RiskComponent, model: Any, surface: Any = None
    ) -> tuple[HedgeInstrument, ...]:
        if not isinstance(component, BarrierComponent):
            raise TypeError("Expected BarrierComponent")
        if component.is_call:
            raise NotImplementedError("Up/down barrier calls require a dedicated replication basis")

        down_in = self._down_in_strip(component, model)
        if component.knock_in:
            return down_in

        fixing = component.fixing(model.spot)
        base = HedgeInstrument(
            instrument=EuropeanOption(component.strike * fixing, component.expiry, is_call=False),
            weight=component.notional * component.direction / fixing,
            instrument_type="vanilla_put",
            purpose="barrier_base",
        )
        # In/out parity: down-out put = vanilla put - down-in put.
        offset = tuple(
            HedgeInstrument(i.instrument, -i.weight, i.instrument_type, "barrier_static_strip")
            for i in down_in
        )
        return (base, *offset)
