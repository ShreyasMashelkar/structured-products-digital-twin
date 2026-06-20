"""A vectorised reverse-mode AD tape over NumPy arrays (L5).

The scalar tape in :mod:`spdt.greeks.aad.tape` proves the adjoint mechanism on a single
Black-Scholes formula. This module scales the *same* idea to the Monte-Carlo graph: a
:class:`Node` carries an array value (one entry per path) and, for each operation, the local
derivative w.r.t. each input. One reverse sweep then accumulates the adjoint of every input —
so a single backward pass over ``mean(discounted payoff)`` yields the pathwise delta and vega
of the whole simulation at once, independent of the number of inputs. That is exactly the AAD
cost claim, demonstrated on the flagship autocallable rather than a vanilla.

Because reverse-mode AD of an MC payoff differentiates the payoff *along each path*, the
gradient it produces is precisely the **pathwise estimator** — unbiased for the smooth part of
the payoff, and (like any pathwise method) blind to the Dirac contributions at barrier/autocall
discontinuities. AAD is the *mechanism*; pathwise is the *estimator* it computes.
"""

from __future__ import annotations

from typing import Union

import numpy as np
from numpy.typing import NDArray

Number = Union[float, NDArray[np.float64]]


def _unbroadcast(grad: NDArray[np.float64], shape: tuple[int, ...]) -> Number:
    """Sum ``grad`` back down to ``shape`` so adjoints respect NumPy broadcasting."""
    if shape == ():
        return float(np.sum(grad))
    while grad.ndim > len(shape):
        grad = grad.sum(axis=0)
    for axis, size in enumerate(shape):
        if size == 1 and grad.shape[axis] != 1:
            grad = grad.sum(axis=axis, keepdims=True)
    return grad


class Node:
    """A taped value: an array (or scalar) plus how it was computed."""

    __slots__ = ("value", "_parents", "grad")

    def __init__(self, value: Number, parents: tuple[tuple["Node", Number], ...] = ()) -> None:
        self.value = np.asarray(value, dtype=float)
        self._parents = parents  # (parent, local ∂self/∂parent) pairs
        self.grad = np.zeros_like(self.value)

    @staticmethod
    def _coerce(x: "Node | Number") -> "Node":
        return x if isinstance(x, Node) else Node(x)

    def __add__(self, other: "Node | Number") -> "Node":
        o = self._coerce(other)
        return Node(self.value + o.value, ((self, 1.0), (o, 1.0)))

    __radd__ = __add__

    def __sub__(self, other: "Node | Number") -> "Node":
        o = self._coerce(other)
        return Node(self.value - o.value, ((self, 1.0), (o, -1.0)))

    def __rsub__(self, other: "Node | Number") -> "Node":
        return self._coerce(other).__sub__(self)

    def __mul__(self, other: "Node | Number") -> "Node":
        o = self._coerce(other)
        return Node(self.value * o.value, ((self, o.value), (o, self.value)))

    __rmul__ = __mul__

    def __truediv__(self, other: "Node | Number") -> "Node":
        o = self._coerce(other)
        return Node(self.value / o.value, ((self, 1.0 / o.value), (o, -self.value / o.value**2)))

    def __neg__(self) -> "Node":
        return Node(-self.value, ((self, -1.0),))


def v_exp(x: Node) -> Node:
    val = np.exp(x.value)
    return Node(val, ((x, val),))


def v_maximum(x: Node, other: "Node | Number") -> Node:
    """Elementwise ``max(x, other)`` — the kink's subgradient is the in-the-money indicator."""
    o = Node._coerce(other)
    mask = (x.value >= o.value).astype(float)
    return Node(np.maximum(x.value, o.value), ((x, mask), (o, 1.0 - mask)))


def v_sum_mean(x: Node) -> Node:
    """Mean over paths (the MC estimator); local derivative is ``1/n`` to every path."""
    n = x.value.size
    return Node(float(np.mean(x.value)), ((x, np.full(x.value.shape, 1.0 / n)),))


def backward(output: Node) -> None:
    """Reverse-accumulate adjoints from a scalar ``output`` over the taped graph."""
    topo: list[Node] = []
    seen: set[int] = set()

    def visit(node: Node) -> None:
        if id(node) in seen:
            return
        seen.add(id(node))
        for parent, _ in node._parents:
            visit(parent)
        topo.append(node)

    visit(output)
    output.grad = np.ones_like(output.value)
    for node in reversed(topo):
        for parent, local in node._parents:
            contrib = node.grad * np.asarray(local, dtype=float)
            parent.grad = np.asarray(parent.grad) + _unbroadcast(contrib, parent.grad.shape)
