"""Broadie–Glasserman–Kou discrete-barrier continuity correction (L4).

A discretely monitored barrier is breached *less* often than a continuously monitored one —
the discrete monitor misses excursions that begin and end between observation dates. BGK
(1997) showed the leading-order fix is a simple shift of the barrier:

    H_adj = H · exp( ± β · σ · √Δt ),     β = −ζ(½)/√(2π) ≈ 0.5826

where Δt is the monitoring spacing and the sign moves the barrier **toward the spot** (so the
coarser monitor breaches as readily as a continuous one): ``+`` for a down barrier (raise it),
``−`` for an up barrier (lower it). Monitoring a coarse discrete scheme against ``H_adj`` then
approximates the continuous-monitoring price to O(√Δt) — far better than the raw O(√Δt) bias.
"""

from __future__ import annotations

from math import exp, sqrt

BGK_BETA = 0.5826414278686763  # −ζ(1/2)/√(2π)


def continuity_corrected_barrier(
    barrier: float, sigma: float, monitoring_dt: float, *, direction: str
) -> float:
    """Barrier to monitor in a discrete scheme so it approximates continuous monitoring.

    ``direction`` is ``"down"`` (barrier below spot) or ``"up"`` (barrier above spot);
    ``monitoring_dt`` is the spacing between observation dates in years.
    """
    if direction not in ("down", "up"):
        raise ValueError("direction must be 'down' or 'up'")
    shift = BGK_BETA * sigma * sqrt(monitoring_dt)
    return barrier * exp(shift if direction == "down" else -shift)
