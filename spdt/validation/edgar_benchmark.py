"""Benchmark the model against issuers' own disclosed valuations (L8).

Every other leg of the validation pack is internal. This one asks the only question that can
falsify the model from outside: **priced against the same terms, does it land where the bank
that actually sold the note said it landed?**

The comparison, precisely:

    model_pv           our risk-neutral PV of the filed terms, in points of par
    estimated_value    the issuer's disclosed initial estimated value, in points of par
    gap = model_pv − estimated_value

``gap`` is *not* expected to be zero on any single note, and a run that produced zeros would be
evidence of a bug rather than of accuracy — the two numbers come from different vol surfaces,
different funding curves and different dividend forecasts. What carries information is the
gap's **distribution**: its centre is a systematic bias (usually funding or dividends, and
correctable), and its dispersion is the honest width of the model's disagreement with the
street. A gap that drifts with tenor or differs between single-name and basket notes localises
*where* the model breaks down, which is the useful output.

**The limitation that governs everything here.** A note was priced on its pricing date, but the
free CBOE feed serves only the current chain — there is no way to ask it for last April's
surface. So the model prices filed terms on a *later* surface. The mismatch is recorded in
``surface_staleness_days`` and gated by ``max_staleness_days``; beyond a few days the comparison
measures how much the market moved as much as it measures the model, and reporting it as a
model result would be dishonest. Removing this limitation needs a paid historical option
dataset, and that — not more modelling — is the binding constraint on this leg.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from math import exp

from scipy.optimize import brentq

from spdt.data.ingest.edgar import NoteFiling
from spdt.pricing.engine import price_mc, price_worst_of, price_worst_of_lv
from spdt.pricing.models.bs import BlackScholes
from spdt.products.catalog import WorstOfAutocallable
from spdt.products.graph import Discounter

# Beyond this the surface is from a materially different market and the gap stops being a
# statement about the model.
DEFAULT_MAX_STALENESS_DAYS = 5


@dataclass(frozen=True)
class BenchmarkResult:
    """One filed note priced by the model and compared with the issuer's disclosed value."""

    filing: NoteFiling
    model_pv: float  # points of par
    estimated_value_pct: float
    atm_vol: float
    surface_staleness_days: int
    underlying: str

    @property
    def gap(self) -> float:
        """Model PV minus the issuer's disclosed estimated value, in points of par."""
        return self.model_pv - self.estimated_value_pct

    @property
    def gap_vs_offering(self) -> float:
        """Model PV minus the offering price — what a naive comparison would have reported.

        Kept alongside the real gap because the naive number is the one that looks flattering
        and is wrong: matching 100 means the model has absorbed the dealer's fee into its
        risk-neutral value.
        """
        return self.model_pv - self.filing.offering_price

    @property
    def is_trustworthy(self) -> bool:
        return self.surface_staleness_days <= DEFAULT_MAX_STALENESS_DAYS


def funding_discounter(r: float, funding_spread: float) -> Discounter:
    """Two-curve discounting: hedge on OIS, the note's bond leg on the issuer's funding curve.

    A structured note is the issuer's **funded debt**. Its principal and coupons are the bank's
    own liability and must be discounted at the bank's borrowing rate, not at the risk-free
    rate; only the embedded optionality — which is hedged in the market — belongs on OIS.
    Discounting everything at OIS overvalues the note by roughly ``spread × duration``, which on
    a three-year note at 150bps is about 4.4 points of par. That is the same order as a typical
    disclosed fee load, so the error is easy to mistake for the dealer's margin.
    """
    return Discounter(
        ois=lambda t: exp(-r * t),
        funding=lambda t: exp(-(r + funding_spread) * t),
    )


def price_filed_note(
    filing: NoteFiling,
    *,
    spot: float,
    atm_vol: float,
    r: float,
    q: float,
    funding_spread: float = 0.0,
    underlying: str = "",
    as_of: date | None = None,
    n_paths: int = 100_000,
    seed: int = 0,
) -> BenchmarkResult:
    """Price ``filing``'s terms under Black-Scholes and compare with its disclosed value.

    The note is struck at ``spot`` so its barriers are live levels rather than scale-invariant
    fractions. Prices in points of par, which is the unit the disclosed estimated value is
    quoted in once converted by :attr:`NoteFiling.estimated_value_pct`.

    ``funding_spread`` (continuously compounded, over ``r``) discounts the note's bond leg on
    the issuer's curve. It defaults to zero — single-curve — so the caller must opt in to the
    more correct treatment rather than have a funding assumption applied silently.
    """
    if not filing.is_benchmarkable:
        raise ValueError("filing lacks the fixed terms or disclosed value needed to benchmark")

    note = filing.to_autocallable(initial_fixing=spot)
    model = BlackScholes(spot=spot, r=r, q=q, sigma=atm_vol)
    discount = funding_discounter(r, funding_spread) if funding_spread else None
    pv = price_mc(note, model, n_paths=n_paths, seed=seed, discount=discount).price

    as_of = as_of or date.today()
    staleness = (as_of - filing.pricing_date).days if filing.pricing_date else 10**6

    return BenchmarkResult(
        filing=filing,
        model_pv=float(pv),
        estimated_value_pct=float(filing.estimated_value_pct or 0.0),
        atm_vol=atm_vol,
        surface_staleness_days=staleness,
        underlying=underlying or (filing.underlyings[0] if filing.underlyings else ""),
    )


