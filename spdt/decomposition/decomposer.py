"""Risk Decomposition Engine: dispatch any product to its typed risk components.

A structured product enters the engine as an opaque :class:`~spdt.products.graph.Product`;
it leaves as a :class:`Decomposition` — a typed list of :class:`RiskComponent` objects, each
tagged with its hedge strategy, discount leg, and (where the decomposition is exact) a
standalone :class:`Product` primitive for independent pricing.

The engine uses a **registry pattern**: product types register their decomposition strategy
at import time.  Adding a new product (e.g. a Snowball) requires only writing a new strategy
and calling ``engine.register(Snowball, decompose_snowball)``; the engine itself is closed to
modification.

Two classes of decomposition:

* **Exact** (``is_exact=True``): the sum of component PVs equals the product PV on every
  path (BRC, RC, CPN).  These mirror the existing ``legs.py`` composition, now typed.
* **Approximate** (``is_exact=False``): the components are a *risk decomposition* — they
  identify the hedgeable risks but their sum may differ from the exact product PV because
  of path-dependent interactions (autocallable, worst-of).  The pricing still happens
  through the full MC on the monolithic product; the decomposition tells the replication
  engine *what to hedge*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from spdt.decomposition.components import RiskComponent
from spdt.products.graph import Product


@dataclass(frozen=True)
class Decomposition:
    """The result of decomposing a structured product into risk components."""

    product_type: str
    components: tuple[RiskComponent, ...]
    is_exact: bool  # True if sum of component PVs = product PV exactly
    notes: str = ""  # human-readable notes on the decomposition

    @property
    def component_types(self) -> tuple[str, ...]:
        """Unique component type tags present in the decomposition."""
        return tuple(sorted({c.component_type for c in self.components}))

    @property
    def hedge_strategies(self) -> tuple[str, ...]:
        """Unique hedge strategies required."""
        return tuple(sorted({c.hedge_strategy for c in self.components}))

    def by_type(self, component_type: str) -> tuple[RiskComponent, ...]:
        """Filter components by type tag."""
        return tuple(c for c in self.components if c.component_type == component_type)

    def by_strategy(self, strategy: str) -> tuple[RiskComponent, ...]:
        """Filter components by hedge strategy."""
        return tuple(c for c in self.components if c.hedge_strategy == strategy)

    @property
    def total_notional(self) -> float:
        """Sum of absolute component notionals — a rough measure of hedge complexity."""
        return sum(abs(c.notional) for c in self.components)


# Type alias for decomposer callables.
# Concrete decomposers intentionally narrow their argument to the product type registered beside
# them. The runtime registry performs that type dispatch before calling one.
Decomposer = Callable[[Any], Decomposition]


class RiskDecompositionEngine:
    """Registry-based dispatcher: product type → decomposer → Decomposition.

    Usage::

        engine = RiskDecompositionEngine()
        engine.register(Autocallable, decompose_autocallable)
        engine.register(BarrierReverseConvertible, decompose_brc)

        result = engine.decompose(some_autocallable)
        for c in result.components:
            print(c.component_type, c.hedge_strategy)

    The registry is deliberately a plain dict rather than a class hierarchy on the products
    themselves, so that decomposers live in ``spdt.decomposition.strategies`` — separate from
    the product definitions — and can be swapped or extended without touching the product code.
    """

    def __init__(self) -> None:
        self._registry: dict[type, Decomposer] = {}

    def register(self, product_type: type, decomposer: Decomposer) -> None:
        """Register a decomposer for a product type."""
        self._registry[product_type] = decomposer

    def can_decompose(self, product: Product) -> bool:
        """Check whether a decomposer is registered for this product's type."""
        return type(product) in self._registry

    def decompose(self, product: Product) -> Decomposition:
        """Decompose a product into its risk components.

        Raises :class:`TypeError` if no decomposer is registered for the product's type.
        """
        decomposer = self._registry.get(type(product))
        if decomposer is None:
            raise TypeError(
                f"No decomposer registered for {type(product).__name__}. "
                f"Registered types: {[t.__name__ for t in self._registry]}"
            )
        return decomposer(product)

    @property
    def registered_types(self) -> list[str]:
        """Names of all product types with registered decomposers."""
        return [t.__name__ for t in self._registry]


def _default_engine() -> RiskDecompositionEngine:
    """Build the default engine with all catalog decomposers registered.

    Called lazily on first use of :func:`decompose` so that imports are deferred and the
    strategies can reference the catalog without circular import issues.
    """
    from spdt.decomposition.strategies.autocallable import decompose_autocallable
    from spdt.decomposition.strategies.brc import decompose_brc
    from spdt.decomposition.strategies.capital_protected import decompose_capital_protected
    from spdt.decomposition.strategies.reverse_convertible import decompose_reverse_convertible
    from spdt.decomposition.strategies.worst_of import decompose_worst_of
    from spdt.products.catalog import (
        Autocallable,
        BarrierReverseConvertible,
        CapitalProtectedNote,
        ReverseConvertible,
        WorstOfAutocallable,
    )

    engine = RiskDecompositionEngine()
    engine.register(Autocallable, decompose_autocallable)
    engine.register(BarrierReverseConvertible, decompose_brc)
    engine.register(CapitalProtectedNote, decompose_capital_protected)
    engine.register(ReverseConvertible, decompose_reverse_convertible)
    engine.register(WorstOfAutocallable, decompose_worst_of)
    return engine


_ENGINE: RiskDecompositionEngine | None = None


def get_engine() -> RiskDecompositionEngine:
    """Return the singleton default decomposition engine (lazily initialised)."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = _default_engine()
    return _ENGINE


def decompose(product: Product) -> Decomposition:
    """Convenience: decompose a product using the default engine."""
    return get_engine().decompose(product)
