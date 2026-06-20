"""Forward-starting smile from the surface (L2).

A forward-starting option (cliquet, forward-start) depends on the smile of ``S_{T2}/S_{T1}``,
not the spot smile. The calendar-consistent *forward variance* between two tenors is read off
the total-variance surface by differencing:

    w_fwd(k) = w(k, T2) − w(k, T1),   σ_fwd(k) = √( w_fwd(k) / (T2 − T1) )

with ``w(k, T) = σ(k, T)²·T`` the total variance (non-decreasing in T ⟺ no calendar arb).

This is the forward variance the *surface today* implies. The important desk fact: **local vol
reprices today's surface exactly but flattens the realised forward smile** — under LV the smile
of ``S_{T2}/S_{T1}`` decays toward flat, whereas stochastic / local-stochastic vol keep it. That
gap is precisely what makes forward-smile-sensitive exotics (cliquets, forward-starts,
autocallables) carry an LV−LSV model reserve (see :mod:`spdt.modelrisk`).
"""

from __future__ import annotations

from typing import Callable

# σ(k, T): implied vol at log-moneyness k and tenor T (e.g. ``VolSurface.implied_vol_kt``).
IvKT = Callable[[float, float], float]


def forward_total_variance(iv_kt: IvKT, k: float, t1: float, t2: float) -> float:
    """Forward total variance ``w(k,T2) − w(k,T1)`` (non-negative iff calendar-arbitrage-free)."""
    if t2 <= t1:
        raise ValueError("require t2 > t1")
    w1 = iv_kt(k, t1) ** 2 * t1
    w2 = iv_kt(k, t2) ** 2 * t2
    return w2 - w1


def forward_implied_vol(iv_kt: IvKT, k: float, t1: float, t2: float) -> float:
    """Forward implied vol over ``(T1, T2]`` at log-moneyness ``k`` — ``√(w_fwd/(T2−T1))``."""
    w_fwd = max(forward_total_variance(iv_kt, k, t1, t2), 0.0)
    return (w_fwd / (t2 - t1)) ** 0.5


def forward_atm_vol(iv_kt: IvKT, t1: float, t2: float) -> float:
    """Forward at-the-money vol over ``(T1, T2]``."""
    return forward_implied_vol(iv_kt, 0.0, t1, t2)


def forward_smile(iv_kt: IvKT, t1: float, t2: float, ks: list[float]) -> list[tuple[float, float]]:
    """The forward smile ``(k, σ_fwd(k))`` over ``(T1, T2]`` across log-moneyness ``ks``."""
    return [(k, forward_implied_vol(iv_kt, k, t1, t2)) for k in ks]