def implied_funding_spread(
    filing: NoteFiling,
    *,
    spot: float,
    atm_vol: float,
    r: float,
    q: float,
    n_paths: int = 100_000,
    seed: int = 0,
    bracket: tuple[float, float] = (-0.02, 0.15),
) -> float | None:
    """The funding spread at which the model reproduces the issuer's disclosed value.

    This inverts the benchmark into a quantity that can be checked against the outside world.
    Rather than asking "how far off are we", it asks "**what would the issuer's funding cost
    have to be** for our model to agree with them?" — and unlike the gap itself, the answer has
    an independent reality check: senior unsecured bank funding at these tenors is roughly
    60–200bps, and the bank's own bond and CDS curves are public.

    So the reading is:

    * an implied spread inside that range means the model and the issuer differ by an amount
      fully explained by funding, which is the *expected* result and a pass;
    * an implied spread of 500bps means the residual is not funding — something else is wrong,
      most likely vol or dividends;
    * a *negative* implied spread means the model already values the note below the issuer's own
      estimate, which no funding assumption can repair.

    Returns ``None`` when the disclosed value is unreachable anywhere in ``bracket`` — reported
    rather than clamped, because a clamped boundary value would masquerade as a fit.
    """
    target = filing.estimated_value_pct
    if target is None:
        return None

    def gap(spread: float) -> float:
        return (
            price_filed_note(
                filing, spot=spot, atm_vol=atm_vol, r=r, q=q, funding_spread=spread,
                n_paths=n_paths, seed=seed,
            ).model_pv
            - target
        )

    lo, hi = bracket
    try:
        if gap(lo) * gap(hi) > 0:
            return None  # not bracketed: no funding spread reconciles the two
        return float(brentq(gap, lo, hi, xtol=1e-6, maxiter=100))
    except (ValueError, RuntimeError):
        return None


def implied_vol_from_note(
    filing: NoteFiling,
    *,
    spot: float,
    r: float,
    q: float,
    funding_spread: float,
    n_paths: int = 100_000,
    seed: int = 0,
    bracket: tuple[float, float] = (0.05, 2.0),
) -> float | None:
    """The volatility at which the model reproduces the issuer's disclosed value.

    **This is the identifying restriction the benchmark actually needs.** The gap between a
    model value and a disclosed value has at least two free parameters — the volatility used and
    the issuer's funding spread — and one equation cannot pin down two unknowns. Solving for
    funding while guessing vol (or vice versa) does not measure anything; it just relabels the
    error, which is why :func:`implied_funding_spread` returns implausible spreads when the vol
    input is wrong.

    Volatility is the parameter to invert for, because it is the one with an *independent
    observable*: the listed option market quotes it directly. So the check becomes a genuine
    falsification test —

        note-implied vol  vs  listed ATM vol for the same underlying and tenor

    — with funding held at a value taken from the issuer's own bond curve rather than fitted.
    Agreement means the model, the note and the option market are mutually consistent.
    Disagreement is informative in a way the raw gap is not: a note-implied vol well above the
    listed surface is the skew the flat-vol pricing is missing, since an autocallable's
    knock-in lives in the put wing where the real surface is far higher than ATM.
    """
    target = filing.estimated_value_pct
    if target is None:
        return None

    def gap(vol: float) -> float:
        return (
            price_filed_note(
                filing, spot=spot, atm_vol=vol, r=r, q=q, funding_spread=funding_spread,
                n_paths=n_paths, seed=seed,
            ).model_pv
            - target
        )

    lo, hi = bracket
    try:
        if gap(lo) * gap(hi) > 0:
            return None
        return float(brentq(gap, lo, hi, xtol=1e-6, maxiter=100))
    except (ValueError, RuntimeError):
        return None


