"""L2 Volatility Analytics: SVI calibration, arbitrage checks, the queryable VolSurface."""

from spdt.vol.arbitrage import ArbReport, check_butterfly, check_calendar, check_slices, durrleman_g
from spdt.vol.forward_smile import (
    forward_atm_vol,
    forward_implied_vol,
    forward_smile,
    forward_total_variance,
)
from spdt.vol.localvol import dupire_local_variance, dupire_local_vol
from spdt.vol.ssvi import SSVISurface
from spdt.vol.stickiness import StickyRegime, atm_vol_under_move, skew_delta_adjustment
from spdt.vol.surface import VolSurface, with_surfaces
from spdt.vol.svi import SVIParams, calibrate_svi, total_variance_from_iv

__all__ = [
    "ArbReport",
    "SSVISurface",
    "SVIParams",
    "StickyRegime",
    "VolSurface",
    "atm_vol_under_move",
    "calibrate_svi",
    "check_butterfly",
    "check_calendar",
    "check_slices",
    "dupire_local_variance",
    "dupire_local_vol",
    "durrleman_g",
    "forward_atm_vol",
    "forward_implied_vol",
    "forward_smile",
    "forward_total_variance",
    "skew_delta_adjustment",
    "total_variance_from_iv",
    "with_surfaces",
]
