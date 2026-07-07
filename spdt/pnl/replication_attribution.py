"""Replication-based P&L attribution (Phase 5).

Instead of explaining the P&L of an exotic product using its own Greeks, an institutional
desk explains its P&L using the Greeks of the hedge portfolio it actually holds.
The "unexplained" P&L thus becomes the true economic slippage (tracking error) between
the theoretical exotic model and the executable vanilla hedges.
"""

from __future__ import annotations

from dataclasses import dataclass

from spdt.decomposition.components import RiskComponent
from spdt.greeks.bump import bump_greeks
from spdt.pnl.attribution import age
from spdt.pricing.engine import price_mc
from spdt.pricing.models import BlackScholes
from spdt.replication.portfolio import ReplicationPortfolio


@dataclass(frozen=True)
class ReplicationPnLExplain:
    """P&L attribution using the static hedge portfolio."""

    total_component_pnl: float    # Actual PV change of the component
    hedge_delta_pnl: float        # Explained by the hedge portfolio's Delta
    hedge_gamma_pnl: float        # Explained by the hedge portfolio's Gamma
    hedge_vega_pnl: float         # Explained by the hedge portfolio's Vega
    hedge_theta_pnl: float        # Explained by the hedge portfolio's Theta
    hedge_rho_pnl: float          # Explained by the hedge portfolio's Rho
    total_hedge_explained: float  # Sum of hedge explained PnL
    residual_slippage: float      # Component PnL - Hedge Explained PnL


def attribute_via_replication(
    component: RiskComponent,
    portfolio: ReplicationPortfolio,
    model0: BlackScholes,
    model1: BlackScholes,
    dt: float,
    *,
    n_paths: int = 200_000,
    seed: int = 0,
    rel_spot_bump: float = 1e-2,
    vol_bump: float = 1e-2,
    rate_bump: float = 1e-4,
) -> ReplicationPnLExplain:
    """Attribute the D-1 to D P&L of a RiskComponent using its hedge portfolio's Greeks."""

    primitive = component.as_product(model0.spot)
    if primitive is None:
        raise ValueError("Cannot attribute P&L for a component without a primitive representation.")

    def comp_pv(m: BlackScholes, aged: bool = False) -> float:
        prod = age(primitive, dt) if aged else primitive
        return price_mc(prod, m, n_paths=n_paths, seed=seed).price

    # 1. Component Total PnL (Actual full reval)
    comp_pv0 = comp_pv(model0, aged=False)
    comp_pv1 = comp_pv(model1, aged=True)
    total_pnl = comp_pv1 - comp_pv0

    # 2. Calculate Hedge Portfolio Greeks and Theta
    hedge_delta = 0.0
    hedge_gamma = 0.0
    hedge_vega = 0.0
    hedge_rho = 0.0
    hedge_theta = 0.0

    for instr in portfolio.instruments:
        # Get Delta, Gamma, Vega, Rho
        greeks = bump_greeks(
            instr.instrument,
            model0,
            n_paths=n_paths,
            seed=seed,
            rel_spot_bump=rel_spot_bump,
            vol_bump=vol_bump,
            rate_bump=rate_bump,
        )
        weight = instr.weight
        hedge_delta += greeks.delta * weight
        hedge_gamma += greeks.gamma * weight
        hedge_vega += greeks.vega * weight
        hedge_rho += greeks.rho * weight

        # Calculate Theta for this instrument
        p0 = price_mc(instr.instrument, model0, n_paths=n_paths, seed=seed).price
        p_aged = price_mc(age(instr.instrument, dt), model0, n_paths=n_paths, seed=seed).price
        instr_theta = (p_aged - p0) / dt
        hedge_theta += instr_theta * weight

    # 3. Market moves
    d_s = model1.spot - model0.spot
    d_sig = model1.sigma - model0.sigma
    d_r = model1.r - model0.r

    # 4. Explained PnL components
    delta_pnl = hedge_delta * d_s
    gamma_pnl = 0.5 * hedge_gamma * d_s * d_s
    vega_pnl = hedge_vega * d_sig
    rho_pnl = hedge_rho * d_r
    theta_pnl = hedge_theta * dt

    total_explained = delta_pnl + gamma_pnl + vega_pnl + rho_pnl + theta_pnl
    slippage = total_pnl - total_explained

    return ReplicationPnLExplain(
        total_component_pnl=total_pnl,
        hedge_delta_pnl=delta_pnl,
        hedge_gamma_pnl=gamma_pnl,
        hedge_vega_pnl=vega_pnl,
        hedge_theta_pnl=theta_pnl,
        hedge_rho_pnl=rho_pnl,
        total_hedge_explained=total_explained,
        residual_slippage=slippage,
    )
