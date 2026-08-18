"""Priced-versus-realised: what the note was sold to do, against what it did (L8).

This is the only leg of the validation pack that leaves the model's own world. Every other
check — calibration RMSE, Greek agreement, coupon sensitivity — is internal: it asks whether
the model is consistent with itself and with its inputs. None of them can detect a model that
is coherent, well-fitted, beautifully differentiated and *wrong about the world*.

The test:

1. Price the note on ``issue_date`` using **only** data published on or before that date, and
   solve the coupon that makes it fair. This is a genuine point-in-time exercise: the surface,
   spot and curve all come from that evening's bhavcopy.
2. Walk the **actual realised path** — the index levels that subsequently happened — through
   the note's terms, and record what an investor received.
3. Compare.

**What this can and cannot show.** One note on one path is a single draw from a distribution,
so a gap between priced and realised is not by itself evidence of mispricing — an autocallable
that knocked in during COVID was not necessarily wrongly priced, it was unlucky. The comparison
becomes evidence only in aggregate, across issue dates and regimes, where a systematic bias in
one direction cannot be explained by luck. The report therefore quotes the distribution, not
the individual outcome, and the reader should treat small samples accordingly.

**Why exchange data, not a vendor series.** The realised path is read from NSE F&O bhavcopy
files on the observation dates themselves — the same source the pricing snapshot came from.
A third-party daily series would be more convenient and would silently introduce a second
definition of "the index level", which is precisely the kind of inconsistency this exercise
exists to detect.

**The survivorship caveat.** On a single index there is no survivorship bias: NIFTY existed
throughout and its history is not conditioned on success. That is *not* true of a multi-name
worst-of, which needs point-in-time index membership — using today's constituents would
backfill winners and inflate autocall frequency. This module handles the single-name case
only, and refuses rather than silently doing the wrong thing for baskets.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from spdt.backtest.issuance import IssuanceOutcome, _evaluate_on_path
from spdt.data.ingest.nse_historical import bhavcopy_source_for
from spdt.pricing.engine import price_mc
from spdt.pricing.models.bs import BlackScholes
from spdt.products.catalog import Autocallable
from spdt.structurer.solver import par_target, solve_to_par

_DAYS_PER_YEAR = 365.0


@dataclass(frozen=True)
class RealizedComparison:
    """One note, priced point-in-time and then evaluated on the path that happened."""

    issue_date: date
    label: str
    initial_fixing: float
    notional: float
    solved_coupon: float
    priced_pv: float
    atm_vol_at_issue: float
    observation_dates: tuple[date, ...]
    observed_spots: tuple[float, ...]
    outcome: IssuanceOutcome
    realised_vol: float

    @property
    def total_return_pct(self) -> float:
        """Undiscounted total payoff as a percentage of notional."""
        return 100.0 * self.outcome.total_payoff / self.notional

    @property
    def coupons_received(self) -> float:
        return self.outcome.coupon_income

    @property
    def capital_loss(self) -> float:
        return self.outcome.capital_loss

    @property
    def vol_error(self) -> float:
        """Implied minus subsequently-realised vol — the variance premium the note sold.

        Positive means the note was priced off a higher vol than actually materialised, i.e.
        the issuer collected a premium that the path did not justify. Persistently positive
        across regimes is the expected result (that premium is the business); persistently
        *negative* would mean the desk systematically underpriced risk.
        """
        return self.atm_vol_at_issue - self.realised_vol


def _spot_on(as_of: date, underlying: str) -> tuple[date, float]:
    """Index level on ``as_of`` from the exchange file, with the date actually served.

    Returns the served date too, because NSE does not publish on holidays and an observation
    date that silently slid by three days would misstate the note's schedule.
    """
    raw = bhavcopy_source_for(as_of).fetch(as_of, underlying)
    return raw.date, raw.spot


def realised_path(
    issue_date: date, observation_times: tuple[float, ...], underlying: str = "NIFTY"
) -> tuple[tuple[date, ...], np.ndarray]:
    """Index levels on the note's observation dates, read from the exchange archive.

    ``observation_times`` are year fractions from issue; each is converted to a calendar date
    and served from the nearest published session on or before it.
    """
    dates: list[date] = []
    spots: list[float] = []
    for t in observation_times:
        target = issue_date + timedelta(days=round(t * _DAYS_PER_YEAR))
        served, spot = _spot_on(target, underlying)
        dates.append(served)
        spots.append(spot)
    return tuple(dates), np.array(spots, dtype=float)


def realised_vol_over_life(
    issue_date: date,
    tenor: float,
    initial_spot: float,
    underlying: str = "NIFTY",
    *,
    samples_per_year: int = 12,
) -> float:
    """Annualised realised vol over the note's life, sampled monthly.

    Deliberately *not* computed from the note's own observation dates. A six-month quarterly
    note has two observations, so a vol estimated from them has one degree of freedom and is
    noise. Monthly sampling costs a handful of extra (cached) archive reads and produces an
    estimate that can actually be compared against the implied vol the note was priced on —
    which is the whole point of reporting it.

    Still a coarse estimate: monthly close-to-close understates the vol of a path that whipsawed
    within each month, which matters most in exactly the stressed regimes of interest here.
    """
    n = max(2, int(round(tenor * samples_per_year)))
    spots = [initial_spot]
    for i in range(1, n + 1):
        target = issue_date + timedelta(days=round(i * tenor / n * _DAYS_PER_YEAR))
        try:
            spots.append(_spot_on(target, underlying)[1])
        except Exception:  # noqa: BLE001 - a missing archive day shortens the sample, not fatal
            continue
    if len(spots) < 3:
        return float("nan")
    logret = np.diff(np.log(np.array(spots, dtype=float)))
    return float(np.std(logret, ddof=1) * np.sqrt(len(logret) / tenor))


def price_at_issue(
    note: Autocallable,
    spot: float,
    atm_vol: float,
    *,
    r: float,
    q: float,
    par: float = 100.0,
    fee: float = 0.0,
    n_paths: int = 50_000,
    seed: int = 0,
    bracket: tuple[float, float] = (0.0, 0.25),
) -> tuple[float, float]:
    """Solve the fair coupon at issue and return ``(coupon, achieved_pv)``.

    Uses only ``spot`` and ``atm_vol`` as observed on the issue date — no later information.
    """
    struck = dataclasses.replace(note, initial_fixing=spot)
    model = BlackScholes(spot=spot, r=r, q=q, sigma=atm_vol)

    def pv(coupon: float) -> float:
        return price_mc(
            dataclasses.replace(struck, coupon_rate=coupon), model, n_paths=n_paths, seed=seed
        ).price

    result = solve_to_par(pv, par_target(par, fee), bracket)
    return result.param, result.achieved_pv


def compare_priced_vs_realized(
    note: Autocallable,
    issue_date: date,
    *,
    underlying: str = "NIFTY",
    label: str = "",
    r: float = 0.065,
    q: float = 0.013,
    atm_vol: float | None = None,
    par: float = 100.0,
    fee: float = 0.0,
    n_paths: int = 50_000,
    seed: int = 0,
) -> RealizedComparison:
    """Price ``note`` point-in-time at ``issue_date``, then evaluate it on the realised path.

    ``atm_vol`` may be supplied to reuse an already-calibrated surface; when omitted the
    surface is calibrated from the issue date's own chain.
    """
    from spdt.validation.asof import build_asof_market

    tenor = max(note.observation_times)
    if atm_vol is None:
        market = build_asof_market(issue_date, underlying)
        issue_served, spot = market.as_of, market.spot
        atm_vol = market.atm_vol(tenor)
    else:
        issue_served, spot = _spot_on(issue_date, underlying)

    coupon, priced_pv = price_at_issue(
        note, spot, atm_vol, r=r, q=q, par=par, fee=fee, n_paths=n_paths, seed=seed
    )

    obs_dates, obs_spots = realised_path(issue_served, note.observation_times, underlying)
    struck = dataclasses.replace(note, initial_fixing=spot, coupon_rate=coupon)
    outcome = _evaluate_on_path(struck, obs_spots)

    realised = realised_vol_over_life(issue_served, tenor, spot, underlying)

    return RealizedComparison(
        issue_date=issue_served,
        label=label or issue_served.isoformat(),
        initial_fixing=spot,
        notional=note.notional,
        solved_coupon=coupon,
        priced_pv=priced_pv,
        atm_vol_at_issue=float(atm_vol),
        observation_dates=obs_dates,
        observed_spots=tuple(float(s) for s in obs_spots),
        outcome=outcome,
        realised_vol=realised,
    )


def summarise(comparisons: list[RealizedComparison]) -> dict[str, float]:
    """Aggregate across issues — the level at which the comparison carries information.

    A single note's outcome is one draw; these are the statistics that separate a systematic
    pricing bias from a run of bad paths.
    """
    if not comparisons:
        return {}
    returns = np.array([c.total_return_pct for c in comparisons])
    vol_errors = np.array([c.vol_error for c in comparisons])
    finite_vol_errors = vol_errors[np.isfinite(vol_errors)]
    return {
        "n_issues": float(len(comparisons)),
        "autocall_rate": float(np.mean([c.outcome.autocalled for c in comparisons])),
        "knock_in_rate": float(np.mean([c.capital_loss > 0.0 for c in comparisons])),
        "mean_return_pct": float(np.mean(returns)),
        "worst_return_pct": float(np.min(returns)),
        "best_return_pct": float(np.max(returns)),
        "mean_coupon": float(np.mean([c.solved_coupon for c in comparisons])),
        "mean_implied_minus_realised_vol": (
            float(finite_vol_errors.mean()) if finite_vol_errors.size else float("nan")
        ),
    }
