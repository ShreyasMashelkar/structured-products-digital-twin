"""Objective → structure proposer & recommender (L6).

Maps a plain-language client brief to candidate structures. This is the "front-office magic":
the desk does not start from a product name — it starts from what the client *wants* (income,
yield enhancement, or capital preservation) and how much downside they can stomach, then picks
the product family that best fits and solves its free parameter to par.

Two entry points:

* :func:`propose_autocallable` — the original single-product proposer (income → Phoenix), kept
  for callers/tests that just want the flagship note.
* :func:`recommend` — ranks every product family for fit against the brief and returns them
  best-first, each with a :class:`Proposal` (how to build and what to solve) and a plain-English
  rationale. This is what the Originate desk uses: recommend the best fit, show the alternatives.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from spdt.products.termsheet import TermSheet
from spdt.structurer.objectives import SolveFor


class ClientObjective(str, Enum):
    """What the client is fundamentally trying to achieve — drives the product choice."""

    INCOME = "income"  # range-bound view, wants a coupon, can take some downside
    YIELD_ENHANCED = "yield_enhanced"  # wants the *highest* coupon, will sell more risk
    PROTECTION = "protection"  # capital preservation first, some upside second


@dataclass(frozen=True)
class ClientBrief:
    """A client's request in their own terms."""

    target_coupon: float  # desired annual coupon, e.g. 0.12
    max_downside: float  # drawdown they can stomach, e.g. 0.30 → knock-in at 70%
    maturity_years: float = 1.0
    observations_per_year: int = 4
    objective: ClientObjective = ClientObjective.INCOME
    prefer_basket: bool = False  # willing to take a multi-name (worst-of) basket for more coupon


# Default 3-name basket for worst-of proposals (mirrors the desk's WO-000 correlation regime).
_DEFAULT_BASKET = ("NIFTY", "BANKNIFTY", "RELIANCE")
_DEFAULT_BASKET_VOL_MULT = (1.0, 1.15, 0.90)
_DEFAULT_BASKET_RHO = 0.60


def _observation_schedule(brief: ClientBrief) -> tuple[float, ...]:
    """Evenly spaced observation dates implied by the brief's maturity and frequency."""
    n_obs = round(brief.maturity_years * brief.observations_per_year)
    if n_obs < 1:
        raise ValueError("brief implies fewer than one observation")
    step = 1.0 / brief.observations_per_year
    return tuple(round((i + 1) * step, 10) for i in range(n_obs))


@dataclass(frozen=True)
class Proposal:
    """A buildable, solvable candidate structure produced from a brief.

    Carries everything the pricer needs to (a) construct the product, (b) solve its single free
    parameter to par, and (c) book it. The free parameter is either the coupon (income notes) or
    the upside participation (capital-protected notes), per ``solve_for``.
    """

    product_type: str  # autocallable | brc | capital_protected | worst_of
    observation_times: tuple[float, ...]
    maturity: float
    params: dict
    solve_for: SolveFor  # COUPON or PARTICIPATION
    free_param_key: str  # which params key the solver writes ("coupon_rate" | "participation")
    bracket: tuple[float, float]  # search range for the free parameter (per-period for coupons)


@dataclass(frozen=True)
class RankedProposal:
    """A :class:`Proposal` with its desk-fit ranking and a plain-English rationale."""

    proposal: Proposal
    label: str
    rationale: str
    fit_score: float  # 0–1; the recommender picks the highest


# ---------------------------------------------------------------------------------------------
# Per-family proposers: brief → Proposal (indicative; the coupon/participation is solved to par)
# ---------------------------------------------------------------------------------------------

def propose_autocallable(brief: ClientBrief, *, notional: float = 100.0) -> TermSheet:
    """Translate a brief into a Phoenix-autocallable term sheet (indicative, single-product)."""
    observation_times = _observation_schedule(brief)
    knock_in = round(1.0 - brief.max_downside, 10)  # 30% down ⇒ KI at 70%
    return TermSheet(
        product_type="autocallable",
        underlyings=("NIFTY",),
        notional=notional,
        observation_times=observation_times,
        params={
            "coupon_rate": brief.target_coupon / brief.observations_per_year,  # per period
            "autocall_level": 1.0,
            "coupon_barrier": knock_in,
            "knock_in": knock_in,
            "memory": True,  # Phoenix
        },
    )


def _autocallable_proposal(brief: ClientBrief) -> Proposal:
    knock_in = round(1.0 - brief.max_downside, 10)
    return Proposal(
        product_type="autocallable",
        observation_times=_observation_schedule(brief),
        maturity=brief.maturity_years,
        params={
            "coupon_rate": brief.target_coupon / brief.observations_per_year,
            "autocall_level": 1.0,
            "coupon_barrier": knock_in,
            "knock_in": knock_in,
            "memory": True,
        },
        solve_for=SolveFor.COUPON,
        free_param_key="coupon_rate",
        bracket=(0.0, 0.06),
    )


def _brc_proposal(brief: ClientBrief) -> Proposal:
    knock_in = round(1.0 - brief.max_downside, 10)
    return Proposal(
        product_type="brc",
        observation_times=_observation_schedule(brief),
        maturity=brief.maturity_years,
        params={
            "coupon_rate": brief.target_coupon / brief.observations_per_year,
            "strike": 1.0,
            "knock_in": knock_in,
        },
        solve_for=SolveFor.COUPON,
        free_param_key="coupon_rate",
        bracket=(0.0, 0.08),
    )


