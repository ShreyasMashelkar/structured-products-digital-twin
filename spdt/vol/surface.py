"""VolSurface: the calibrated, queryable, arbitrage-checked surface a snapshot carries (L2).

Built from the IV points the data layer inverts (:func:`spdt.data.curate.invert_chain`), one
raw-SVI slice per expiry. Exposes ``vol(K, T)`` / total variance, carries its arbitrage
diagnostics, and is **content-hashable** so it participates in the snapshot's content hash
(the snapshot hashes a surface by its ``content_hash``, never by importing this class).

Cross-tenor queries interpolate **linearly in total variance** at fixed log-moneyness — the
representation in which calendar no-arbitrage is stated — with flat extrapolation past the
first/last calibrated tenor.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from types import MappingProxyType
from dataclasses import dataclass
from datetime import date
from math import exp, log, sqrt
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from spdt.vol.arbitrage import ArbReport, check_slices
from spdt.vol.quality import BucketError, FitReport, SliceFit, assess_fit
from spdt.vol.svi import SVIParams, calibrate_svi, total_variance_from_iv

if TYPE_CHECKING:
    from spdt.core.snapshot import MarketSnapshot
    from spdt.data.curate.bs_inversion import IVPoint


def _fit_to_dict(fit: FitReport | None) -> dict[str, Any] | None:
    """Serialise a :class:`FitReport`, rendering slice expiry dates as ISO strings."""
    if fit is None:
        return None
    d = dataclasses.asdict(fit)
    for s in d["slices"]:
        s["expiry"] = s["expiry"].isoformat()
    return d


@dataclass(frozen=True)
class VolSurface:
    """Calibrated SVI/SSVI surface for one underlying (design doc §7)."""

    underlying: str
    param_model: str  # "SVI" for this slice; "SSVI" arrives later
    slices: Mapping[date, SVIParams]
    taus: Mapping[date, float]  # expiry -> ACT/365F year fraction
    forwards: Mapping[date, float]  # expiry -> forward used to define k = log(K/F)
    arb_status: ArbReport
    # How closely the fit reproduces the quotes, in vol bps (``spdt.vol.quality``). Optional
    # because a surface can be rebuilt from parameters alone (``from_dict``), at which point
    # the original quotes are gone and fit quality is unknowable rather than merely unmeasured.
    fit_status: FitReport | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "slices", MappingProxyType(dict(self.slices)))
        object.__setattr__(self, "taus", MappingProxyType(dict(self.taus)))
        object.__setattr__(self, "forwards", MappingProxyType(dict(self.forwards)))

    # --- queries ----------------------------------------------------------------------

    def _ordered(self) -> list[date]:
        return sorted(self.slices, key=lambda e: self.taus[e])

    def total_variance(self, k: float | NDArray, tau: float) -> float | NDArray:
        """Total variance at log-moneyness ``k`` and year-fraction ``tau``.

        Accepts an **array** of strikes as well as a scalar, returning the matching shape. The
        Dupire construction in :func:`spdt.pricing.models.localvol.local_vol_from_surface`
        evaluates this on a whole vector of simulated spots at every time step, so a scalar-only
        implementation confines the surface to closed-form use and silently forces local-vol
        pricing back onto a flat vol.

        Interpolation is linear in total variance at fixed ``k`` — the representation calendar
        no-arbitrage is stated in — with flat extrapolation past the first/last calibrated tenor.
        """
        expiries = self._ordered()
        taus = [self.taus[e] for e in expiries]
        k_arr = np.asarray(k, dtype=float)
        ws = [np.asarray(self.slices[e].total_variance(k_arr), dtype=float) for e in expiries]

        if tau <= taus[0]:
            out = ws[0]
        elif tau >= taus[-1]:
            out = ws[-1]
        else:
            j = int(np.searchsorted(taus, tau))
            lo, hi = taus[j - 1], taus[j]
            weight = (tau - lo) / (hi - lo)
            out = (1.0 - weight) * ws[j - 1] + weight * ws[j]
        return float(out) if np.ndim(k) == 0 else out

    def implied_vol_kt(self, k: float, tau: float) -> float:
        """Implied vol from total variance: ``σ = √(w/τ)``."""
        if tau <= 0.0:
            raise ValueError("implied vol undefined at tau <= 0")
        return sqrt(self.total_variance(k, tau) / tau)

    def implied_vol(self, strike: float, expiry: date) -> float:
        """Implied vol for a strike at a *calibrated* expiry (uses that slice's forward)."""
        if expiry not in self.slices:
            raise KeyError(f"{expiry} is not a calibrated expiry; use implied_vol_kt for interp")
        k = log(strike / self.forwards[expiry])
        return self.implied_vol_kt(k, self.taus[expiry])

    # --- construction -----------------------------------------------------------------

    @classmethod
    def calibrate(
        cls,
        iv_points: list[IVPoint],
        underlying: str,
        *,
        param_model: str = "SVI",
        min_points_per_slice: int = 5,
    ) -> VolSurface:
        """Calibrate one SVI slice per expiry from inverted IV points.

        The forward per expiry is recovered from the points themselves
        (``F = K·exp(−k)``), so no separate forward input is needed. ``param_model="SVI"`` fits one
        independent SVI slice per expiry; ``"SSVI"`` fits a single Gatheral–Jacquier surface
        (calendar-free by construction, butterfly-constrained) and emits its exact per-slice SVI
        form — the arbitrage-free route for noisy real-market surfaces.

        ``min_points_per_slice`` drops expiries with too few quotes to identify the model. Raw
        SVI has five parameters, so four points do not merely fit badly — they fit *perfectly*
        and meaninglessly, interpolating noise with an unidentified parameter left free to take
        any value. Once a liquidity filter is applied to a real chain this is the common case,
        not an edge case: illiquid expiries survive with a handful of traded strikes. Omitting
        such a slice is the honest outcome, and the surface's tenor interpolation then spans
        the gap from the liquid expiries on either side instead of inventing a smile.
        """
        if param_model not in ("SVI", "SSVI", "eSSVI"):
            raise NotImplementedError(f"param_model {param_model!r} not supported")

        by_expiry: dict[date, list[IVPoint]] = {}
        for p in iv_points:
            by_expiry.setdefault(p.expiry, []).append(p)

        ssvi_slices: dict[float, SVIParams] = {}
        if param_model == "SSVI":
            from spdt.vol.ssvi import SSVISurface

            ssvi_slices = SSVISurface.calibrate(iv_points).to_svi_slices()
        elif param_model == "eSSVI":
            # Per-tenor skew under the Hendriks–Martini adjacency conditions: the middle
            # ground the other two bracket. SVI fits best and guarantees nothing across
            # tenors; SSVI guarantees everything with one global shape and pays ~55bps for
            # it; eSSVI keeps the guarantees per-pair and lets each tenor carry its own rho.
            from spdt.vol.essvi import ESSVISurface

            ssvi_slices = ESSVISurface.calibrate(iv_points).to_svi_slices()

        slices: dict[date, SVIParams] = {}
        taus: dict[date, float] = {}
        forwards: dict[date, float] = {}
        for expiry, pts in by_expiry.items():
            if len(pts) < min_points_per_slice:
                continue  # too few liquid quotes to identify five SVI parameters
            tau = pts[0].tau
            if param_model in ("SSVI", "eSSVI"):
                if tau not in ssvi_slices:
                    continue  # expiry with non-positive ATM variance — skip
                slices[expiry] = ssvi_slices[tau]
            else:
                k = np.array([p.log_moneyness for p in pts])
                w = total_variance_from_iv(np.array([p.implied_vol for p in pts]), tau)
                slices[expiry] = calibrate_svi(k, np.asarray(w))
            taus[expiry] = tau
            forwards[expiry] = float(np.median([p.strike * exp(-p.log_moneyness) for p in pts]))

        ordered = sorted(slices, key=lambda e: taus[e])
        arb = check_slices([slices[e] for e in ordered])
        fit = assess_fit(iv_points, slices, taus)
        return cls(underlying, param_model, slices, taus, forwards, arb, fit)

    # --- content hash + (de)serialisation ---------------------------------------------

    @property
    def content_hash(self) -> str:
        """SHA-256 over the calibrated parameters — lets the snapshot hash the surface."""
        canonical = {
            "underlying": self.underlying,
            "param_model": self.param_model,
            "slices": sorted(
                [
                    [
                        e.isoformat(),
                        round(self.taus[e], 12),
                        round(self.forwards[e], 12),
                        [
                            round(p.a, 12),
                            round(p.b, 12),
                            round(p.rho, 12),
                            round(p.m, 12),
                            round(p.sigma, 12),
                        ],
                    ]
                    for e, p in self.slices.items()
                ]
            ),
        }
        blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "underlying": self.underlying,
            "param_model": self.param_model,
            "slices": [
                {
                    "expiry": e.isoformat(),
                    "tau": self.taus[e],
                    "forward": self.forwards[e],
                    "params": dataclasses.astuple(self.slices[e]),
                }
                for e in self._ordered()
            ],
            "arb_status": dataclasses.asdict(self.arb_status),
            "fit_status": _fit_to_dict(self.fit_status),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VolSurface:
        slices: dict[date, SVIParams] = {}
        taus: dict[date, float] = {}
        forwards: dict[date, float] = {}
        for s in d["slices"]:
            e = date.fromisoformat(s["expiry"])
            slices[e] = SVIParams(*s["params"])
            taus[e] = s["tau"]
            forwards[e] = s["forward"]
        fit_raw = d.get("fit_status")
        fit = (
            FitReport(
                n_points=fit_raw["n_points"],
                rmse_bps=fit_raw["rmse_bps"],
                max_abs_bps=fit_raw["max_abs_bps"],
                slices=tuple(
                    SliceFit(**{**s, "expiry": date.fromisoformat(str(s["expiry"]))})
                    for s in fit_raw["slices"]
                ),
                buckets=tuple(BucketError(**b) for b in fit_raw["buckets"]),
            )
            if fit_raw
            else None
        )
        return cls(
            underlying=d["underlying"],
            param_model=d["param_model"],
            slices=slices,
            taus=taus,
            forwards=forwards,
            arb_status=ArbReport(**d["arb_status"]),
            fit_status=fit,
        )


def with_surfaces(
    snapshot: MarketSnapshot, surfaces: dict[str, VolSurface]
) -> MarketSnapshot:
    """Return a new snapshot with ``surfaces`` attached (snapshots are immutable)."""
    return dataclasses.replace(snapshot, surfaces=surfaces)
