"""Model-risk reserves: money you can't book because you don't trust the model that far (L11).

Three reserves a model-validation seat computes:

* **Model reserve** = price under one model minus another for the *same* product. LV and LSV
  agree on vanillas (they share the marginal distributions) but disagree on forward-smile-
  sensitive exotics like autocallables (they differ in dynamics) — that gap is real money the
  desk reserves against using the "wrong" model. The gap function is generic; wiring in the
  LSV and LV prices awaits the advanced pricing models.
* **Parameter-uncertainty reserve**: reprice across a calibration confidence region; the
  reserve is the spread of resulting prices.
* **Bid-offer reserve**: price at the bid and offer marks of a risk factor; the reserve is
  half that price spread (the cost of crossing to unwind).
"""

from __future__ import annotations

import dataclasses
from typing import Callable

from spdt.pricing.engine import price_mc
from spdt.pricing.models import BlackScholes
from spdt.products.graph import Product


def model_gap_reserve(price_a: float, price_b: float) -> float:
    """Reserve for model choice on one product — e.g. ``|LSV − LV|`` for an autocallable."""
    return abs(price_a - price_b)


def parameter_uncertainty_reserve(prices: list[float]) -> float:
    """Half the price spread across a calibration confidence region."""
    if not prices:
        raise ValueError("need at least one price")
    return 0.5 * (max(prices) - min(prices))


def vol_bid_offer_reserve(
    product: Product,
    model: BlackScholes,
    vol_half_spread: float,
    *,
    n_paths: int = 100_000,
    seed: int = 0,
) -> float:
    """Bid-offer reserve from the vol mark's half-spread, repriced under CRN.

    Prices the product at ``σ ± vol_half_spread`` and takes half the resulting price spread —
    the model-independent cost of unwinding across the volatility bid-offer.
    """

    def pv(sigma: float) -> float:
        return price_mc(
            product, dataclasses.replace(model, sigma=sigma), n_paths=n_paths, seed=seed
        ).price

    return 0.5 * abs(pv(model.sigma + vol_half_spread) - pv(model.sigma - vol_half_spread))


def total_reserve(*reserves: float) -> float:
    """Sum component reserves (held additively, the conservative convention)."""
    return sum(abs(r) for r in reserves)


def reserve_from_scenarios(
    price_fn: Callable[[float], float], param_scenarios: list[float]
) -> float:
    """Parameter-uncertainty reserve given a repricing function and parameter scenarios."""
    return parameter_uncertainty_reserve([price_fn(p) for p in param_scenarios])
