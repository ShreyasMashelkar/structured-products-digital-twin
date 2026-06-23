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
from dataclasses import dataclass
from datetime import date
from math import exp, log, sqrt
from typing import TYPE_CHECKING, Any

import numpy as np

from spdt.vol.arbitrage import ArbReport, check_slices
from spdt.vol.svi import SVIParams, calibrate_svi, total_variance_from_iv

if TYPE_CHECKING:
    from spdt.core.snapshot import MarketSnapshot
    from spdt.data.curate.bs_inversion import IVPoint


@dataclass(frozen=True)
class VolSurface:
    """Calibrated SVI/SSVI surface for one underlying (design doc §7)."""

    underlying: str
    param_model: str  # "SVI" for this slice; "SSVI" arrives later
    slices: dict[date, SVIParams]
    taus: dict[date, float]  # expiry -> ACT/365F year fraction
    forwards: dict[date, float]  # expiry -> forward used to define k = log(K/F)
    arb_status: ArbReport

    # --- queries ----------------------------------------------------------------------

    def _ordered(self) -> list[date]:
        return sorted(self.slices, key=lambda e: self.taus[e])

    def total_variance(self, k: float, tau: float) -> float:
        """Total variance at log-moneyness ``k`` and year-fraction ``tau``."""
        expiries = self._ordered()
        taus = [self.taus[e] for e in expiries]
        ws = [float(self.slices[e].total_variance(k)) for e in expiries]
        if tau <= taus[0]:
            return ws[0]
        if tau >= taus[-1]:
            return ws[-1]
        return float(np.interp(tau, taus, ws))

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
        cls, iv_points: list[IVPoint], underlying: str, *, param_model: str = "SVI"
    ) -> VolSurface:
        """Calibrate one SVI slice per expiry from inverted IV points.

        The forward per expiry is recovered from the points themselves
        (``F = K·exp(−k)``), so no separate forward input is needed. ``param_model="SVI"`` fits one
        independent SVI slice per expiry; ``"SSVI"`` fits a single Gatheral–Jacquier surface
        (calendar-free by construction, butterfly-constrained) and emits its exact per-slice SVI
        form — the arbitrage-free route for noisy real-market surfaces.
        """
        if param_model not in ("SVI", "SSVI"):
            raise NotImplementedError(f"param_model {param_model!r} not supported")

        by_expiry: dict[date, list[IVPoint]] = {}
        for p in iv_points:
            by_expiry.setdefault(p.expiry, []).append(p)

        ssvi_slices: dict[float, SVIParams] = {}
        if param_model == "SSVI":
            from spdt.vol.ssvi import SSVISurface

            ssvi_slices = SSVISurface.calibrate(iv_points).to_svi_slices()

        slices: dict[date, SVIParams] = {}
        taus: dict[date, float] = {}
        forwards: dict[date, float] = {}
        for expiry, pts in by_expiry.items():
            tau = pts[0].tau
            if param_model == "SSVI":
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
        return cls(underlying, param_model, slices, taus, forwards, arb)

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
        return cls(
            underlying=d["underlying"],
            param_model=d["param_model"],
            slices=slices,
            taus=taus,
            forwards=forwards,
            arb_status=ArbReport(**d["arb_status"]),
        )


def with_surfaces(
    snapshot: MarketSnapshot, surfaces: dict[str, VolSurface]
) -> MarketSnapshot:
    """Return a new snapshot with ``surfaces`` attached (snapshots are immutable)."""
    return dataclasses.replace(snapshot, surfaces=surfaces)
