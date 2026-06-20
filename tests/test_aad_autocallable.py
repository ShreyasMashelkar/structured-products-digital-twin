"""AAD over the Monte-Carlo graph: the design doc's W10 three-way Greek cross-check.

Two claims:

* On a **smooth** payoff (a European call) AAD, the pathwise estimator and a CRN bump all
  agree — pathwise is unbiased there, and AAD computes exactly the pathwise estimator.
* AAD scales to the **flagship autocallable**: one reverse pass over the whole simulation
  yields its delta and vega. We validate that adjoint against an independent hand-written
  pathwise computation to machine precision.
"""

import numpy as np
import pytest

from spdt.greeks import autocallable_aad_greeks, bump_greeks, call_aad_greeks, pathwise_vanilla
from spdt.pricing import BlackScholes
from spdt.pricing.mc.rng import standard_normals
from spdt.products import Autocallable, EuropeanOption

MODEL = BlackScholes(spot=100.0, r=0.05, q=0.0, sigma=0.2)
OBS = (0.25, 0.5, 0.75, 1.0)


def test_call_aad_matches_pathwise_and_bump():
    aad = call_aad_greeks(MODEL, strike=100.0, expiry=1.0, n_paths=400_000, seed=1)
    pw = pathwise_vanilla(MODEL, strike=100.0, expiry=1.0, is_call=True, n_paths=400_000, seed=1)
    bump = bump_greeks(
        EuropeanOption(strike=100.0, expiry=1.0, is_call=True), MODEL, n_paths=400_000, seed=1
    )

    # AAD == pathwise to machine precision (same estimator, same draws).
    assert aad["delta"] == pytest.approx(pw["delta"], abs=1e-9)
    assert aad["vega"] == pytest.approx(pw["vega"], abs=1e-9)
    # AAD ≈ CRN bump (bump carries truncation + MC noise).
    assert aad["delta"] == pytest.approx(bump.delta, abs=2e-2)
    assert aad["vega"] == pytest.approx(bump.vega, abs=5e-2)


def _struck_autocallable():
    return Autocallable(
        notional=100.0,
        observation_times=OBS,
        coupon_rate=0.02,
        autocall_level=1.0,
        coupon_barrier=0.7,
        knock_in=0.6,
        initial_fixing=100.0,  # struck ⇒ fixed barriers ⇒ a real delta
    )


def _pathwise_autocallable_reference(note, model, n_paths, seed):
    """Independent pathwise delta/vega of the autocallable, written out by hand."""
    k0 = note.initial_fixing
    n = note.notional
    grid = np.array([0.0, *note.observation_times])
    dt = np.diff(grid)
    z = standard_normals(n_paths, len(note.observation_times), seed=seed)
    incr = (model.r - model.q - 0.5 * model.sigma**2) * dt + model.sigma * np.sqrt(dt) * z
    log_s = np.cumsum(incr, axis=1)
    spots = model.spot * np.exp(log_s)  # (n, n_steps), columns are the observation dates
    dlnS_dsig = np.cumsum(-model.sigma * dt + np.sqrt(dt) * z, axis=1)  # ∂lnS_t/∂σ

    alive = np.ones(n_paths, dtype=bool)
    last = len(note.observation_times) - 1
    delta = np.zeros(n_paths)
    vega = np.zeros(n_paths)
    for i, t in enumerate(note.observation_times):
        sv = spots[:, i]
        disc = np.exp(-model.r * t)
        if i < last:
            called = alive & (sv >= note.autocall_level * k0)
            alive = alive & ~called  # par redemption is constant ⇒ no delta/vega
        else:
            ki = alive & (sv <= note.knock_in * k0)
            # principal = n·S_T/k0 on knocked-in paths.
            delta += disc * ki * (n / k0) * (sv / model.spot)  # ∂S_T/∂S₀ = S_T/S₀
            vega += disc * ki * (n / k0) * (sv * dlnS_dsig[:, i])
    return {"delta": float(delta.mean()), "vega": float(vega.mean())}


def test_autocallable_aad_matches_handwritten_pathwise():
    note = _struck_autocallable()
    aad = autocallable_aad_greeks(note, MODEL, n_paths=200_000, seed=3)
    ref = _pathwise_autocallable_reference(note, MODEL, n_paths=200_000, seed=3)
    assert aad["delta"] == pytest.approx(ref["delta"], abs=1e-9)
    assert aad["vega"] == pytest.approx(ref["vega"], abs=1e-9)


def test_autocallable_aad_delta_has_the_right_sign():
    # The investor is long the downside via the knock-in: PV rises with spot ⇒ delta > 0.
    aad = autocallable_aad_greeks(_struck_autocallable(), MODEL, n_paths=200_000, seed=3)
    assert aad["delta"] > 0.0


def test_unstruck_autocallable_aad_is_rejected():
    note = Autocallable(notional=100.0, observation_times=OBS, coupon_rate=0.02)
    with pytest.raises(ValueError, match="struck"):
        autocallable_aad_greeks(note, MODEL)
