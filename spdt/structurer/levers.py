"""Manufacturing a coupon the market will not hand over (L6).

The price-to-par solve answers *"what coupon does this structure afford?"*. Clients ask the
other question: *"I want 15%."* When the solve returns 11%, the desk does not say no — it says
**which term would you like to change?** Every extra point of coupon is bought by selling
something: more downside, a shorter path to being called away, a longer horizon, or the
dispersion of a basket. That negotiation *is* structuring, and this module is it.

The mechanics are a nested root-find. The inner solve is the ordinary price-to-par: fix every
term, find the coupon. The outer solve moves one term until the coupon the inner solve returns
equals the client's target::

    outer:  find lever L  such that  coupon(L) = target
    inner:  find coupon c such that  PV(c, L)  = par − fee

Each lever is swept **independently**, so the report reads as a menu of single concessions
("70% → 62% barrier", "or 1y → 1.6y"), not one blended compromise the client cannot reason
about. Combining them is a second conversation, and one the client should drive.

Monotonicity, which is what makes the outer Brent legitimate, differs by lever and is asserted
per-lever below rather than assumed globally — a lever whose direction is wrong would silently
return a root on the wrong side.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from scipy.optimize import brentq

from spdt.structurer.proposer import Proposal


class CouponSolver(Protocol):
    """Prices a proposal and solves its coupon to par. Injected so this module stays pure."""

    def __call__(self, proposal: Proposal) -> float | None: ...


@dataclass(frozen=True)
class Lever:
    """One term the client could concede, and what conceding it buys."""

    key: str
    label: str  # client-facing name of the concession
    gives_up: str  # what the client actually loses by moving it
    current: float
    required: float | None  # value that reaches the target; None if the lever cannot get there
    reachable: bool
    limit: float  # the bound tested — how far the lever was allowed to move
    coupon_at_limit: float | None  # best coupon this lever alone can produce

    @property
    def move(self) -> float | None:
        return None if self.required is None else self.required - self.current


@dataclass(frozen=True)
class ManufactureReport:
    """What the market affords, what the client wanted, and the menu of ways to close the gap."""

    target_coupon: float  # annualised, as the client stated it
    natural_coupon: float | None  # annualised, on the brief's own terms
    levers: tuple[Lever, ...]

    @property
    def shortfall(self) -> float | None:
        if self.natural_coupon is None:
            return None
        return self.target_coupon - self.natural_coupon

    @property
    def already_met(self) -> bool:
        return self.shortfall is not None and self.shortfall <= 1e-9

    @property
    def reachable_levers(self) -> tuple[Lever, ...]:
        return tuple(v for v in self.levers if v.reachable)

    def summary(self) -> str:
        """One honest sentence for the term sheet or the call."""
        if self.natural_coupon is None:
            return "The structure could not be solved on these terms."
        if self.already_met:
            return (
                f"The market affords {self.natural_coupon:.2%} on these terms, at or above the "
                f"{self.target_coupon:.2%} asked — no concession needed."
            )
        options = self.reachable_levers
        if not options:
            return (
                f"The market affords {self.natural_coupon:.2%}; {self.target_coupon:.2%} is not "
                f"reachable by moving any single term within its tested bound. It needs a "
                f"combination of concessions, or a lower target."
            )
        return (
            f"The market affords {self.natural_coupon:.2%} on these terms. "
            f"{self.target_coupon:.2%} is reachable by conceding one of "
            f"{len(options)} terms — cheapest first in the table."
        )


# Per-lever configuration. ``bound`` is how far the lever may travel; every one of these moves
# UP to raise the coupon, and the first version of this table had all three pointing down —
# on the plausible-sounding but wrong intuition that "deeper barrier" means "more risk sold".
# It does not: a knock-in at 60% is *further* from spot and therefore SAFER for the investor,
# so it makes the note more valuable and the affordable coupon smaller. Every lever here sells
# risk by moving toward spot, or by keeping the client invested longer.
#
# The direction is re-verified numerically on every call (see ``solve_lever``) rather than
# trusted from this table, which is what caught the original error: the guard reported
# "cannot reach" instead of root-solving into a concession that would have sold the client
# the opposite of what the label promised.
_LEVERS: dict[str, dict] = {
    "knock_in": {
        "label": "Move the barrier closer to today's level",
        "gives_up": "protection — capital is at risk on a smaller fall",
        "bound": 0.95,
    },
    "coupon_barrier": {
        "label": "Raise the level coupons require",
        "gives_up": "frequency of payment — coupons stop on a smaller fall",
        "bound": 0.95,
    },
    "autocall_level": {
        "label": "Stay invested longer before early redemption",
        "gives_up": "the early exit — capital stays at risk through more observations",
        "bound": 1.20,
    },
}


def _annualise(per_period: float, obs_per_year: int) -> float:
    return per_period * obs_per_year


def solve_lever(
    proposal: Proposal,
    solve_coupon: CouponSolver,
    key: str,
    target_annual_coupon: float,
    obs_per_year: int,
    *,
    limit: float | None = None,
    xtol: float = 1e-4,
) -> Lever:
    """Move one term until the solved coupon reaches ``target_annual_coupon``.

    Returns an unreachable :class:`Lever` — never raises — when the target sits beyond the
    lever's bound. "This term cannot get you there" is a real answer to give a client, and a
    more useful one than an exception.
    """
    cfg = _LEVERS[key]
    current = float(proposal.params[key])
    bound = float(limit if limit is not None else cfg["bound"])

    def coupon_at(value: float) -> float | None:
        moved = replace(proposal, params={**proposal.params, key: value})
        per_period = solve_coupon(moved)
        return None if per_period is None else _annualise(per_period, obs_per_year)

    base = coupon_at(current)
    at_limit = coupon_at(bound)
    if base is None or at_limit is None:
        return Lever(key, cfg["label"], cfg["gives_up"], current, None, False, bound, at_limit)

    # Verify the lever actually moves the coupon the way the table claims. A lever that does
    # not (or moves it backwards) is reported as unreachable rather than root-solved, because
    # Brent on a non-monotone or flat function returns a number that means nothing.
    if at_limit <= base + 1e-9:
        return Lever(key, cfg["label"], cfg["gives_up"], current, None, False, bound, at_limit)

    if target_annual_coupon > at_limit:
        return Lever(key, cfg["label"], cfg["gives_up"], current, None, False, bound, at_limit)
    if target_annual_coupon <= base:
        return Lever(key, cfg["label"], cfg["gives_up"], current, current, True, bound, at_limit)

    lo, hi = (current, bound) if bound > current else (bound, current)
    try:
        root = float(
            brentq(lambda v: (coupon_at(v) or 0.0) - target_annual_coupon, lo, hi, xtol=xtol)
        )
    except (ValueError, RuntimeError):
        return Lever(key, cfg["label"], cfg["gives_up"], current, None, False, bound, at_limit)
    return Lever(key, cfg["label"], cfg["gives_up"], current, root, True, bound, at_limit)


def manufacture(
    proposal: Proposal,
    solve_coupon: CouponSolver,
    target_annual_coupon: float,
    obs_per_year: int,
    *,
    keys: tuple[str, ...] = ("knock_in", "coupon_barrier", "autocall_level"),
) -> ManufactureReport:
    """Report what the brief's own terms afford, and the single concessions that close the gap.

    Levers absent from the proposal (a capital-protected note has no knock-in) are skipped, so
    this can be called on any income structure without the caller filtering first.
    """
    natural_per_period = solve_coupon(proposal)
    natural = (
        None if natural_per_period is None else _annualise(natural_per_period, obs_per_year)
    )

    levers: list[Lever] = []
    if natural is not None and target_annual_coupon > natural:
        for key in keys:
            if key in proposal.params:
                levers.append(
                    solve_lever(proposal, solve_coupon, key, target_annual_coupon, obs_per_year)
                )
    # Cheapest concession first: the smallest move from where the client already is, measured
    # relative to the distance that lever was allowed to travel — so an 8-point barrier move is
    # compared fairly against a 5-point autocall move.
    levers.sort(
        key=lambda v: (
            not v.reachable,
            abs(v.move or 0.0) / max(abs(v.limit - v.current), 1e-9),
        )
    )
    return ManufactureReport(target_annual_coupon, natural, tuple(levers))