def _capital_protected_proposal(brief: ClientBrief) -> Proposal:
    # Protection scales with how risk-averse the client is: a small downside tolerance ⇒ near-full
    # capital protection; a larger one ⇒ a lower floor that funds more upside participation.
    protection = round(min(1.0, 0.90 + (0.30 - min(brief.max_downside, 0.30))), 4)
    return Proposal(
        product_type="capital_protected",
        observation_times=_observation_schedule(brief),
        maturity=brief.maturity_years,
        params={
            "protection": protection,
            "participation": 1.0,  # indicative; solved to par
            "strike": 1.0,
            "cap": None,
        },
        solve_for=SolveFor.PARTICIPATION,
        free_param_key="participation",
        bracket=(0.0, 5.0),
    )


def _worst_of_proposal(brief: ClientBrief) -> Proposal:
    knock_in = round(1.0 - brief.max_downside, 10)
    return Proposal(
        product_type="worst_of",
        observation_times=_observation_schedule(brief),
        maturity=brief.maturity_years,
        params={
            "coupon_rate": brief.target_coupon / brief.observations_per_year,
            "autocall_level": 1.0,
            "coupon_barrier": knock_in,
            "knock_in": knock_in,
            "memory": True,
            "underlyings": list(_DEFAULT_BASKET),
            "vol_mult": list(_DEFAULT_BASKET_VOL_MULT),
            "correlation": _DEFAULT_BASKET_RHO,
        },
        solve_for=SolveFor.COUPON,
        free_param_key="coupon_rate",
        bracket=(0.0, 0.10),
    )


# ---------------------------------------------------------------------------------------------
# Recommender: score every family for fit against the brief, return them best-first
# ---------------------------------------------------------------------------------------------

def recommend(brief: ClientBrief) -> list[RankedProposal]:
    """Rank all product families by how well they fit the brief (best first).

    The scoring mirrors a structurer's heuristics: match the product to the client's *objective*
    first, then tilt by how much downside they'll sell (more tolerance favours yield products;
    less favours protection) and whether they'll take a basket (favours worst-of).
    """
    o = brief.objective
    dd = brief.max_downside
    ki = 1.0 - dd

    # Base fit by objective.
    base = {
        ClientObjective.INCOME: {
            "autocallable": 0.90, "brc": 0.72, "worst_of": 0.60, "capital_protected": 0.20},
        ClientObjective.YIELD_ENHANCED: {
            "worst_of": 0.92, "brc": 0.76, "autocallable": 0.70, "capital_protected": 0.12},
        ClientObjective.PROTECTION: {
            "capital_protected": 0.95, "autocallable": 0.45, "brc": 0.30, "worst_of": 0.18},
    }[o]

    # Tilts (small, explainable): downside tolerance and basket appetite.
    tilt = {
        "autocallable": (0.30 - dd) * 0.20,       # modest tolerance suits the KI-protected coupon
        "brc": (dd - 0.30) * 0.40,                # more downside sold ⇒ richer fixed coupon
        "worst_of": (dd - 0.30) * 0.40 + (0.35 if brief.prefer_basket else -0.05),
        "capital_protected": (0.30 - dd) * 0.40,  # the more protection they want, the better the fit
    }

    rationale = {
        "autocallable": (
            f"Income with a range-bound view and {dd:.0%} downside tolerance → Phoenix autocallable: "
            f"a conditional (memory) coupon while the index holds above the {ki:.0%} knock-in, with "
            f"early redemption at par if it rallies."
        ),
        "brc": (
            f"Income, willing to be assigned the underlying → barrier reverse convertible: a fixed "
            f"coupon paid unconditionally, principal at risk only if the {ki:.0%} barrier is breached."
        ),
        "worst_of": (
            f"{'You will take a basket — ' if brief.prefer_basket else ''}worst-of autocallable on "
            f"{', '.join(_DEFAULT_BASKET)}: selling the basket's dispersion (ρ≈{_DEFAULT_BASKET_RHO:.2f}) "
            f"funds a higher coupon than any single name can."
        ),
        "capital_protected": (
            "Capital preservation first → capital-protected note: a principal floor plus participation "
            "in the upside (the coupon is given up to buy the protection)."
        ),
    }

    builders = {
        "autocallable": _autocallable_proposal,
        "brc": _brc_proposal,
        "worst_of": _worst_of_proposal,
        "capital_protected": _capital_protected_proposal,
    }
    labels = {
        "autocallable": "Phoenix autocallable",
        "brc": "Barrier reverse convertible",
        "worst_of": "Worst-of autocallable",
        "capital_protected": "Capital-protected note",
    }

    ranked = [
        RankedProposal(
            proposal=builders[pt](brief),
            label=labels[pt],
            rationale=rationale[pt],
            fit_score=round(max(0.0, min(1.0, base[pt] + tilt[pt])), 4),
        )
        for pt in builders
    ]
    ranked.sort(key=lambda r: r.fit_score, reverse=True)
    return ranked
