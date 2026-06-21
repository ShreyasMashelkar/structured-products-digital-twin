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
from integration.curve_adapter import SpdtCurveAsOIS  # noqa: E402
from integration.exposure_export import (  # noqa: E402
    autocallable_exposure,
    european_exposure,
    mark_to_future_european,
    note_exposure,
    worst_of_exposure,
)
from integration.exposure_package import ExposurePackage  # noqa: E402

__all__ = [
    "ExposurePackage",
    "SpdtCurveAsOIS",
    "autocallable_exposure",
    "european_exposure",
    "mark_to_future_european",
    "note_exposure",
    "solve_coupon_all_in",
    "worst_of_exposure",
    "xva_charge",
]
