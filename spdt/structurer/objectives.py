"""Structuring objectives: what the client wants, in solvable terms (L6).

A client specifies all-but-one of a note's economics ("I want 12% — what knock-in does that
imply?"). An :class:`Objective` captures the free parameter to solve for and the PV it must
hit, decoupling *what* to solve from *how* (the Brent solver) and *which* product (the
proposer).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SolveFor(str, Enum):
    """The single free parameter a price-to-par solve will move."""

    COUPON = "coupon"
    KNOCK_IN = "knock_in"
    PARTICIPATION = "participation"


@dataclass(frozen=True)
class Objective:
    """Solve ``solve_for`` so the structure prices to ``target_pv`` (default par)."""

    solve_for: SolveFor
    target_pv: float = 100.0
    bracket: tuple[float, float] = (0.0, 1.0)
