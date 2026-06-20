"""Foundational value types shared across every layer.

These are the small, immutable objects the whole system is built on (design doc §7).
They are deliberately dependency-light: nothing here imports a pricing/vol/corr layer,
so `core` sits cleanly at the bottom of the dependency graph.

Day count: every year-fraction in this module is **ACT/365F** — `tau = (d - anchor).days / 365`.
That is the convention used for discounting and drift throughout SPDT; it is stated once,
here, rather than rediscovered per call site.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from math import exp, log

Underlying = str
"""An underlying identifier, e.g. ``"NIFTY"`` or ``"RELIANCE"``."""

ACT_365F = 365.0


def year_fraction(anchor: date, target: date) -> float:
    """ACT/365F year fraction from ``anchor`` to ``target`` (negative if in the past)."""
    return (target - anchor).days / ACT_365F


class SourceTag(str, Enum):
    """Where a snapshot field came from — drives the provenance summary in risk reports."""

    OBSERVED = "observed"
    INTERPOLATED = "interpolated"
    SYNTHETIC = "synthetic"


class InterpMethod(str, Enum):
    """Curve interpolation scheme. Default is log-linear on discount factors (§7)."""

    LOG_LINEAR_DF = "log_linear_df"
    MONOTONE_CONVEX = "monotone_convex"


def _interp_linear(xs: list[float], ys: list[float], x: float) -> float:
    """Linear interpolation over sorted ``xs`` with flat extrapolation at both ends."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    # xs is short (a handful of curve pillars); a linear scan is clearer than bisect here.
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1 = xs[i - 1], xs[i]
            y0, y1 = ys[i - 1], ys[i]
            w = (x - x0) / (x1 - x0)
            return y0 + w * (y1 - y0)
    return ys[-1]  # unreachable; satisfies type checker


@dataclass(frozen=True)
class Curve:
    """A single bootstrapped term structure of discount factors (design doc §7, ADR-0002).

    Two shapes, distinguished by ``spread_over``:

    * **OIS / risk-free** (``spread_over is None``): the discount factors live in
      ``discount_factors``, keyed by pillar date and solved maturity-by-maturity upstream.
    * **Issuer funding** (``spread_over`` set): not bootstrapped independently. Its discount
      factor is ``D_funding(T) = D_ois(T) · exp(-s(T)·T)`` where ``s(T)`` is the parametric
      credit/funding spread in ``spread_knots`` (ADR-0002). This keeps the OIS↔funding basis
      coherent under rate moves and makes the spread a first-class, shockable factor.

    Zero rates and forwards are *derived* from discount factors, never stored, so the curve
    can never be internally inconsistent.
    """

    anchor: date
    pillars: tuple[date, ...] = ()
    discount_factors: dict[date, float] | None = None
    interp: InterpMethod = InterpMethod.LOG_LINEAR_DF
    spread_over: "Curve | None" = None
    spread_knots: dict[date, float] | None = None

    def __post_init__(self) -> None:
        if self.spread_over is None:
            if not self.discount_factors:
                raise ValueError("OIS-style curve requires non-empty discount_factors")
            if self.interp is not InterpMethod.LOG_LINEAR_DF:
                # Monotone-convex is declared in the schema but not yet implemented; fail
                # loudly rather than silently using log-linear.
                raise NotImplementedError(f"interp {self.interp.value!r} not yet supported")
        elif not self.spread_knots:
            raise ValueError("funding curve (spread_over set) requires spread_knots")

    # --- discount factors -------------------------------------------------------------

    def _ln_df_ois(self, tau: float) -> float:
        assert self.discount_factors is not None
        # Implicit pillar at the anchor: D(0) = 1, i.e. ln D = 0.
        pairs = sorted(
            (year_fraction(self.anchor, d), log(df)) for d, df in self.discount_factors.items()
        )
        taus = [0.0] + [t for t, _ in pairs]
        ln_dfs = [0.0] + [v for _, v in pairs]
        if tau <= taus[-1]:
            return _interp_linear(taus, ln_dfs, tau)
        # Flat zero-rate extrapolation beyond the last pillar.
        z_last = -ln_dfs[-1] / taus[-1]
        return -z_last * tau

    def _spread(self, tau: float) -> float:
        assert self.spread_knots is not None
        pairs = sorted((year_fraction(self.anchor, d), s) for d, s in self.spread_knots.items())
        return _interp_linear([t for t, _ in pairs], [s for _, s in pairs], tau)

    def discount_factor(self, target: date) -> float:
        """Discount factor ``D(target)`` seen from ``anchor``."""
        return self.df(year_fraction(self.anchor, target))

    def df(self, tau: float) -> float:
        """Discount factor at year-fraction ``tau`` from the anchor.

        The year-fraction form the pricer works in (cashflows are dated in ACT/365F year
        fractions), avoiding a tau→date→tau round trip. Funding curves compose the OIS
        discount with the parametric spread (ADR-0002): ``D_f(τ) = D_ois(τ)·exp(−s(τ)·τ)``.
        """
        if tau <= 0.0:
            return 1.0
        if self.spread_over is not None:
            return self.spread_over.df(tau) * exp(-self._spread(tau) * tau)
        return exp(self._ln_df_ois(tau))

    def zero_rate(self, target: date) -> float:
        """Continuously-compounded zero rate ``z(T) = -ln D(T) / T``."""
        tau = year_fraction(self.anchor, target)
        if tau <= 0.0:
            return 0.0
        return -log(self.discount_factor(target)) / tau

    def forward_rate(self, start: date, end: date) -> float:
        """Continuously-compounded forward rate ``f(t1,t2)`` between two dates."""
        tau = year_fraction(start, end)
        if tau <= 0.0:
            raise ValueError("forward_rate requires end strictly after start")
        return (log(self.discount_factor(start)) - log(self.discount_factor(end))) / tau


@dataclass(frozen=True)
class DividendSchedule:
    """Dividend assumption for one underlying (design doc §7).

    Supports a continuous proportional yield ``q`` (the common index assumption) and/or
    discrete cash dividends. Equity exotics on NIFTY are typically modelled with a yield.
    """

    continuous_yield: float = 0.0
    cash_dividends: tuple[tuple[date, float], ...] = ()


@dataclass(frozen=True)
class CorrelationMatrix:
    """A labelled, PSD-validated correlation matrix (feeds L4/L12, design doc §7).

    Core only enforces structural validity (square, symmetric, unit diagonal). Estimation
    and Higham PSD *repair* live in ``spdt.corr``; by the time a matrix reaches a snapshot
    it is expected to already be valid.
    """

    labels: tuple[Underlying, ...]
    matrix: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        n = len(self.labels)
        if len(self.matrix) != n or any(len(row) != n for row in self.matrix):
            raise ValueError("matrix must be square and match the number of labels")
        for i in range(n):
            if abs(self.matrix[i][i] - 1.0) > 1e-9:
                raise ValueError("correlation matrix must have unit diagonal")
            for j in range(i + 1, n):
                if abs(self.matrix[i][j] - self.matrix[j][i]) > 1e-9:
                    raise ValueError("correlation matrix must be symmetric")

    def get(self, a: Underlying, b: Underlying) -> float:
        """Pairwise correlation between underlyings ``a`` and ``b``."""
        i, j = self.labels.index(a), self.labels.index(b)
        return self.matrix[i][j]
