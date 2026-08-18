"""Three-way Greek cross-check: adjoint vs finite difference vs closed form (L8).

A Greek computed one way and checked against itself is not validated. This module computes the
same sensitivity by methods that fail *differently*, so agreement is real evidence:

* **AAD (adjoint)** — exact derivative of the simulated payoff. Blind to the Dirac terms at a
  digital barrier, because differentiating an indicator gives zero almost everywhere.
* **Bump (central finite difference)** — sees barrier effects, but carries ``O(h²)`` truncation
  bias and, under common random numbers, MC noise amplified by ``1/2h``.
* **Closed form** — exact where it exists (vanillas), and therefore the anchor: any
  disagreement on a vanilla is a bug in the estimator, not a modelling subtlety.

The interpretation is asymmetric and deliberately so. On a **vanilla** all three must agree to
tight tolerance — this is a correctness test with a known answer. On the **autocallable** there
is no closed form and AAD and bump legitimately disagree by the barrier's Dirac contribution;
the useful output is the *size* of that gap, which measures how much of the note's delta lives
in the discontinuity rather than in the smooth part. A large gap is information about the
product, not necessarily an error.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from math import exp, log, sqrt

import numpy as np
from scipy.stats import norm

from spdt.greeks.aad import autocallable_aad_greeks, bs_vanilla_aad, call_aad_greeks
from spdt.greeks.bump import GreekSet, bump_greeks
from spdt.greeks.pathwise import pathwise_vanilla
from spdt.pricing.models.bs import BlackScholes
from spdt.products.catalog import Autocallable
from spdt.products.primitives import EuropeanOption


@dataclass(frozen=True)
class MethodAgreement:
    """Agreement between two estimators of one Greek."""

    greek: str
    method_a: str
    value_a: float
    method_b: str
    value_b: float

    @property
    def abs_diff(self) -> float:
        return abs(self.value_a - self.value_b)

    @property
    def rel_diff(self) -> float:
        """Relative difference against the larger magnitude; ``nan`` when both are ~zero."""
        scale = max(abs(self.value_a), abs(self.value_b))
        return self.abs_diff / scale if scale > 1e-12 else float("nan")

    def agrees(self, *, rel_tol: float, abs_tol: float = 1e-9) -> bool:
        return self.abs_diff <= abs_tol or self.rel_diff <= rel_tol


@dataclass(frozen=True)
class GreekComparison:
    """All pairwise agreements for one instrument, plus the verdict."""

    instrument: str
    has_closed_form: bool
    agreements: tuple[MethodAgreement, ...]
    values: dict[str, dict[str, float]]  # method -> greek -> value

    def worst(self, greek: str | None = None) -> MethodAgreement | None:
        pool = [a for a in self.agreements if greek is None or a.greek == greek]
        return max(pool, key=lambda a: (a.rel_diff if a.rel_diff == a.rel_diff else 0.0),
                   default=None)

    def all_agree(self, *, rel_tol: float, abs_tol: float = 1e-9) -> bool:
        return all(a.agrees(rel_tol=rel_tol, abs_tol=abs_tol) for a in self.agreements)


def _bs_closed_form(model: BlackScholes, strike: float, expiry: float) -> dict[str, float]:
    """Analytic Black-Scholes call delta/vega/rho — the anchor the estimators are judged against."""
    s, k, r, q, sig, t = model.spot, strike, model.r, model.q, model.sigma, expiry
    d1 = (log(s / k) + (r - q + 0.5 * sig * sig) * t) / (sig * sqrt(t))
    d2 = d1 - sig * sqrt(t)
    return {
        "delta": exp(-q * t) * norm.cdf(d1),
        "vega": s * exp(-q * t) * norm.pdf(d1) * sqrt(t),
        "rho": k * t * exp(-r * t) * norm.cdf(d2),
    }


def cross_check_vanilla(
    model: BlackScholes, strike: float, expiry: float, *, n_paths: int = 200_000, seed: int = 0
) -> GreekComparison:
    """Delta and vega of a European call by closed form, AAD, pathwise and CRN bump.

    Every method has a known-correct target here, so this is the leg of the pack that can
    actually fail in a way that means "the code is wrong" rather than "the product is hard".
    """
    analytic = _bs_closed_form(model, strike, expiry)
    aad_analytic_price, aad_analytic = bs_vanilla_aad(
        model.spot, strike, expiry, model.r, model.q, model.sigma, True
    )
    aad_mc = call_aad_greeks(model, strike, expiry, n_paths=n_paths, seed=seed)
    pathwise = pathwise_vanilla(model, strike, expiry, n_paths=n_paths, seed=seed)
    call = EuropeanOption(strike=strike, expiry=expiry, is_call=True)
    bumped = bump_greeks(call, model, n_paths=n_paths, seed=seed)

    values = {
        "closed_form": analytic,
        "aad_analytic": {"delta": aad_analytic["delta"], "vega": aad_analytic["vega"]},
        "aad_mc": aad_mc,
        "pathwise": dict(pathwise) if isinstance(pathwise, dict) else {},
        "bump": {"delta": bumped.delta, "vega": bumped.vega, "rho": bumped.rho},
    }

    agreements: list[MethodAgreement] = []
    for greek in ("delta", "vega"):
        target = analytic[greek]
        for method in ("aad_analytic", "aad_mc", "pathwise", "bump"):
            got = values[method].get(greek)
            if got is None:
                continue
            agreements.append(
                MethodAgreement(greek, "closed_form", target, method, float(got))
            )
    return GreekComparison("european_call", True, tuple(agreements), values)


def cross_check_autocallable(
    note: Autocallable, model: BlackScholes, *, n_paths: int = 200_000, seed: int = 0
) -> GreekComparison:
    """Delta and vega of the autocallable by AAD and by CRN bump.

    There is no closed form, so neither method is the truth. The gap between them is the
    quantity of interest: AAD sees only the smooth part of the payoff, the bump sees the
    barrier's jump as well, so ``bump − AAD`` estimates the Dirac contribution the adjoint
    structurally cannot capture. The note must be struck, or its delta is identically zero by
    scale invariance and the comparison is vacuous.
    """
    if note.initial_fixing is None:
        raise ValueError("cross-check needs a struck note (set initial_fixing)")

    aad = autocallable_aad_greeks(note, model, n_paths=n_paths, seed=seed)
    bumped = bump_greeks(note, model, n_paths=n_paths, seed=seed)
    values = {
        "aad": {"delta": aad["delta"], "vega": aad["vega"]},
        "bump": {"delta": bumped.delta, "vega": bumped.vega,
                 "gamma": bumped.gamma, "rho": bumped.rho},
    }
    agreements = tuple(
        MethodAgreement(g, "aad", float(aad[g]), "bump", float(getattr(bumped, g)))
        for g in ("delta", "vega")
    )
    return GreekComparison("autocallable", False, agreements, values)


def bump_convergence(
    note: Autocallable, model: BlackScholes, *,
    bumps: tuple[float, ...] = (2e-2, 1e-2, 5e-3, 2e-3, 1e-3),
    n_paths: int = 200_000, seed: int = 0,
) -> dict[float, float]:
    """Bump delta as a function of bump size — the diagnostic that says whether it converged.

    A finite-difference Greek is only meaningful if it is stable in ``h``. Too large and
    truncation bias dominates; too small and MC noise, scaled by ``1/2h``, blows up. If delta
    wanders monotonically across this range, the reported number is an artefact of the step
    size rather than a property of the note — and on a barrier product that is the normal case,
    not the exception, which is precisely why this is reported rather than assumed away.
    """
    return {
        h: bump_greeks(note, model, n_paths=n_paths, seed=seed, rel_spot_bump=h).delta
        for h in bumps
    }


def cross_check_greeks(
    note: Autocallable, model: BlackScholes, *, n_paths: int = 200_000, seed: int = 0
) -> dict[str, GreekComparison | dict[float, float]]:
    """Run the whole cross-check: vanilla anchor, exotic comparison, and bump stability."""
    strike = note.initial_fixing or model.spot
    expiry = max(note.observation_times)
    return {
        "vanilla": cross_check_vanilla(model, strike, expiry, n_paths=n_paths, seed=seed),
        "autocallable": cross_check_autocallable(note, model, n_paths=n_paths, seed=seed),
        "bump_convergence": bump_convergence(note, model, n_paths=n_paths, seed=seed),
    }
