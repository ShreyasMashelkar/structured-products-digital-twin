"""Documentation engine: term sheets and scenario tables from the term-sheet object (L13).

The whole point: the document is rendered from the **same** :class:`TermSheet` the pricer
consumes, and the scenario-at-maturity table is produced by replaying the **same**
``Autocallable.cashflows`` the pricer uses. So the paperwork can never disagree with the
price — a real source of operational risk that this design eliminates by construction.

Output is Markdown (cheap, diff-able, renders anywhere); HTML/PDF are a Jinja template swap.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from jinja2 import Template

from spdt.products.catalog import Autocallable
from spdt.products.graph import PathSet
from spdt.products.termsheet import TermSheet


@dataclass(frozen=True)
class PricingSummary:
    """The indicative valuation shown on the term sheet."""

    pv: float
    std_error: float = 0.0
    currency: str = "INR"


@dataclass(frozen=True)
class ScenarioRow:
    """One row of the scenario-at-maturity table (held to maturity, not autocalled)."""

    terminal_level: float  # final underlying as a fraction of the initial fixing
    ki_breached: bool
    payment_pct: float  # maturity payment (coupon + principal) as a % of notional


def maturity_scenarios(
    note: Autocallable, terminal_levels: tuple[float, ...]
) -> list[ScenarioRow]:
    """Maturity payment vs final level, computed by replaying the product's own cashflows.

    Paths are constructed to *survive* to maturity (intermediate observations sit between the
    coupon barrier and the autocall level, so coupons pay but the note does not redeem early),
    with the terminal observation swept across ``terminal_levels``. This reuses
    :meth:`Autocallable.cashflows`, guaranteeing the table matches the pricer.
    """
    ref = note.initial_fixing if note.initial_fixing is not None else 100.0
    times = np.array((0.0, *note.monitoring_times()))
    n = len(terminal_levels)
    m = times.size

    spots = np.full((n, m), ref)
    if m > 2:  # intermediate observations: survive (no autocall) but qualify for coupons
        survival = 0.5 * (note.coupon_barrier + note.autocall_level)
        spots[:, 1 : m - 1] = ref * survival
    spots[:, m - 1] = ref * np.asarray(terminal_levels)

    cashflows = note.cashflows(PathSet(times=times, spots=spots))
    maturity_time = note.observation_times[-1]
    maturity_pay = np.zeros(n)
    for cf in cashflows:
        if abs(cf.time - maturity_time) <= 1e-12:
            maturity_pay += cf.amount

    return [
        ScenarioRow(
            terminal_level=level,
            # Match the pricer's convention exactly (cashflows breach on spot ≤ KI·S₀), so the
            # table's flag can never disagree with the payment it shows.
            ki_breached=level <= note.knock_in,
            payment_pct=100.0 * maturity_pay[i] / note.notional,
        )
        for i, level in enumerate(terminal_levels)
    ]


_TERM_SHEET = Template(
    """# Indicative Term Sheet — {{ ts.product_type | replace("_", " ") | title }}

| Field | Value |
|---|---|
| Underlying(s) | {{ ts.underlyings | join(", ") }} |
| Notional | {{ ts.notional }} |
| Maturity (years) | {{ ts.maturity | round(4) }} |
| Observation dates (years) | {{ ts.observation_times | map("round", 4) | join(", ") }} |
| Autocall level | {{ ts.params.get("autocall_level", "—") }} |
| Coupon (per observation) | {{ ts.params.get("coupon_rate", "—") }} |
| Coupon barrier | {{ ts.params.get("coupon_barrier", "—") }} |
| Knock-in | {{ ts.params.get("knock_in", "—") }} |
| Memory coupon | {{ ts.params.get("memory", False) }} |
{% if summary %}
## Indicative valuation

Model PV: **{{ "%.4f" | format(summary.pv) }} {{ summary.currency }}**\
{% if summary.std_error %} (± {{ "%.4f" | format(summary.std_error) }} MC s.e.){% endif %}
{% endif %}
{% if scenarios %}
## Scenario at maturity (if held to maturity, not autocalled)

| Final level (% of initial) | Knock-in breached | Maturity payment (% of notional) |
|---|---|---|
{% for r in scenarios %}| {{ "%.0f" | format(r.terminal_level * 100) }}% \
| {{ "Yes" if r.ki_breached else "No" }} \
| {{ "%.2f" | format(r.payment_pct) }}% |
{% endfor %}
{% endif %}"""
)


def render_term_sheet(
    ts: TermSheet,
    summary: PricingSummary | None = None,
    scenarios: list[ScenarioRow] | None = None,
) -> str:
    """Render an indicative term sheet (Markdown) from the term-sheet object."""
    return _TERM_SHEET.render(ts=ts, summary=summary, scenarios=scenarios)
