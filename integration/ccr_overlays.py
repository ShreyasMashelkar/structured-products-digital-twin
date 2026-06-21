"""CCR exposure overlays — netting, collateral (CSA/MPoR), and wrong-way risk (ADR-0007).

Three transforms that sit *between* the raw mark-to-future cube and the XVA charge, each reducing or
re-shaping exposure the way a real CCR desk would before it computes CVA:

* **Netting** — aggregate the NPV cubes of trades in one netting set on common paths, so offsetting
  positions cancel *before* the positive part is taken. EE(ΣVₖ) ≤ Σ EE(Vₖ): the netting benefit.
* **Collateral** — apply a CSA (threshold / MTA / margin-period-of-risk) so the residual exposure is
  only the close-out gap over the MPoR, not the full MTM. Delegates to the engine's ``CSAEngine``,
  which carries an MPoR-aware close-out even on a coarse grid.
* **Wrong-way risk** — tilt the exposure measure so paths with high exposure are up-weighted when the
  counterparty defaults (exponential / Esscher tilt). ``beta > 0`` is wrong-way (raises CVA),
  ``beta < 0`` is right-way; ``beta = 0`` recovers the independent EE.

The vendored engine ships fuller WWR (Gaussian-copula, stochastic-intensity) for its swap book; the
tilt here is the self-contained equity-seam version that needs only the exposure cube.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

import numpy as np
from numpy.typing import NDArray

from integration.exposure_package import ExposurePackage
from src.csa.collateral import CSAEngine  # type: ignore  # resolved via integration


def netting_set_exposure(
    packages: Sequence[ExposurePackage], *, trade_id: str | None = None
) -> ExposurePackage:
    """Aggregate one netting set into a single package — NPVs sum *before* exposure is taken.

    All packages must share a time grid, path count, counterparty, netting set and curves (the
    cubes must be simulated on common random numbers for the netting to be economically meaningful).
    """
    if not packages:
        raise ValueError("netting_set_exposure needs at least one package")
    first = packages[0]
    for p in packages[1:]:
        if p.npv_paths.shape != first.npv_paths.shape:
            raise ValueError("netting set packages must share (n_paths, n_times) — common paths")
        if not np.allclose(p.time_grid, first.time_grid):
            raise ValueError("netting set packages must share a time grid")
        if (p.counterparty_id, p.netting_set) != (first.counterparty_id, first.netting_set):
            raise ValueError("netting only applies within one counterparty/netting-set")
    netted = np.sum([p.npv_paths for p in packages], axis=0)
    return replace(
        first,
        trade_id=trade_id or f"NET[{'+'.join(p.trade_id for p in packages)}]",
        npv_paths=netted,
    )


@dataclass(frozen=True)
class CSA:
    """Collateral terms for a counterparty (a Credit Support Annex)."""

    threshold: float = 0.0          # exposure left uncollateralised below this level
    mta: float = 0.0                # minimum transfer amount
    mpor_days: int = 10             # margin period of risk (business days)
    margin_frequency: str = "daily"
    independent_amount: float = 0.0


def collateralise(pkg: ExposurePackage, csa: CSA, *, trade_id: str | None = None) -> ExposurePackage:
    """Return a package whose cube is the **residual** (collateralised) exposure max(V−C, 0).

    Variation margin tracks the MTM as of the last margin call (t − MPoR), subject to threshold/MTA;
    the residual is the close-out gap. The returned cube is exposure-valued (≥ 0), so it feeds
    CVA/FVA/EAD/PFE directly — but it no longer carries a negative side, so DVA is not meaningful on
    a collateralised package (a two-way CSA collateralises both directions).
    """
    eng = CSAEngine(
        threshold=csa.threshold, mta=csa.mta, mpor_days=csa.mpor_days,
        margin_frequency=csa.margin_frequency, independent_amount=csa.independent_amount,
    )
    residual = eng.compute_collateralised_exposure(pkg.npv_paths, pkg.time_grid)
    return replace(pkg, trade_id=trade_id or f"{pkg.trade_id}|csa", npv_paths=residual)


def wrong_way_ee(pkg: ExposurePackage, *, beta: float) -> NDArray[np.float64]:
    """Wrong-way-adjusted EE via an exponential tilt of the path measure.

    At each time the positive exposures are standardised across paths and re-weighted by
    ``exp(beta · z)`` (normalised to mean 1, so it stays a probability measure). ``beta > 0`` makes
    high-exposure paths more likely *given counterparty default* — wrong-way risk, which lifts EE and
    hence CVA; ``beta = 0`` returns the ordinary independent EE.
    """
    if beta == 0.0:
        return pkg.expected_exposure()
    pos = np.maximum(pkg.npv_paths, 0.0)
    z = (pos - pos.mean(axis=0)) / (pos.std(axis=0) + 1e-12)
    w = np.exp(beta * z)
    w /= w.mean(axis=0)  # renormalise per time so E[w] = 1
    return (pos * w).mean(axis=0)
