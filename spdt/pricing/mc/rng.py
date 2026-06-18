"""Random-number generation for Monte-Carlo path construction (L4).

Two engines: a pseudo-random generator (Mersenne/PCG via NumPy) with **antithetic variates**
for variance reduction and reproducible Greeks, and a **Sobol** low-discrepancy sequence
(inverse-CDF mapped) for faster convergence of the main estimate. Brownian-bridge ordering
of the Sobol dimensions is a later refinement.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.special import ndtri
from scipy.stats.qmc import Sobol


def standard_normals(
    n_paths: int,
    n_steps: int,
    *,
    antithetic: bool = True,
    seed: int = 0,
    method: str = "pseudo",
) -> NDArray[np.float64]:
    """Return an ``(n_paths, n_steps)`` array of standard-normal draws."""
    if method == "sobol":
        # Map a scrambled Sobol sequence through the inverse normal CDF.
        u = Sobol(d=n_steps, scramble=True, seed=seed).random(n_paths)
        u = np.clip(u, 1e-12, 1.0 - 1e-12)
        return ndtri(u)

    if method != "pseudo":
        raise ValueError(f"unknown RNG method {method!r}")

    rng = np.random.default_rng(seed)
    if not antithetic:
        return rng.standard_normal((n_paths, n_steps))
    if n_paths % 2:
        raise ValueError("antithetic sampling requires an even n_paths")
    half = rng.standard_normal((n_paths // 2, n_steps))
    return np.concatenate([half, -half], axis=0)
