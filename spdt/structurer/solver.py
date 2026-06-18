"""Price-to-par solver (L6).

A note is "fair" when its model PV (the issuer's hedging cost) equals the issue price minus
the issuer's margin/fee. The structurer fixes every parameter the client specified and solves
the one free parameter so that ``PV(param) = target``. With a single free parameter this is a
1-D root find; Brent is used because the relevant PVs are monotone in their free parameter
(PV rises with coupon, falls as the knock-in barrier rises), so the problem is well-posed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from scipy.optimize import brentq


def par_target(par: float = 100.0, fee: float = 0.0) -> float:
    """Issue price net of the issuer's fee — the PV the structure must solve to."""
    return par - fee


@dataclass(frozen=True)
class SolveResult:
    """Outcome of a price-to-par solve."""

    param: float
    achieved_pv: float
    target: float


def solve_to_par(
    pv_of_param: Callable[[float], float],
    target: float,
    bracket: tuple[float, float],
    *,
    xtol: float = 1e-8,
    max_iter: int = 100,
) -> SolveResult:
    """Solve ``pv_of_param(x) = target`` for ``x`` in ``bracket`` (Brent).

    Raises ``ValueError`` if the target PV is not bracketed — i.e. unreachable for any
    parameter in the range (the structure simply cannot hit that level).
    """
    lo, hi = bracket
    f_lo, f_hi = pv_of_param(lo) - target, pv_of_param(hi) - target
    if f_lo * f_hi > 0:
        raise ValueError(
            f"target PV {target} not bracketed by parameter range {bracket} "
            f"(PV spans [{f_lo + target}, {f_hi + target}])"
        )
    root = brentq(lambda x: pv_of_param(x) - target, lo, hi, xtol=xtol, maxiter=max_iter)
    return SolveResult(param=root, achieved_pv=pv_of_param(root), target=target)
