"""MC discretisation schemes — centralisation placeholder (scope contract: intentional).

The schemes the engine actually uses live *with their models*, not here:

* exact lognormal GBM stepping — :mod:`spdt.pricing.models.bs`
* log-Euler local vol — :mod:`spdt.pricing.models.localvol`
* Andersen **QE** scheme for the Heston/LSV variance — :mod:`spdt.pricing.models.heston`
  and :mod:`spdt.pricing.models.lsv` (see ADR-0004)

This module is a deliberately-empty placeholder for a future refactor that would centralise
the stepping logic; it exposes nothing today so importing it is a no-op rather than a silent
half-feature.
"""

from __future__ import annotations
