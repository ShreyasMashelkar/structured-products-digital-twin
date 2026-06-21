"""SPDT ↔ XVA integration layer (ADR-0007).

The *only* package allowed to import across both worlds: SPDT (`spdt.*`) and the vendored XVA
engine (`xva/src/*`, imported as `src.*`). Importing this package puts `xva/` on ``sys.path`` so
the XVA modules resolve, then re-exports the seam: the curve adapter and the `ExposurePackage`
contract. Integration is confined to the exposure → XVA → price seam; the two product models stay
independent.
"""

from __future__ import annotations

import sys
from pathlib import Path

# XVA uses `src.`-prefixed internal imports, so its import root is the `xva/` directory.
_XVA_ROOT = Path(__file__).resolve().parent.parent / "xva"
if _XVA_ROOT.is_dir() and str(_XVA_ROOT) not in sys.path:
    sys.path.insert(0, str(_XVA_ROOT))

from integration.all_in_price import solve_coupon_all_in, xva_charge  # noqa: E402
from integration.ccr_overlays import (  # noqa: E402
    CSA,
    collateralise,
    initial_margin_profile,
    netting_set_exposure,
    wrong_way_ee,
)
from integration.credit import term_structure_credit_curve  # noqa: E402
from integration.curve_adapter import SpdtCurveAsOIS  # noqa: E402
from integration.exposure_export import (  # noqa: E402
    autocallable_exposure,
    european_exposure,
    mark_to_future_european,
    note_exposure,
    worst_of_exposure,
)
from integration.exposure_package import ExposurePackage  # noqa: E402
from integration.governance import (  # noqa: E402
    GovernanceGate,
    economic_capital,
    exposure_metrics,
)
from integration.xva_risk import (  # noqa: E402
    cva_cs01,
    saccr_ead_equity,
    stress_xva,
    xva_sensitivities,
)

# Re-export the one XVA input type callers must construct to cross the seam (the counterparty credit
# curve), so consumers depend only on `integration` — keeping it the sole cross-world importer.
from src.xva.cva import CreditCurve  # type: ignore  # noqa: E402  # resolved via the sys.path insert above

__all__ = [
    "CSA",
    "CreditCurve",
    "ExposurePackage",
    "GovernanceGate",
    "SpdtCurveAsOIS",
    "autocallable_exposure",
    "collateralise",
    "cva_cs01",
    "economic_capital",
    "european_exposure",
    "exposure_metrics",
    "initial_margin_profile",
    "mark_to_future_european",
    "netting_set_exposure",
    "note_exposure",
    "saccr_ead_equity",
    "solve_coupon_all_in",
    "stress_xva",
    "term_structure_credit_curve",
    "worst_of_exposure",
    "wrong_way_ee",
    "xva_charge",
    "xva_sensitivities",
]
