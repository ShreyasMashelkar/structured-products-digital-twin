"""Credit-curve construction at the seam (ADR-0007).

The flat :class:`CreditCurve` (one CDS spread → one hazard rate) is enough for a quote, but a real
counterparty trades a *term structure* of CDS. ``term_structure_credit_curve`` bootstraps a piecewise
hazard curve from CDS tenors/spreads against the SPDT-sourced OIS curve, and hands back an object with
the **same interface** as the flat curve (``default_probability`` / ``cumulative_default_probability``
/ ``survival_probability`` / ``lgd`` / ``shift``) — so it drops straight into ``xva_charge``,
``economic_capital`` and the governance gate with no other change.
"""

from __future__ import annotations

from typing import Sequence

from integration.curve_adapter import SpdtCurveAsOIS
from src.xva.cva import TermStructureCreditCurve, build_credit_curve_from_cds  # type: ignore


def term_structure_credit_curve(
    tenors: Sequence[float],
    cds_spreads_bps: Sequence[float],
    *,
    recovery_rate: float = 0.40,
    ois_curve: SpdtCurveAsOIS,
) -> "TermStructureCreditCurve":
    """Bootstrap a term-structure credit curve from CDS quotes against a SPDT OIS curve.

    Args:
        tenors: CDS pillar tenors in years (e.g. ``[0.5, 1, 3, 5]``).
        cds_spreads_bps: par CDS spreads at those tenors, in basis points.
        recovery_rate: assumed recovery on default.
        ois_curve: the discount curve (the same adapted SPDT curve the rest of the seam uses).
    """
    if len(tenors) != len(cds_spreads_bps):
        raise ValueError("tenors and cds_spreads_bps must be the same length")
    return build_credit_curve_from_cds(
        list(tenors), list(cds_spreads_bps), recovery_rate, ois_curve
    )
