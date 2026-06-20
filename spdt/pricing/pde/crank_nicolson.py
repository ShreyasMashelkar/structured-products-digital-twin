"""Crank–Nicolson PDE pricer for low-dimensional payoffs (L4).

The backward Black-Scholes / local-vol PDE

    V_t + ½σ(S,t)² S² V_SS + (r−q) S V_S − r V = 0,   V(S, T) = payoff(S)

solved on a uniform spot grid by the **Crank–Nicolson** scheme (θ = ½: second-order in time,
unconditionally stable, no oscillation for smooth data). Each time step is a tridiagonal solve
(``scipy.linalg.solve_banded``). This is the desk's PDE engine for 1-D products — vanillas and
single barriers — and an *independent* cross-check on the Monte-Carlo price (different
numerical method, same model), exactly the agreement model validation asks for.

Curse of dimensionality keeps PDE to 1–2 factors; baskets/autocallables stay on MC.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
from numpy.typing import NDArray
from scipy.linalg import solve_banded

# σ(S, t) → local vol; a constant is wrapped into one of these.
LocalVol = Callable[[NDArray[np.float64], float], NDArray[np.float64]]


def _const_vol(c: float) -> LocalVol:
    def f(s: NDArray[np.float64], t: float) -> NDArray[np.float64]:
        return np.full_like(s, c)

    return f


def crank_nicolson_price(
    spot: float,
    strike: float,
    expiry: float,
    r: float,
    q: float,
    sigma: float | LocalVol,
    *,
    is_call: bool = True,
    barrier: float | None = None,
    n_s: int = 400,
    n_t: int = 400,
    s_max_mult: float = 4.0,
) -> float:
    """Price a European vanilla (or down-and-out call/put if ``barrier`` is set) by Crank–Nicolson.

    ``sigma`` is either a constant (Black-Scholes) or a callable ``σ(S, t)`` (local vol). With a
    ``barrier`` below spot the option knocks out continuously at that level (Dirichlet V = 0).
    Returns the price interpolated at ``spot``.
    """
    s_lo = barrier if barrier is not None else 0.0
    s_max = s_max_mult * max(spot, strike)
    grid = np.linspace(s_lo, s_max, n_s + 1)
    ds = grid[1] - grid[0]
    dt = expiry / n_t
    vol_fn: LocalVol = sigma if callable(sigma) else _const_vol(float(sigma))

    payoff = np.maximum(grid - strike, 0.0) if is_call else np.maximum(strike - grid, 0.0)
    if barrier is not None:
        payoff[grid <= barrier] = 0.0
    v = payoff.copy()
    interior = grid[1:-1]

    for n in range(n_t):
        t = expiry - n * dt  # march backward in calendar time
        vol = vol_fn(interior, t)
        alpha = 0.5 * vol * vol * interior * interior / (ds * ds)
        beta = (r - q) * interior / (2.0 * ds)
        lower = alpha - beta           # coeff on V_{i-1}
        diagL = -2.0 * alpha - r       # coeff on V_i
        upper = alpha + beta           # coeff on V_{i+1}

        # Crank–Nicolson: (I − ½dt L) Vⁿ = (I + ½dt L) Vⁿ⁺¹ in time-to-maturity.
        ab = np.zeros((3, interior.size))
        ab[0, 1:] = -0.5 * dt * upper[:-1]   # super-diagonal
        ab[1, :] = 1.0 - 0.5 * dt * diagL    # diagonal
        ab[2, :-1] = -0.5 * dt * lower[1:]   # sub-diagonal

        rhs = (
            (1.0 + 0.5 * dt * diagL) * v[1:-1]
            + 0.5 * dt * lower * v[:-2]
            + 0.5 * dt * upper * v[2:]
        )

        # Dirichlet boundaries at the level we are solving for (knock-out ⇒ 0 at the low edge).
        tau = (n + 1) * dt
        if is_call:
            v_lo = 0.0
            v_hi = s_max - strike * np.exp(-r * tau)
        else:
            v_lo = strike * np.exp(-r * tau) if barrier is None else 0.0
            v_hi = 0.0
        rhs[0] += 0.5 * dt * lower[0] * v_lo
        rhs[-1] += 0.5 * dt * upper[-1] * v_hi

        v_new = solve_banded((1, 1), ab, rhs)
        v = np.empty_like(grid)
        v[0] = v_lo
        v[-1] = v_hi
        v[1:-1] = v_new

    return float(np.interp(spot, grid, v))
