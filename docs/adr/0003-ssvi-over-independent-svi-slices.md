# ADR 0003 — SSVI surface over independent per-slice SVI

## Status
Accepted

## Context
The vol layer (L2) turns discrete implied-vol points into a continuous, queryable,
**arbitrage-free** surface. Two no-arbitrage conditions must hold:

- **Butterfly (static)** — the risk-neutral density of each maturity slice must be
  non-negative (Gatheral's Durrleman condition `g(k) ≥ 0`).
- **Calendar** — at fixed log-moneyness, total variance must be non-decreasing in
  maturity (`w(k, T₂) ≥ w(k, T₁)` for `T₂ > T₁`).

Raw **SVI** fits five parameters `(a, b, ρ, m, σ)` *independently per slice*. It is a great
single-slice fit and can be constrained to be butterfly-free, but nothing couples the slices,
so two adjacent maturities can **cross** and violate calendar arbitrage — which directly
corrupts the Dupire local vol (a `∂w/∂T` that goes negative produces an imaginary local vol)
and therefore every forward-smile-sensitive exotic.

## Decision
Use **SSVI** (surface SVI) as the surface parametrisation:
`w(k, θ) = (θ/2)·(1 + ρφ(θ)k + √((φ(θ)k + ρ)² + (1 − ρ²)))`, with `θ(T)` the ATM total-variance
term structure and `φ(θ)` a power-law. SSVI is **calendar-arbitrage-free by construction**
under simple parameter conditions, and butterfly-free under a companion condition on `θφ`.
Per-slice SVI is retained as the calibration target/diagnostic and for slices fit in isolation,
but the surface a snapshot exposes is SSVI.

## Consequences
- **Calendar arbitrage is structurally impossible**, not merely checked-and-repaired after the
  fact — the single most important property for a Dupire local vol that does not explode.
- **Fewer free parameters across the surface** ⇒ a more stable fit on sparse/noisy
  bhavcopy-inverted points, and a coherent term structure rather than a stack of unrelated fits.
- **Durrleman butterfly check still runs** on a `k`-grid as a guard (the `arbitrage` module);
  SSVI removes calendar arb but butterfly must still be enforced via the parameter condition.
- **Cost / limitation.** SSVI is less flexible per slice than free SVI, so a pathological single
  smile fits slightly worse. We accept marginally higher per-slice residual in exchange for a
  globally arbitrage-free surface — the right trade for pricing exotics off the surface. A desk
  with richer data would move to SABR/proprietary surfaces with local overrides.
