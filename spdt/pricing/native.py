"""Native MC kernel wrapper with a NumPy reference behind the same interface (L4).

The C++ kernel in ``cpp/mc_kernel`` is an *optional accelerator*: if it has been compiled
(``python cpp/build_kernel.py``) it is used; otherwise the identical algorithm runs in NumPy.
The point is the boundary — the same ``price_autocallable`` signature, two implementations, so
the "one product's hot loop is in C++; the rest is the same pattern" claim is real and the
speedup is measurable (see ``cpp/benchmark.py``). Both price a *struck* autocallable (levels as
fractions of the initial fixing) to match :class:`spdt.products.catalog.Autocallable`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:  # the compiled extension is optional
    from spdt.pricing import _spdt_mc  # type: ignore

    HAVE_NATIVE = True
except ImportError:  # pragma: no cover - depends on local build
    _spdt_mc = None
    HAVE_NATIVE = False


@dataclass(frozen=True)
class KernelResult:
    price: float
    std_error: float
    n_paths: int


def price_autocallable_reference(
    *, spot: float, r: float, q: float, sigma: float, obs_times: tuple[float, ...],
    notional: float, coupon_rate: float, autocall_level: float, coupon_barrier: float,
    knock_in: float, n_paths: int, seed: int,
) -> KernelResult:
    """Vectorised NumPy reference: the same path + payoff the C++ kernel computes."""
    obs = np.asarray(obs_times, dtype=float)
    dt = np.diff(np.concatenate(([0.0], obs)))
    drift = (r - q - 0.5 * sigma * sigma) * dt
    diffusion = sigma * np.sqrt(dt)
    disc = np.exp(-r * obs)
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n_paths, obs.size))
    log_s = np.log(spot) + np.cumsum(drift + diffusion * z, axis=1)
    ratio = np.exp(log_s) / spot  # S_t / S_0

    alive = np.ones(n_paths, dtype=bool)
    pv = np.zeros(n_paths)
    last = obs.size - 1
    for i in range(obs.size):
        rt = ratio[:, i]
        pv += disc[i] * (alive & (rt >= coupon_barrier)) * coupon_rate * notional
        if i < last:
            called = alive & (rt >= autocall_level)
            pv += disc[i] * called * notional
            alive = alive & ~called
        else:
            principal = np.where(rt <= knock_in, notional * rt, notional)
            pv += disc[i] * alive * principal
    mean = float(pv.mean())
    return KernelResult(mean, float(pv.std(ddof=0) / np.sqrt(n_paths)), n_paths)


def price_autocallable_python_loop(
    *, spot: float, r: float, q: float, sigma: float, obs_times: tuple[float, ...],
    notional: float, coupon_rate: float, autocall_level: float, coupon_barrier: float,
    knock_in: float, n_paths: int, seed: int,
) -> KernelResult:
    """A *pure-Python scalar* loop — the honest baseline the C++ port really competes with.

    NumPy is already compiled C under the hood, so C-vs-NumPy is a modest win; the dramatic
    speedup (and the actual reason a desk writes this in C++) is against an interpreted
    path-by-path loop like this one. Kept here so ``cpp/benchmark.py`` can quote that number.
    """
    import math

    obs = list(obs_times)
    prev = 0.0
    drift, diffusion, disc = [], [], []
    for t in obs:
        dt = t - prev
        prev = t
        drift.append((r - q - 0.5 * sigma * sigma) * dt)
        diffusion.append(sigma * math.sqrt(dt))
        disc.append(math.exp(-r * t))
    rng = np.random.default_rng(seed)
    last = len(obs) - 1
    total = 0.0
    for _ in range(n_paths):
        log_s = math.log(spot)
        alive = True
        pv = 0.0
        for i in range(len(obs)):
            log_s += drift[i] + diffusion[i] * rng.standard_normal()
            ratio = math.exp(log_s) / spot
            if alive and ratio >= coupon_barrier:
                pv += disc[i] * coupon_rate * notional
            if i < last:
                if alive and ratio >= autocall_level:
                    pv += disc[i] * notional
                    alive = False
            elif alive:
                principal = notional * ratio if ratio <= knock_in else notional
                pv += disc[i] * principal
        total += pv
    return KernelResult(total / n_paths, 0.0, n_paths)


def price_autocallable_native(
    *, spot: float, r: float, q: float, sigma: float, obs_times: tuple[float, ...],
    notional: float, coupon_rate: float, autocall_level: float, coupon_barrier: float,
    knock_in: float, n_paths: int, seed: int,
) -> KernelResult:
    """Call the compiled C++ kernel (raises if it was never built)."""
    if not HAVE_NATIVE:
        raise RuntimeError("native kernel not built; run `python cpp/build_kernel.py`")
    d = _spdt_mc.price_autocallable(
        spot, r, q, sigma, list(obs_times), notional, coupon_rate, autocall_level,
        coupon_barrier, knock_in, int(n_paths), int(seed),
    )
    return KernelResult(d["price"], d["std_error"], d["n_paths"])


def price_autocallable(*, backend: str = "auto", **kwargs) -> KernelResult:
    """Price via ``backend`` in {``"native"``, ``"reference"``, ``"auto"``} (auto prefers C++)."""
    if backend == "reference" or (backend == "auto" and not HAVE_NATIVE):
        return price_autocallable_reference(**kwargs)
    if backend in ("native", "auto"):
        return price_autocallable_native(**kwargs)
    raise ValueError(f"unknown backend {backend!r}")
