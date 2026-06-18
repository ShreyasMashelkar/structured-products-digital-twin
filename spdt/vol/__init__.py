"""L2 Volatility Analytics: SVI calibration, arbitrage checks, the queryable VolSurface."""

from spdt.vol.arbitrage import ArbReport, check_butterfly, check_calendar, check_slices, durrleman_g
from spdt.vol.surface import VolSurface, with_surfaces
from spdt.vol.svi import SVIParams, calibrate_svi, total_variance_from_iv

__all__ = [
    "ArbReport",
    "SVIParams",
    "VolSurface",
    "calibrate_svi",
    "check_butterfly",
    "check_calendar",
    "check_slices",
    "durrleman_g",
    "total_variance_from_iv",
    "with_surfaces",
]