def equicorrelation(n: int, rho: float) -> np.ndarray:
    """``n×n`` correlation matrix with every off-diagonal equal to ``rho``.

    A single parameter rather than a full matrix because that is what the data can support: one
    note gives one equation, so at most one correlation number is identifiable from it. Fitting
    a full pairwise matrix to a single price would be fitting noise. The matrix stays positive
    semi-definite for ``rho ≥ −1/(n−1)``, which the caller's bracket respects.
    """
    return np.full((n, n), rho) + np.eye(n) * (1.0 - rho)


def price_worst_of_filing(
    filing: NoteFiling,
    *,
    vols: dict[str, float],
    rho: float,
    r: float,
    q: float,
    funding_spread: float = 0.0,
    n_paths: int = 60_000,
    seed: int = 0,
    local_vols: dict[str, object] | None = None,
    steps_per_year: int = 52,
) -> float:
    """PV of a filed worst-of note at inception, in points of par.

    Priced **at inception**: each underlying starts at its own recorded starting value and the
    note is struck there. That is the state the issuer's disclosed estimated value describes.
    Pricing it at today's spots against the original strikes would value a *seasoned* note,
    which is a different instrument and not comparable to the disclosed figure.
    """
    starts = dict(filing.starting_values)
    names = [t for t in starts if t in vols]
    if len(names) < 2:
        raise ValueError(f"need at least two underlyings with vols; have {names}")

    spots = np.array([starts[t] for t in names], dtype=float)
    sigma = np.array([vols[t] for t in names], dtype=float)
    corr = equicorrelation(len(names), rho)

    note = WorstOfAutocallable(
        notional=100.0,
        observation_times=filing.observation_times(),
        coupon_rate=(filing.coupon_per_period or 0.0) / filing.denomination,
        autocall_level=filing.call_level or 1.0,
        coupon_barrier=filing.coupon_barrier or 0.8,
        knock_in=filing.knock_in or 0.6,
        memory=filing.memory,
        underlyings=tuple(names),
        initial_fixings=tuple(spots),
    )
    # Funding is applied leg by leg, exactly as on the single-underlying path: the note's
    # bond-like cashflows (principal, coupons) discount on the issuer curve, the embedded
    # optionality on OIS. The earlier multiplicative shortcut — discounting the *whole* PV by
    # the spread over the full tenor — over-penalised autocalling notes, whose expected life is
    # far shorter than their stated maturity; on a typical 2y note that error was ~40bps of par,
    # inside the range this benchmark is trying to resolve.
    discount = funding_discounter(r, funding_spread) if funding_spread else None
    if local_vols is not None and all(t in local_vols for t in names):
        pv = price_worst_of_lv(
            note, spots, [local_vols[t] for t in names], corr,
            r=r, q=q, n_paths=n_paths, seed=seed, steps_per_year=steps_per_year,
        ).price
        if funding_spread:  # the LV pricer has no discount hook yet; keep the old approximation
            pv *= exp(-funding_spread * (filing.tenor_years or 0.0))
    else:
        pv = price_worst_of(
            note, spots, sigma, corr, r=r, q=q, n_paths=n_paths, seed=seed, discount=discount
        ).price
    return float(pv)


def implied_correlation(
    filing: NoteFiling,
    *,
    vols: dict[str, float],
    r: float,
    q: float,
    funding_spread: float = 0.012,
    n_paths: int = 60_000,
    seed: int = 0,
    bracket: tuple[float, float] = (-0.20, 0.99),
    local_vols: dict[str, object] | None = None,
) -> float | None:
    """The correlation at which the model reproduces the issuer's disclosed value.

    **This is the identified version of the benchmark.** A worst-of note's value depends on the
    constituents' vols and on their correlation. The vols are *observable* — each name has a
    listed option market, and :mod:`spdt.data.ingest.cboe` reads them — so pinning those leaves
    correlation as the single free parameter, and one disclosed value is exactly enough to
    determine one unknown.

    That matters because correlation is the input a structured-products desk has no clean
    market for. There is no liquid instrument quoting the correlation of Meta against Apple
    against Tesla, yet it is the dominant lever on every worst-of price. Inverting it out of
    notes that actually traded answers a question the market does not otherwise publish:
    **what correlation is the street pricing worst-of autocallables at?**

    The reading is again a sanity range rather than a point: realised equity correlations among
    large-cap US names run roughly 0.3–0.7, and dealers are widely understood to mark
    correlation *conservatively high* when selling worst-of, because a higher correlation lowers
    dispersion, lowers the worst-of's downside and so raises the note's value to them. An
    implied correlation above realised is therefore the expected finding, and its size is the
    interesting number. A value pinned at the bracket ends means the disclosed value is
    unreachable for any correlation, which points at the vol or funding input instead.
    """
    target = filing.estimated_value_pct
    if target is None or not filing.is_worst_of:
        return None

    def gap(rho: float) -> float:
        return (
            price_worst_of_filing(
                filing, vols=vols, rho=rho, r=r, q=q, funding_spread=funding_spread,
                n_paths=n_paths, seed=seed, local_vols=local_vols,
            )
            - target
        )

    lo, hi = bracket
    try:
        if gap(lo) * gap(hi) > 0:
            return None
        return float(brentq(gap, lo, hi, xtol=1e-4, maxiter=60))
    except (ValueError, RuntimeError):
        return None


