"""Bump-and-revalue Greeks with common random numbers (L5).

The cheapest, most general estimator: re-price the product under perturbed inputs and take
central differences. The essential trick is **common random numbers (CRN)** — every bump
reuses the *same* random draws (here via a fixed ``seed``), so the Monte-Carlo noise cancels
in the difference and the estimate is stable. Without CRN, the bump difference is dominated
by sampling noise and second-order Greeks (gamma) are unusable.

Works for any :class:`~spdt.products.graph.Product` under any model with the bumped fields;
the model is perturbed immutably via ``dataclasses.replace``.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from spdt.pricing.engine import price_mc
from spdt.pricing.models import BlackScholes
from spdt.products.graph import Product


@dataclass(frozen=True)
class GreekSet:
    """First- and second-order Greeks of a position (per unit of the underlying input)."""

    delta: float  # ∂PV/∂S
    gamma: float  # ∂²PV/∂S²
    vega: float  # ∂PV/∂σ  (per unit vol, i.e. per 100 vol points)
    rho: float  # ∂PV/∂r


def bump_greeks(
    product: Product,
    model: BlackScholes,
    *,
    n_paths: int = 200_000,
    seed: int = 0,
    rel_spot_bump: float = 1e-2,
    vol_bump: float = 1e-2,
    rate_bump: float = 1e-4,
) -> GreekSet:
    """Central-difference Greeks under CRN (same ``seed`` for every revaluation)."""

    def pv(m: BlackScholes) -> float:
        return price_mc(product, m, n_paths=n_paths, seed=seed).price

    h_s = model.spot * rel_spot_bump
    base = pv(model)
    up_s = pv(dataclasses.replace(model, spot=model.spot + h_s))
    dn_s = pv(dataclasses.replace(model, spot=model.spot - h_s))
    up_v = pv(dataclasses.replace(model, sigma=model.sigma + vol_bump))
    dn_v = pv(dataclasses.replace(model, sigma=model.sigma - vol_bump))
    up_r = pv(dataclasses.replace(model, r=model.r + rate_bump))
    dn_r = pv(dataclasses.replace(model, r=model.r - rate_bump))

    return GreekSet(
        delta=(up_s - dn_s) / (2 * h_s),
        gamma=(up_s - 2 * base + dn_s) / (h_s * h_s),
        vega=(up_v - dn_v) / (2 * vol_bump),
        rho=(up_r - dn_r) / (2 * rate_bump),
    )
