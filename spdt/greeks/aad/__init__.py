"""Adjoint algorithmic differentiation: all Greeks in one reverse pass (L5).

The point of AAD: one forward pass plus one reverse pass yields **all** input sensitivities
at a small constant multiple of a single price, *independent of the number of inputs* — which
is how a desk gets thousands of Greeks for thousands of trades overnight. We run the
Black-Scholes price through the hand-rolled tape in :mod:`spdt.greeks.aad.tape` to demonstrate
the mechanism on one product.
"""

from __future__ import annotations

from spdt.greeks.aad.tape import Var, backward, v_exp, v_log, v_norm_cdf, v_sqrt


def bs_vanilla_aad(
    spot: float, strike: float, t: float, r: float, q: float, sigma: float, is_call: bool
) -> tuple[float, dict[str, float]]:
    """Black-Scholes price **and** all first-order Greeks from one reverse pass.

    Returns ``(price, {"delta", "vega", "rho", "epsilon", "dPrice_dT"})`` where ``delta`` is
    ∂P/∂S, ``vega`` ∂P/∂σ, ``rho`` ∂P/∂r and ``epsilon`` ∂P/∂q (dividend sensitivity).
    """
    s = Var(spot)
    k = Var(strike)
    tau = Var(t)
    rate = Var(r)
    div = Var(q)
    vol = Var(sigma)

    vol_sqrt_t = vol * v_sqrt(tau)
    d1 = (v_log(s / k) + (rate - div + vol * vol * 0.5) * tau) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    disc_s = s * v_exp(div * tau * -1.0)
    disc_k = k * v_exp(rate * tau * -1.0)
    if is_call:
        price = disc_s * v_norm_cdf(d1) - disc_k * v_norm_cdf(d2)
    else:
        price = disc_k * v_norm_cdf(d2 * -1.0) - disc_s * v_norm_cdf(d1 * -1.0)

    backward(price)
    return price.value, {
        "delta": s.grad,
        "vega": vol.grad,
        "rho": rate.grad,
        "epsilon": div.grad,
        "dPrice_dT": tau.grad,
    }


__all__ = ["bs_vanilla_aad"]
