"""
Self-contained reverse-mode automatic differentiation (AAD) engine.

This is a minimal tape-based reverse-mode autodiff framework written in pure
NumPy — no JAX/PyTorch dependency. It is the same technique (Adjoint Algorithmic
Differentiation) that every Tier-1 bank uses to compute thousands of XVA
sensitivities in a single reverse sweep, instead of bumping each input and
re-valuing (which costs one revaluation per sensitivity).

Why AAD matters for XVA:
    A CVA depends on hundreds of inputs — every node of the exposure profile,
    each credit spread, each discount factor, recovery, vol, etc. Bump-and-
    revalue needs N forward valuations for N Greeks. AAD gets the *entire*
    gradient vector in roughly the cost of ONE valuation by propagating
    adjoints backward through the computation tree.

References:
    - Giles & Glasserman (2006), "Smoking Adjoints: fast Monte Carlo Greeks"
    - Capriotti (2011), "Fast Greeks by Algorithmic Differentiation"
    - Andreasen, "CVA on an iPad Mini" (adjoint XVA)

Supported: scalars and 1-D NumPy arrays, with the operations required to
express CVA/exposure analytics (+, -, *, /, exp, log, sqrt, sum, dot,
maximum with a constant, array indexing via slicing helpers).
"""

import numpy as np
from typing import Union, List, Callable

Number = Union[float, int, np.ndarray]


class Var:
    """
    A node in the autodiff computation tape.

    Wraps a value (scalar or ndarray) and records the local vector-Jacobian
    products (VJPs) needed to backpropagate adjoints to its parents.
    """

    __slots__ = ("value", "grad", "_backward", "_parents")

    def __init__(self, value: Number, parents: tuple = (), backward: Callable = None):
        self.value = np.asarray(value, dtype=float)
        self.grad = np.zeros_like(self.value)
        self._backward = backward if backward is not None else (lambda: None)
        self._parents = parents

    # ── helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _ensure(x) -> "Var":
        return x if isinstance(x, Var) else Var(x)

    @staticmethod
    def _unbroadcast(grad: np.ndarray, shape: tuple) -> np.ndarray:
        """Sum a gradient back down to `shape` after NumPy broadcasting."""
        g = grad
        # collapse extra leading dims
        while g.ndim > len(shape):
            g = g.sum(axis=0)
        # collapse broadcasted (size-1) dims
        for i, s in enumerate(shape):
            if s == 1 and g.shape[i] != 1:
                g = g.sum(axis=i, keepdims=True)
        return g.reshape(shape)

    # ── arithmetic ───────────────────────────────────────────────────────
    def __add__(self, other):
        other = self._ensure(other)
        out = Var(self.value + other.value, (self, other))

        def _bw():
            self.grad = self.grad + self._unbroadcast(out.grad, self.value.shape)
            other.grad = other.grad + self._unbroadcast(out.grad, other.value.shape)
        out._backward = _bw
        return out

    __radd__ = __add__

    def __sub__(self, other):
        return self + (-self._ensure(other))

    def __rsub__(self, other):
        return self._ensure(other) + (-self)

    def __neg__(self):
        out = Var(-self.value, (self,))

        def _bw():
            self.grad = self.grad - out.grad
        out._backward = _bw
        return out

    def __mul__(self, other):
        other = self._ensure(other)
        out = Var(self.value * other.value, (self, other))

        def _bw():
            self.grad = self.grad + self._unbroadcast(out.grad * other.value, self.value.shape)
            other.grad = other.grad + self._unbroadcast(out.grad * self.value, other.value.shape)
        out._backward = _bw
        return out

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = self._ensure(other)
        out = Var(self.value / other.value, (self, other))

        def _bw():
            self.grad = self.grad + self._unbroadcast(out.grad / other.value, self.value.shape)
            other.grad = other.grad + self._unbroadcast(
                -out.grad * self.value / (other.value ** 2), other.value.shape)
        out._backward = _bw
        return out

    def __rtruediv__(self, other):
        return self._ensure(other) / self

    # ── unary math ───────────────────────────────────────────────────────
    def exp(self):
        out = Var(np.exp(self.value), (self,))

        def _bw():
            self.grad = self.grad + out.grad * out.value
        out._backward = _bw
        return out

    def log(self):
        out = Var(np.log(self.value), (self,))

        def _bw():
            self.grad = self.grad + out.grad / self.value
        out._backward = _bw
        return out

    def sqrt(self):
        out = Var(np.sqrt(self.value), (self,))

        def _bw():
            self.grad = self.grad + out.grad * 0.5 / (out.value + 1e-300)
        out._backward = _bw
        return out

    # ── reductions / vector ops ──────────────────────────────────────────
    def sum(self):
        out = Var(self.value.sum(), (self,))

        def _bw():
            self.grad = self.grad + out.grad * np.ones_like(self.value)
        out._backward = _bw
        return out

    def dot(self, other):
        other = self._ensure(other)
        out = Var(np.dot(self.value, other.value), (self, other))

        def _bw():
            self.grad = self.grad + out.grad * other.value
            other.grad = other.grad + out.grad * self.value
        out._backward = _bw
        return out

    def maximum0(self):
        """Element-wise max(x, 0) — for positive-exposure (EE) construction."""
        mask = (self.value > 0).astype(float)
        out = Var(self.value * mask, (self,))

        def _bw():
            self.grad = self.grad + out.grad * mask
        out._backward = _bw
        return out

    # ── slicing helpers (return plain Var views via gather) ──────────────
    def slice_to(self, sl: slice):
        out = Var(self.value[sl], (self,))

        def _bw():
            g = np.zeros_like(self.value)
            g[sl] = out.grad
            self.grad = self.grad + g
        out._backward = _bw
        return out

    # ── backward pass ────────────────────────────────────────────────────
    def backward(self):
        """Reverse-mode sweep: seed this node's adjoint with 1 and propagate."""
        topo: List[Var] = []
        visited = set()

        def build(v: "Var"):
            if id(v) in visited:
                return
            visited.add(id(v))
            for p in v._parents:
                build(p)
            topo.append(v)

        build(self)
        # seed
        self.grad = np.ones_like(self.value)
        for v in reversed(topo):
            v._backward()


def var(value: Number) -> Var:
    """Convenience constructor for a leaf input node."""
    return Var(value)
