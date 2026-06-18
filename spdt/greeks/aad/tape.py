"""A tiny scalar reverse-mode autodiff tape (L5).

The minimal machinery behind AAD: a ``Var`` records its value and, for each operation, the
local derivatives with respect to its inputs. A single reverse sweep over the recorded graph
then accumulates the adjoint of every input. This is hand-rolled deliberately — to own the
adjoint — rather than pulled from a framework; JAX would provide the same over the full MC
graph at breadth.
"""

from __future__ import annotations

from math import erf, exp, log, pi
from math import sqrt as _sqrt

_INV_SQRT_2PI = 1.0 / _sqrt(2.0 * pi)


class Var:
    """A node on the reverse-mode tape: a value plus how it was computed."""

    __slots__ = ("value", "_parents", "grad")

    def __init__(self, value: float, parents: tuple[tuple["Var", float], ...] = ()) -> None:
        self.value = float(value)
        self._parents = parents  # (parent, local ∂self/∂parent) pairs
        self.grad = 0.0

    def __add__(self, other: "Var | float") -> "Var":
        o = other if isinstance(other, Var) else Var(other)
        return Var(self.value + o.value, ((self, 1.0), (o, 1.0)))

    __radd__ = __add__

    def __sub__(self, other: "Var | float") -> "Var":
        o = other if isinstance(other, Var) else Var(other)
        return Var(self.value - o.value, ((self, 1.0), (o, -1.0)))

    def __rsub__(self, other: "Var | float") -> "Var":
        o = other if isinstance(other, Var) else Var(other)
        return o.__sub__(self)

    def __mul__(self, other: "Var | float") -> "Var":
        o = other if isinstance(other, Var) else Var(other)
        return Var(self.value * o.value, ((self, o.value), (o, self.value)))

    __rmul__ = __mul__

    def __truediv__(self, other: "Var | float") -> "Var":
        o = other if isinstance(other, Var) else Var(other)
        return Var(self.value / o.value, ((self, 1.0 / o.value), (o, -self.value / o.value**2)))


def v_exp(x: Var) -> Var:
    val = exp(x.value)
    return Var(val, ((x, val),))


def v_log(x: Var) -> Var:
    return Var(log(x.value), ((x, 1.0 / x.value),))


def v_sqrt(x: Var) -> Var:
    val = _sqrt(x.value)
    return Var(val, ((x, 0.5 / val),))


def v_norm_cdf(x: Var) -> Var:
    val = 0.5 * (1.0 + erf(x.value / _sqrt(2.0)))
    pdf = _INV_SQRT_2PI * exp(-0.5 * x.value * x.value)
    return Var(val, ((x, pdf),))


def backward(output: Var) -> None:
    """Topologically order the tape and accumulate adjoints back from ``output``."""
    topo: list[Var] = []
    seen: set[int] = set()

    def visit(node: Var) -> None:
        if id(node) in seen:
            return
        seen.add(id(node))
        for parent, _ in node._parents:
            visit(parent)
        topo.append(node)

    visit(output)
    output.grad = 1.0
    for node in reversed(topo):
        for parent, local in node._parents:
            parent.grad += node.grad * local
