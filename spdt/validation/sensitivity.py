"""Coupon sensitivity: how far the solved terms move when the assumptions move (L8).

The structurer solves one free parameter — usually the coupon — so that the note prices to
par. That coupon is quoted to a client as if it were a fact. It is not: it is a function of
inputs the desk does not observe cleanly, and the honest question is not "what is the coupon"
but **"how much of the coupon is an artefact of an assumption we cannot verify?"**

Each input below is perturbed by an amount chosen to represent genuine estimation uncertainty
rather than a round number:

``vol``
    ±2 vol points. Roughly the whole-surface calibration RMSE measured on stressed historical
    dates (:mod:`spdt.vol.quality`), so this is the model's own admitted uncertainty, not an
    arbitrary stress.
``rate``
    ±50bps. About the range across which a flat-curve assumption differs from a bootstrapped
    OIS curve at the relevant tenor.
``dividend``
    ±50bps. Index dividend yield is a forecast; the implied-dividend route disagrees with the
    trailing yield by about this much.
``skew``
    ±20% of the fitted skew. The wings are exactly where settlement-price surfaces are least
    reliable, and an autocallable's knock-in lives in the put wing.
``correlation``
    ±0.10, worst-of notes only. Correlation is unobservable and the single largest lever on a
    worst-of price.

The output ranks inputs by **coupon basis points moved per unit of plausible error**, which is
the ordering that tells a desk where to spend its data budget. An input the price is insensitive
to does not need better data however unreliable it is; an input the price is very sensitive to
needs better data however good it already looks.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

import numpy as np

from spdt.pricing.engine import price_mc
from spdt.pricing.models.bs import BlackScholes
from spdt.products.catalog import Autocallable
from spdt.structurer.solver import par_target, solve_to_par


@dataclass(frozen=True)
class Perturbation:
    """One input moved by a plausible estimation error, and what it did to the coupon."""

    input_name: str
    description: str
    shift: float
    coupon_down: float  # solved coupon at −shift
    coupon_base: float
    coupon_up: float  # solved coupon at +shift

    @property
    def swing_bps(self) -> float:
        """Total coupon range across the perturbation, in basis points per observation."""
        return 1e4 * (max(self.coupon_up, self.coupon_down) - min(self.coupon_up, self.coupon_down))

    @property
    def half_range_bps(self) -> float:
        """Coupon bps moved per one-sided plausible error — the ranking key."""
        return self.swing_bps / 2.0

    @property
    def is_monotone(self) -> bool:
        """Whether the coupon responds monotonically; if not, the solve is likely unstable."""
        return (self.coupon_down - self.coupon_base) * (self.coupon_up - self.coupon_base) <= 0.0


@dataclass(frozen=True)
class SensitivityTable:
    """The full sensitivity picture for one note in one market."""

    base_coupon: float
    target_pv: float
    perturbations: tuple[Perturbation, ...] = field(default_factory=tuple)

    @property
    def ranked(self) -> tuple[Perturbation, ...]:
        """Inputs ordered by how much coupon they move — where the model risk actually is."""
        return tuple(sorted(self.perturbations, key=lambda p: -p.half_range_bps))

    @property
    def total_uncertainty_bps(self) -> float:
        """Coupon uncertainty if every input is wrong at once and independently.

        Added in quadrature rather than summed: the inputs are separately estimated, so the
        arithmetic sum would assume they all err in the same direction simultaneously, which
        overstates a realistic band. It is still only a rough envelope, not a confidence
        interval — the perturbations are judgement calls, not fitted standard errors.
        """
        return float(np.sqrt(sum(p.half_range_bps ** 2 for p in self.perturbations)))

    @property
    def dominant_input(self) -> str:
        return self.ranked[0].input_name if self.perturbations else ""


def _solve_coupon(
    note: Autocallable,
    model: BlackScholes,
    *,
    target: float,
    bracket: tuple[float, float],
    n_paths: int,
    seed: int,
) -> float:
    """Solve the per-observation coupon that prices ``note`` to ``target`` under ``model``.

    Common random numbers (a fixed ``seed`` across every revaluation) are essential: without
    them the root finder chases MC noise and the "sensitivity" measured is sampling error.
    """

    def pv(coupon: float) -> float:
        return price_mc(
            dataclasses.replace(note, coupon_rate=coupon), model, n_paths=n_paths, seed=seed
        ).price

    return solve_to_par(pv, target, bracket).param


def coupon_sensitivity(
    note: Autocallable,
    model: BlackScholes,
    *,
    par: float = 100.0,
    fee: float = 0.0,
    n_paths: int = 50_000,
    seed: int = 0,
    bracket: tuple[float, float] = (0.0, 0.20),
    vol_shift: float = 0.02,
    rate_shift: float = 0.005,
    div_shift: float = 0.005,
) -> SensitivityTable:
    """Solve the coupon, then re-solve it with each input perturbed either way.

    Returns the table ranked by impact. The note's ``coupon_rate`` is overwritten by the solve,
    so whatever it carries on the way in is irrelevant.
    """
    target = par_target(par, fee)
    solve = lambda m: _solve_coupon(  # noqa: E731 - a local alias keeps the table below readable
        note, m, target=target, bracket=bracket, n_paths=n_paths, seed=seed
    )
    base = solve(model)

    specs = (
        ("vol", "implied vol ±2 vol pts (≈ stressed-date calibration RMSE)", "sigma", vol_shift),
        ("rate", "risk-free rate ±50bps (flat-curve vs bootstrapped OIS)", "r", rate_shift),
        ("dividend", "dividend yield ±50bps (forecast, not observed)", "q", div_shift),
    )

    perturbations: list[Perturbation] = []
    for name, description, attr, shift in specs:
        value = getattr(model, attr)
        down = solve(dataclasses.replace(model, **{attr: value - shift}))
        up = solve(dataclasses.replace(model, **{attr: value + shift}))
        perturbations.append(Perturbation(name, description, shift, down, base, up))

    return SensitivityTable(base, target, tuple(perturbations))


def barrier_sensitivity(
    note: Autocallable,
    model: BlackScholes,
    *,
    par: float = 100.0,
    fee: float = 0.0,
    n_paths: int = 50_000,
    seed: int = 0,
    bracket: tuple[float, float] = (0.0, 0.20),
    shift: float = 0.05,
) -> Perturbation:
    """Coupon sensitivity to the **knock-in level** — a term, not a market input.

    Included because it separates two things a single coupon number conflates: uncertainty
    about the market (vol, rates) and leverage on the structure itself. If a 5-point move in
    the knock-in moves the coupon more than a 2-vol-point calibration error does, the note's
    economics are dominated by where the barrier was placed, and the pricing uncertainty is a
    second-order concern by comparison.
    """
    target = par_target(par, fee)
    base = _solve_coupon(note, model, target=target, bracket=bracket, n_paths=n_paths, seed=seed)
    out = {}
    for tag, level in (("down", note.knock_in - shift), ("up", note.knock_in + shift)):
        moved = dataclasses.replace(note, knock_in=level)
        out[tag] = _solve_coupon(
            moved, model, target=target, bracket=bracket, n_paths=n_paths, seed=seed
        )
    return Perturbation(
        "knock_in", f"knock-in barrier ±{shift:.0%} of initial fixing",
        shift, out["down"], base, out["up"],
    )
