"""The ``ExposurePackage`` contract — the single artefact SPDT hands XVA (ADR-0007).

SPDT *produces* this from its Monte-Carlo engine (mark-to-future: the position's NPV on every path
at every future time); XVA *consumes* it to compute counterparty/funding/capital charges. This is
the **only** coupling point between the two systems — the two product models never meet.

The contract is intentionally minimal and model-agnostic: a path × time NPV cube, the time grid it
lives on, the counterparty/netting identity, and the curves to discount with. Behaviour (writing
into XVA's ``ExposureCube``, computing EE/EPE/PFE, charging CVA/FVA/KVA) is built on top in later
phases; this module pins only the *shape* so both sides can be developed against it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    from integration.curve_adapter import SpdtCurveAsOIS


@dataclass(frozen=True)
class ExposurePackage:
    """Mark-to-future exposure of one position, ready for the XVA stack.

    Attributes:
        trade_id: stable identifier for the position.
        counterparty_id: who the exposure is *to* (drives the credit curve in CVA).
        netting_set: netting-set key; carried for portfolio netting (the current charge is
            single-trade — see the roadmap in ``docs/adr/0007``).
        time_grid: shape ``(n_times,)`` year-fractions from today. Exposure is **uncollateralised**:
            no CSA / margin-period-of-risk gap is applied (collateralised EPE is a planned extension).
        npv_paths: shape ``(n_paths, n_times)`` — the position NPV on each path at each time.
        ois_curve: discounting curve for the option/hedge leg (adapted SPDT OIS curve).
        funding_curve: issuer funding curve (OIS + spread) — the FVA driver.
        ccy: settlement currency (``"INR"`` for this platform).
    """

    trade_id: str
    counterparty_id: str
    netting_set: str
    time_grid: NDArray[np.float64]
    npv_paths: NDArray[np.float64]
    ois_curve: "SpdtCurveAsOIS"
    funding_curve: "SpdtCurveAsOIS"
    ccy: str = "INR"

    def __post_init__(self) -> None:
        if self.npv_paths.ndim != 2:
            raise ValueError("npv_paths must be 2-D (n_paths, n_times)")
        if self.npv_paths.shape[1] != self.time_grid.shape[0]:
            raise ValueError("npv_paths second axis must match time_grid length")

    @property
    def n_paths(self) -> int:
        return int(self.npv_paths.shape[0])

    @property
    def n_times(self) -> int:
        return int(self.time_grid.shape[0])

    def expected_exposure(self) -> NDArray[np.float64]:
        """EE(t) = E[max(V_t, 0)] — the positive-exposure profile, undiscounted.

        A convenience cross-check; the production path runs through XVA's ``ExposureCube`` so the
        netting and persistence match the rest of the platform. Pinned here so the contract is
        testable in isolation.
        """
        return np.maximum(self.npv_paths, 0.0).mean(axis=0)
