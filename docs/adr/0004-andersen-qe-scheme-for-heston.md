# ADR 0004 — Andersen QE scheme for Heston simulation

## Status
Accepted

## Context
Heston's variance follows a CIR process `dv = κ(θ − v)dt + ξ√v dW₂`, which is **non-central χ²**
distributed and must stay non-negative. The obvious discretisation — Euler on the variance —
is wrong in two ways: it is **biased** (the √v coefficient makes the naïve scheme inconsistent
at practical step sizes), and it routinely produces **negative variance**, which then has to be
floored or reflected, injecting further bias. For an autocallable book whose value lives in the
forward smile, that bias is not academic — it moves prices and reserves.

## Decision
Simulate the variance with the **Andersen (2008) Quadratic-Exponential (QE)** scheme. QE matches
the first two moments of the exact transition law with one of two proxies chosen per step:

- a **quadratic** proxy `v' = a(b + Z)²` when the variance is large (`ψ ≤ ψ_c`), and
- an **exponential** proxy (a mass at zero plus an exponential tail) when it is small (`ψ > ψ_c`),

with the spot advanced by the **martingale-corrected** log-Euler update (the `k₀…k₄`
coefficients). The vanilla benchmark is the **characteristic-function** price (Heston's
two-integral formula, plus a Carr–Madan FFT pricer for whole-smile calibration); the QE Monte
Carlo converging to that CF price is the headline cross-check.

## Consequences
- **Variance stays non-negative by construction** — no flooring/reflection hacks and the bias
  they carry.
- **Accurate at large steps.** QE is near-unbiased even with coarse time grids, so the
  autocallable's observation-date grid does not need heavy sub-stepping for the variance leg.
- **Validated.** The QE MC reproduces the CF/FFT vanilla price to Monte-Carlo tolerance
  (`tests/test_heston.py`), and the same QE variance engine is reused inside the LSV model.
- **Cost / limitation.** QE is more code than Euler (two branches, moment matching) and the
  martingale correction must be derived carefully. We accept that complexity because Euler-on-
  variance is simply not fit for pricing forward-smile-sensitive exotics.
