"""Curve adapter — make a SPDT ``Curve`` satisfy XVA's ``OISCurve`` interface (ADR-0007).

Both sides discount in year-fraction space: SPDT ``Curve.df(tau)`` and XVA ``OISCurve.df(t)`` map
time-in-years → discount factor with identical semantics. This adapter wraps one bootstrapped SPDT
curve so it can be handed straight to ``CVAEngine(ois_curve)`` and the rest of the XVA stack — one
curve, two consumers, no re-bootstrap. `df(t)` is the hot path; `tenors`/`rates` are exposed so
XVA's IR01 sensitivity (which rebuilds a bumped ``OISCurve`` from pillars) also works.
"""

from __future__ import annotations

from math import log
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    from spdt.core.types import Curve


class SpdtCurveAsOIS:
    """Adapt a SPDT :class:`~spdt.core.types.Curve` to the XVA ``OISCurve`` consumer interface."""

    def __init__(self, curve: "Curve") -> None:
        self._curve = curve
        # Pillar tenors (year fractions from the anchor) and the implied continuous zero rates —
        # what XVA's sensitivity path reads off to rebuild a bumped curve.
        from spdt.core.types import year_fraction  # local import: avoid a hard import-time dep

        dfs = curve.discount_factors or {}
        pillars = sorted(year_fraction(curve.anchor, d) for d in dfs)
        self.tenors: NDArray[np.float64] = np.array(pillars, dtype=float)
        self.rates: NDArray[np.float64] = np.array([self.zero_rate(t) for t in pillars], dtype=float)

    # --- the OISCurve surface XVA actually calls -----------------------------------------
    def df(self, t: float) -> float:
        """Discount factor at year-fraction ``t`` — delegates to the wrapped SPDT curve."""
        return self._curve.df(t)

    def df_array(self, t_array: NDArray[np.float64]) -> NDArray[np.float64]:
        return np.array([self._curve.df(float(t)) for t in t_array], dtype=float)

    def zero_rate(self, t: float) -> float:
        """Continuously-compounded zero rate ``z(t) = -ln D(t) / t``."""
        if t <= 0.0:
            return 0.0
        return -log(self._curve.df(t)) / t
