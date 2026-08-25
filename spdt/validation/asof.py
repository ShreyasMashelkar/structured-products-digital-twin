"""Rebuild the market as it stood on a historical business date (L8).

The engine's live path builds today's snapshot from today's bhavcopy. Validation needs the
same object for a date years ago — and needs it built from *only* what was observable then,
because a snapshot contaminated with hindsight validates nothing.

Two properties make that honest here:

* The snapshot is assembled from a single day's F&O bhavcopy — spot, option chain and the
  forward all come from one file published that evening. Nothing later than ``as_of`` enters.
* The result is the ordinary :class:`~spdt.core.snapshot.MarketSnapshot`, content-hashed like
  any other, so historical and live runs go through identical downstream code. A validation
  harness with its own private pricing path proves nothing about the production one.

**The regimes.** A model that works in 2024's calm market and is only ever tested there has
not been tested. The dates below were chosen because each broke something different:

===============  ==================================================================
2018-09-21       IL&FS default — a credit event that hit an equity market with no
                 warning; NIFTY fell ~10% over the following weeks.
2020-03-23       COVID crash bottom — the highest realised and implied vol in the
                 index's history, and the single hardest day to calibrate.
2022-06-17       Global hiking cycle — the regime the rate model is supposed to
                 handle, with the curve moving in level *and* shape.
2024-06-04       Election-result day — a one-session ~6% gap, i.e. a jump the
                 diffusion model structurally cannot produce.
2025-01-15       Ordinary conditions — the control. Without it, poor stressed-date
                 results cannot be separated from a generally broken model.
===============  ==================================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import log, sqrt

import numpy as np

from spdt.core.snapshot import MarketSnapshot
from spdt.data import build_snapshot
from spdt.data.curate import invert_chain
from spdt.data.curate.bs_inversion import IVPoint
from spdt.data.ingest.nse_historical import bhavcopy_source_for
from spdt.vol.surface import VolSurface, with_surfaces

# (label, date, one-line description) — the regime sweep the report runs over.
REGIMES: tuple[tuple[str, date, str], ...] = (
    ("ILFS_2018", date(2018, 9, 21), "IL&FS credit event"),
    ("COVID_2020", date(2020, 3, 23), "COVID crash bottom"),
    ("HIKES_2022", date(2022, 6, 17), "Global hiking cycle"),
    ("ELECTION_2024", date(2024, 6, 4), "Election-result gap"),
    ("CALM_2025", date(2025, 1, 15), "Ordinary conditions (control)"),
)

# Liquidity filters for historical chains. Settlement prints in the far wings are stale often
# enough that leaving them in dominates the calibration; ``otm_only`` additionally drops the
# ITM half of each strike, which the exchange does not force into put-call parity.
_MONEYNESS_BAND = 1.0
_IV_BOUNDS = (0.05, 2.0)
# A contract must have actually traded and be held by someone. Without this the long-dated
# expiries — which on NIFTY frequently print zero volume for months — contribute exchange
# settlement marks that invert to a plausible-looking but entirely fictional term structure.
_MIN_CONTRACTS = 1.0
_MIN_OPEN_INTEREST = 1.0
# Raw SVI has five parameters. Five points therefore fit *exactly* — RMSE ≈ 0 — while
# identifying nothing, and that spurious perfect fit then reads as a high-quality slice. Eight
# points leaves genuine degrees of freedom, so the reported RMSE means something.
_MIN_POINTS_PER_SLICE = 8


@dataclass(frozen=True)
class AsOfMarket:
    """A historical market: the snapshot, its calibrated surface, and the quotes behind it."""

    label: str
    description: str
    requested_date: date
    snapshot: MarketSnapshot
    surface: VolSurface
    iv_points: tuple[IVPoint, ...]

    @property
    def as_of(self) -> date:
        """The date actually served — the exchange may not have published on the one asked for."""
        return self.snapshot.date

    @property
    def spot(self) -> float:
        return self.snapshot.spots[self.surface.underlying]

    def atm_vol(self, tau: float) -> float:
        """ATM implied vol at year-fraction ``tau`` — the single number pricing needs most."""
        return self.surface.implied_vol_kt(0.0, tau)

    def realised_atm_term_structure(self) -> dict[float, float]:
        """ATM vol at each calibrated tenor — the shape a flat-vol price throws away."""
        return {
            self.surface.taus[e]: self.surface.implied_vol_kt(0.0, self.surface.taus[e])
            for e in self.surface.slices
        }

    def skew(self, tau: float, *, delta_k: float = 0.10) -> float:
        """25-delta-ish skew proxy: vol at k=−0.10 minus vol at k=+0.10, in vol points."""
        return self.surface.implied_vol_kt(-delta_k, tau) - self.surface.implied_vol_kt(delta_k, tau)


def build_asof_market(
    as_of: date,
    underlying: str = "NIFTY",
    *,
    label: str = "",
    description: str = "",
    param_model: str = "SVI",
    risk_free_rate: float = 0.065,
    dividend_yield: float = 0.013,
) -> AsOfMarket:
    """Fetch, invert and calibrate the market for ``as_of`` — the production path, backdated.

    ``risk_free_rate`` is a flat placeholder for dates where an FBIL curve is not available;
    it shifts the implied forward and therefore log-moneyness, so the report records it as an
    assumption rather than pretending the curve was observed.
    """
    source = bhavcopy_source_for(
        as_of, risk_free_rate=risk_free_rate, dividend_yield=dividend_yield
    )
    raw = source.fetch(as_of, underlying)
    snapshot = build_snapshot(raw)
    points = invert_chain(
        raw,
        snapshot.ois_curve,
        moneyness_band=_MONEYNESS_BAND,
        iv_bounds=_IV_BOUNDS,
        otm_only=True,
        min_contracts=_MIN_CONTRACTS,
        min_open_interest=_MIN_OPEN_INTEREST,
    )
    if not points:
        raise ValueError(f"no option quote survived inversion on {as_of}")

    surface = VolSurface.calibrate(
        points, underlying, param_model=param_model,
        min_points_per_slice=_MIN_POINTS_PER_SLICE,
    )
    return AsOfMarket(
        label=label or as_of.isoformat(),
        description=description,
        requested_date=as_of,
        snapshot=with_surfaces(snapshot, {underlying: surface}),
        surface=surface,
        iv_points=tuple(points),
    )


def build_regime_markets(
    underlying: str = "NIFTY", *, param_model: str = "SVI"
) -> list[AsOfMarket]:
    """Build every market in :data:`REGIMES`, skipping any date the archive cannot serve.

    A missing date is reported by omission rather than by aborting the sweep: one unavailable
    archive file should not cost the other four regimes.
    """
    markets: list[AsOfMarket] = []
    for label, day, description in REGIMES:
        try:
            markets.append(
                build_asof_market(
                    day, underlying, label=label, description=description,
                    param_model=param_model,
                )
            )
        except Exception as exc:  # noqa: BLE001 - a bad date must not sink the sweep
            print(f"  [skip] {label} ({day}): {type(exc).__name__}: {exc}")
    return markets


def realised_vol(series: np.ndarray, *, window: int = 21, days_per_year: int = 252) -> float:
    """Close-to-close annualised realised vol over the last ``window`` observations.

    Reported next to implied vol because the gap between them is the variance risk premium the
    note is really selling — and in a crash that gap inverts, which is exactly when an
    autocallable's economics stop behaving the way the pricing assumed.
    """
    if len(series) < window + 1:
        raise ValueError(f"need {window + 1} observations for a {window}-day realised vol")
    logret = np.diff(np.log(np.asarray(series, dtype=float)[-(window + 1):]))
    return float(np.std(logret, ddof=1) * sqrt(days_per_year))


def moneyness_of(strike: float, forward: float) -> float:
    """Log-moneyness ``k = log(K/F)`` — the surface's native coordinate."""
    return log(strike / forward)
