"""Rolling issuance study: many notes, many regimes, on the paths that actually happened (L8).

The single-note comparison in :mod:`spdt.validation.realized` demonstrates that the machinery
works end to end, and demonstrates nothing else. Three notes that all autocalled at their first
observation is not evidence about pricing accuracy — it is one draw from a distribution, three
times, in a rising market.

This module issues a fresh note every month across the whole available history and evaluates
each on its realised path. That converts the question from "did this note pay out?" — luck —
into "across many issues spanning crashes and rallies, is the coupon the model solved for
systematically too generous or too mean?" — which luck cannot fake at sample size.

**What can and cannot be concluded.** Each note is priced with only data published on or before
its own issue date, so there is no hindsight in the pricing. But the notes overlap: a 1-year
note issued every month shares eleven months of path with its neighbour, so the outcomes are
strongly serially correlated and the effective sample is far smaller than the issue count. A
mean across issues is meaningful; a standard error computed as if the issues were independent
is not, and is deliberately not reported.

**The regime caveat that governs the result.** Indian equity spent most of the last fifteen
years in a bull market. An autocallable is short the downside and long the calm, so a high
autocall rate and a positive average return are what that regime *mechanically* produces — they
are not evidence the pricing was right. The per-regime breakdown matters more than the total,
and the 2008 and 2020 sub-samples matter most of all, because they are the only periods where
the structure's downside was genuinely tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from spdt.products.catalog import Autocallable
from spdt.validation.realized import RealizedComparison, compare_priced_vs_realized

_DAYS_PER_YEAR = 365.0


@dataclass(frozen=True)
class RollingResult:
    """Outcome distribution across a rolling issuance programme."""

    comparisons: tuple[RealizedComparison, ...]
    failures: tuple[tuple[date, str], ...]

    @property
    def n(self) -> int:
        return len(self.comparisons)

    @property
    def autocall_rate(self) -> float:
        return float(np.mean([c.outcome.autocalled for c in self.comparisons]))

    @property
    def knock_in_rate(self) -> float:
        return float(np.mean([c.capital_loss > 0.0 for c in self.comparisons]))

    @property
    def mean_return_pct(self) -> float:
        return float(np.mean([c.total_return_pct for c in self.comparisons]))

    @property
    def worst_return_pct(self) -> float:
        return float(np.min([c.total_return_pct for c in self.comparisons]))

    @property
    def mean_coupon(self) -> float:
        return float(np.mean([c.solved_coupon for c in self.comparisons]))

    @property
    def mean_vol_error(self) -> float:
        """Mean implied minus realised vol — the variance premium the notes sold.

        Persistently positive is the expected result and is the desk's edge. Persistently
        *negative* would mean the model systematically underpriced risk, which is the failure
        this study exists to detect.
        """
        errors = [c.vol_error for c in self.comparisons if np.isfinite(c.vol_error)]
        return float(np.mean(errors)) if errors else float("nan")

    def by_year(self) -> dict[int, dict[str, float]]:
        """Per-issue-year breakdown — where a regime effect would show up."""
        buckets: dict[int, list[RealizedComparison]] = {}
        for c in self.comparisons:
            buckets.setdefault(c.issue_date.year, []).append(c)
        return {
            year: {
                "n": float(len(cs)),
                "autocall_rate": float(np.mean([c.outcome.autocalled for c in cs])),
                "knock_in_rate": float(np.mean([c.capital_loss > 0.0 for c in cs])),
                "mean_return_pct": float(np.mean([c.total_return_pct for c in cs])),
                "mean_coupon": float(np.mean([c.solved_coupon for c in cs])),
            }
            for year, cs in sorted(buckets.items())
        }

    def summary_lines(self) -> list[str]:
        if not self.comparisons:
            return ["no issues completed"]
        return [
            f"issues evaluated : {self.n}  (failed/skipped {len(self.failures)})",
            f"autocall rate    : {self.autocall_rate:.0%}",
            f"knock-in rate    : {self.knock_in_rate:.0%}",
            f"mean coupon      : {self.mean_coupon:.2%} per observation",
            f"mean return      : {self.mean_return_pct:.1f}% of notional (worst {self.worst_return_pct:.1f}%)",
            f"implied − realised vol : {self.mean_vol_error:+.1%}",
        ]


def run_rolling_issuance(
    *,
    start: date,
    end: date,
    tenor: float = 0.5,
    observations_per_year: int = 4,
    step_months: int = 3,
    underlying: str = "NIFTY",
    coupon_barrier: float = 0.80,
    knock_in: float = 0.60,
    autocall_level: float = 1.00,
    memory: bool = True,
    r: float = 0.065,
    q: float = 0.013,
    n_paths: int = 20_000,
    verbose: bool = True,
) -> RollingResult:
    """Issue and evaluate a note every ``step_months`` between ``start`` and ``end``.

    Each issue is priced from its own date's calibrated surface and then walked forward on the
    realised index path. Issues whose surface cannot be built — an unpublished archive day, or a
    date where too few contracts traded to calibrate — are recorded as failures rather than
    silently dropped, because *which* dates fail is itself informative: they cluster in exactly
    the stressed periods the study most wants to measure.

    ``step_months`` defaults to a quarter rather than a month: every issue costs one surface
    calibration plus a realised-path walk, each of which is a set of archive fetches, so a
    monthly cadence over fifteen years is hours of network time for outcomes that overlap almost
    completely anyway.
    """
    n_obs = max(1, round(tenor * observations_per_year))
    observations = tuple(round(tenor * i / n_obs, 6) for i in range(1, n_obs + 1))
    note = Autocallable(
        notional=100.0,
        observation_times=observations,
        coupon_rate=0.02,  # overwritten by the price-to-par solve
        autocall_level=autocall_level,
        coupon_barrier=coupon_barrier,
        knock_in=knock_in,
        memory=memory,
    )

    comparisons: list[RealizedComparison] = []
    failures: list[tuple[date, str]] = []

    issue = start
    while issue <= end:
        try:
            comparisons.append(
                compare_priced_vs_realized(
                    note, issue, underlying=underlying, r=r, q=q, n_paths=n_paths
                )
            )
            if verbose:
                c = comparisons[-1]
                print(
                    f"  {c.issue_date} fix={c.initial_fixing:>9,.0f} vol={c.atm_vol_at_issue:5.1%} "
                    f"cpn={c.solved_coupon:6.2%} {'CALLED' if c.outcome.autocalled else 'held  '} "
                    f"ret={c.total_return_pct:6.1f}%"
                )
        except Exception as exc:  # noqa: BLE001 - a bad date must not sink the programme
            failures.append((issue, f"{type(exc).__name__}: {exc}"))
            if verbose:
                print(f"  {issue} [skip] {type(exc).__name__}")
        issue += timedelta(days=round(step_months * 30.44))

    return RollingResult(tuple(comparisons), tuple(failures))


def main() -> int:
    """Run the study over the span the NSE archive supports and print the distribution."""
    # The note must mature before today, so issuance stops one tenor short of the present.
    tenor = 0.5
    start, end = date(2015, 1, 15), date.today() - timedelta(days=int(tenor * _DAYS_PER_YEAR) + 30)
    print(f"Rolling {tenor:.1f}y quarterly autocallable, {start} → {end}")
    print("(first run downloads and caches NSE archives; later runs are offline)\n")

    result = run_rolling_issuance(start=start, end=end, tenor=tenor)

    print("\n" + "\n".join(result.summary_lines()))
    by_year = result.by_year()
    if by_year:
        print(f"\n{'year':>6} {'n':>3} {'autocall':>9} {'knock-in':>9} {'mean ret':>9} {'coupon':>8}")
        for year, stats in by_year.items():
            print(
                f"{year:>6} {int(stats['n']):>3} {stats['autocall_rate']:>8.0%} "
                f"{stats['knock_in_rate']:>9.0%} {stats['mean_return_pct']:>8.1f}% "
                f"{stats['mean_coupon']:>7.2%}"
            )
    if result.failures:
        print(f"\nskipped {len(result.failures)} issue dates (surface unavailable/uncalibratable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
