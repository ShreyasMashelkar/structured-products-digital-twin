# Interview Defense

The real deliverable. Each layer's "You must be able to defend" points, collected here
to rehearse from first principles. Build a one-page derivation card for each.

> Knowing these cold is worth more than any extra feature.

## Data (L1)
- Why invert to IV per contract rather than store prices (surface layer stays model-agnostic to spot/rate moves).
- Newton vs Brent for BS inversion (vega → 0 on deep wings).
- Why settlement-price IVs are biased on the wings (settlement ≠ traded mid, wide bid-offer).
- What survivorship bias does to backtested autocall frequency (inflates it).

## Vol Analytics (L2)
- SVI vs SSVI — slice vs surface; why SSVI removes calendar arbitrage by construction.
- The two arbitrage types (butterfly / calendar) and how each manifests.
- Why Dupire LV reprices vanillas exactly by construction, and what that does / doesn't buy you.
- Sticky-strike vs sticky-delta and which regime your delta assumes.

## Correlation
- Why a shocked correlation matrix breaks PSD and what that does to Cholesky/MC.
- Gaussian vs t copula tail dependence and why it matters for worst-of products.

## Product DSL (L3)
- Decompose a Phoenix into long/short option positions — who is long what.
- Why memory coupons increase value to the investor (issuer's short-vol exposure).
- Continuous vs discrete barrier monitoring; the Broadie-Glasserman-Kou continuity correction.

## Pricing (L4)
- Why Euler-on-variance is wrong and what the QE scheme fixes.
- Why LV alone misprices forward-smile products and SV alone misfits the spot smile → hence LSV.
- The LSV leverage-function calibration identity; what the conditional expectation means.
- Why CRN is mandatory for finite-difference Greeks.

## Greeks (L5)
- Derive the pathwise delta estimator and prove it's unbiased; why it fails for digitals.
- Why LR rescues digitals and why it's higher variance.
- The AAD cost claim (all Greeks at a small constant multiple of one price, independent of input count) and why reverse mode gives that.
- What vanna/volga mean for a short-vol autocallable book.

## Structurer (L6)
- What "to par" means (PV = issuer hedging cost + funding + margin).
- Why higher coupon ⟺ lower KI / more short optionality sold by the investor.
- Why the solver is well-posed (PV monotone in coupon).

## Backtesting (L7)
- Risk-neutral pricing (L4) vs real-world backtesting (L7) — conflating these is a classic error.
- How survivorship bias inflates backtested autocall frequency.
- Why autocallable backtests look great until they don't (short tail risk).

## Virtual Book (L8)
- Netting — net delta/vega, not gross.
- Why the book's aggregate vega is negative (autocallable desks are structurally short vol).
- Concentration — one underlying carrying most of the gamma.

## Hedging (L9)
- Why discrete delta-hedging P&L variance scales with rebalance frequency (√Δt).
- The gamma-theta trade-off; an autocallable issuer is typically short gamma near barriers.
- Why gap risk can't be delta-hedged away.

## P&L Attribution (L10)
- Why the residual is the most informative number in the report.
- Which products generate big residuals (high gamma/vanna near barriers).
- "Greek P&L" (Taylor) vs "revaluation P&L" (full reprice) and why both are computed.

## Model Risk (L11)
- Why LV and LSV agree on vanillas but disagree on autocallables (same marginals, different dynamics/forward smile).
- What a model reserve is for (P&L you can't book because you don't trust the model that far).
- Why a desk runs multiple models on purpose.

## Stress (L12)
- Why scenarios must be coherent (crash + vol-up + corr-up together), not independent single-factor bumps.
- Why correlation-up is the killer scenario for a worst-of book.
- Why an autocallable book's worst day is a sharp drop through the KI with no autocall relief.