@dataclass(frozen=True)
class BenchmarkSummary:
    """The distribution of gaps — the level at which this benchmark carries information."""

    n: int
    mean_gap: float
    median_gap: float
    std_gap: float
    min_gap: float
    max_gap: float
    mean_disclosed_load: float
    n_trustworthy: int

    @property
    def verdict(self) -> str:
        """A plain-language reading of the gap distribution.

        Thresholds are judgement calls, stated here rather than buried: a structured note desk
        would regard a persistent 1-point disagreement on a par-100 note as significant, since
        it is a quarter of a typical fee load.
        """
        if self.n == 0:
            return "no benchmarkable filings"
        if abs(self.mean_gap) < 0.5 and self.std_gap < 1.0:
            return "model agrees with issuer valuations within noise"
        if abs(self.mean_gap) >= 0.5 and self.std_gap < 1.0:
            return (
                f"systematic bias of {self.mean_gap:+.2f}pts with tight dispersion — "
                "likely a funding or dividend assumption, not a modelling error"
            )
        return (
            f"dispersion of {self.std_gap:.2f}pts is too wide to call agreement; "
            "inspect the gap against tenor and underlying before drawing conclusions"
        )


def summarise(results: list[BenchmarkResult]) -> BenchmarkSummary:
    """Aggregate benchmark results. A single note's gap is not evidence; this is."""
    if not results:
        nan = float("nan")
        return BenchmarkSummary(
            n=0, mean_gap=nan, median_gap=nan, std_gap=nan,
            min_gap=nan, max_gap=nan, mean_disclosed_load=nan, n_trustworthy=0,
        )
    gaps = np.array([r.gap for r in results], dtype=float)
    loads = np.array(
        [r.filing.disclosed_load_pct or float("nan") for r in results], dtype=float
    )
    return BenchmarkSummary(
        n=len(results),
        mean_gap=float(gaps.mean()),
        median_gap=float(np.median(gaps)),
        std_gap=float(gaps.std(ddof=1)) if len(gaps) > 1 else 0.0,
        min_gap=float(gaps.min()),
        max_gap=float(gaps.max()),
        mean_disclosed_load=float(np.nanmean(loads)) if np.isfinite(loads).any() else float("nan"),
        n_trustworthy=sum(r.is_trustworthy for r in results),
    )


def gap_by_tenor(results: list[BenchmarkResult]) -> dict[str, float]:
    """Mean gap bucketed by tenor — where a term-structure error would show up.

    A model that is right at one year and drifting at three is not "roughly right"; it has a
    specific defect in how it extrapolates vol or carry, and averaging the two hides it.
    """
    buckets: dict[str, list[float]] = {"<=1y": [], "1-2y": [], ">2y": []}
    for r in results:
        tenor = r.filing.tenor_years or 0.0
        key = "<=1y" if tenor <= 1.25 else ("1-2y" if tenor <= 2.25 else ">2y")
        buckets[key].append(r.gap)
    return {k: float(np.mean(v)) for k, v in buckets.items() if v}


