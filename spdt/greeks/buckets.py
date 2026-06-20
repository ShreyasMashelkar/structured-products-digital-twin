"""Bucketed vega: the vega ladder a desk actually risk-manages (L5).

Flat vega — one number from a parallel shift of the whole surface — hides *where* the vol risk
sits. A desk hedges vega per maturity bucket, because a 1y autocallable and a 3y one buy vol in
different parts of the term structure and trade against different listed options. This computes
``∂PV/∂σ_bucket`` for each knot of a :class:`TermVolBlackScholes` term structure by a CRN
central bump of that knot alone.
"""

from __future__ import annotations

from spdt.pricing.engine import price_mc
from spdt.pricing.models.term_vol import TermVolBlackScholes
from spdt.products.graph import Discount, Product


def bucketed_vega(
    product: Product,
    model: TermVolBlackScholes,
    *,
    n_paths: int = 200_000,
    seed: int = 0,
    vol_bump: float = 1e-2,
    discount: Discount | None = None,
) -> dict[float, float]:
    """``∂PV/∂σ`` per term-structure bucket (keyed by the bucket's knot tenor), under CRN."""
    ladder: dict[float, float] = {}
    for b, tk in enumerate(model.knot_times):
        up = price_mc(product, model.bumped(b, vol_bump), n_paths=n_paths, seed=seed, discount=discount).price
        dn = price_mc(product, model.bumped(b, -vol_bump), n_paths=n_paths, seed=seed, discount=discount).price
        ladder[tk] = (up - dn) / (2.0 * vol_bump)
    return ladder
