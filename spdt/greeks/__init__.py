"""L5 Greeks Engine: bump (CRN), pathwise, likelihood-ratio, and hand-rolled AAD."""

from spdt.greeks.aad import autocallable_aad_greeks, bs_vanilla_aad, call_aad_greeks
from spdt.greeks.bump import GreekSet, bump_greeks
from spdt.greeks.likelihood import lr_digital_delta
from spdt.greeks.pathwise import pathwise_vanilla
from spdt.greeks.reallocation import GreekReallocator, ReallocatedGreeks
from spdt.greeks.residual import ResidualGreekCalculator
from spdt.greeks.routing import DeskRouter, DeskRoutingSlip

__all__ = [
    "DeskRouter",
    "DeskRoutingSlip",
    "GreekReallocator",
    "GreekSet",
    "ReallocatedGreeks",
    "ResidualGreekCalculator",
    "autocallable_aad_greeks",
    "bs_vanilla_aad",
    "bump_greeks",
    "call_aad_greeks",
    "lr_digital_delta",
    "pathwise_vanilla",
]