def shaped_correlation(names: list[str], base: np.ndarray, scale: float) -> np.ndarray:
    """A realised-shape correlation matrix moved by one scale factor.

    Equicorrelation assumes META–AAPL and AAPL–TSLA are equally correlated, which they are not,
    and on a worst-of that assumption is not neutral: the *least* correlated pair dominates the
    dispersion and therefore the price. This keeps the relative shape of an observed (realised)
    correlation matrix and moves the whole thing toward or away from 1 with a single parameter:

        rho_ij(scale) = 1 - scale * (1 - base_ij)        for i != j

    ``scale = 1`` returns the base matrix; ``scale -> 0`` approaches perfect correlation;
    ``scale > 1`` pushes pairs further apart than realised. One disclosed value still identifies
    exactly one parameter — the same identification argument as equicorrelation — but what is
    being scaled is now the market's own shape rather than a flat guess.

    Two degeneracies are handled *here* rather than left to the caller, because both failed
    silently once: at ``scale = 0`` the matrix is all ones — positive semi-definite but
    singular, and ``np.linalg.cholesky`` raises ``LinAlgError``, which subclasses ``ValueError``
    and so vanished into the solver's except-clause, making every inversion read "unreachable".
    Off-diagonals are therefore capped at 0.995. And for large scales on a weakly-correlated
    basket the matrix can leave the PSD cone entirely; eigenvalues are clipped and the result
    renormalised to unit diagonal, the standard nearest-correlation repair.
    """
    base = np.asarray(base, dtype=float)
    if base.shape != (len(names), len(names)):
        raise ValueError(f"base correlation is {base.shape}, need {(len(names), len(names))}")
    off = 1.0 - scale * (1.0 - base)
    out = np.where(np.eye(len(names), dtype=bool), 1.0, np.clip(off, -0.99, 0.995))
    vals, vecs = np.linalg.eigh(out)
    if vals.min() < 1e-8:
        repaired = vecs @ np.diag(np.maximum(vals, 1e-8)) @ vecs.T
        d = np.sqrt(np.diag(repaired))
        out = repaired / np.outer(d, d)
        np.fill_diagonal(out, 1.0)
    return out


def realised_correlation(
    series: dict[str, "np.ndarray"], *, min_overlap: int = 60
) -> np.ndarray | None:
    """Pairwise correlation of log returns from aligned price series, or ``None`` if too short.

    The *shape* input to :func:`shaped_correlation`. Estimated from history, so it is a
    real-world-measure quantity standing in for a risk-neutral one — a known abuse, shared by
    every desk that marks correlation off realised plus a spread. The scale factor solved
    downstream absorbs exactly that spread, which is what makes it interpretable: scale < 1
    means the disclosed value needs *higher-than-realised* correlation to reconcile.
    """
    names = list(series)
    length = min(len(series[t]) for t in names)
    if length < min_overlap + 1:
        return None
    returns = np.column_stack(
        [np.diff(np.log(np.asarray(series[t], dtype=float)[-length:])) for t in names]
    )
    return np.corrcoef(returns, rowvar=False)


def implied_correlation_scale(
    filing: NoteFiling,
    *,
    vols: dict[str, float],
    base_corr: np.ndarray,
    r: float,
    q: float,
    funding_spread: float = 0.012,
    n_paths: int = 60_000,
    seed: int = 0,
    bracket: tuple[float, float] = (0.0, 1.8),
) -> float | None:
    """Solve for the scale on a realised-shape correlation that reproduces the disclosed value.

    The refinement over :func:`implied_correlation`: same single-parameter identification, but
    the parameter now *means* something checkable — ``scale = 1`` says the issuer priced at
    realised correlation, ``scale < 1`` says they marked correlation above realised (the
    expected dealer behaviour, since higher correlation raises a worst-of's value), and a
    solution outside the bracket says the disagreement is not a correlation mark at all.
    """
    target = filing.estimated_value_pct
    if target is None or not filing.is_worst_of:
        return None
    names = [t for t, _ in filing.starting_values if t in vols]
    if len(names) < 2:
        return None

    def gap(scale: float) -> float:
        corr = shaped_correlation(names, base_corr, scale)
        starts = dict(filing.starting_values)
        spots = np.array([starts[t] for t in names])
        sigma = np.array([vols[t] for t in names])
        wo = WorstOfAutocallable(
            notional=100.0,
            observation_times=filing.observation_times(),
            coupon_rate=(filing.coupon_per_period or 0.0) / filing.denomination,
            autocall_level=filing.call_level or 1.0,
            coupon_barrier=filing.coupon_barrier or 0.8,
            knock_in=filing.knock_in or 0.6,
            memory=filing.memory,
            underlyings=tuple(names),
            initial_fixings=tuple(spots),
        )
        discount = funding_discounter(r, funding_spread) if funding_spread else None
        pv = price_worst_of(
            wo, spots, sigma, corr, r=r, q=q, n_paths=n_paths, seed=seed, discount=discount
        ).price
        return float(pv) - target

    lo, hi = bracket
    try:
        if gap(lo) * gap(hi) > 0:
            return None
        return float(brentq(gap, lo, hi, xtol=1e-4, maxiter=60))
    except (ValueError, RuntimeError):
        return None
