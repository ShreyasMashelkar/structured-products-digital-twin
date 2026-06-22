# Interview Defense

The real deliverable. Each layer's "You must be able to defend" points, collected here
to rehearse from first principles. Build a one-page derivation card for each.

> Knowing these cold is worth more than any extra feature.

## Data (L1)
- Why invert to IV per contract rather than store prices (surface layer stays model-agnostic to spot/rate moves).
- Newton vs Brent for BS inversion (vega → 0 on deep wings).
- Why settlement-price IVs are biased on the wings (settlement ≠ traded mid, wide bid-offer).
- What survivorship bias does to backtested autocall frequency (inflates it).
- Why rates are **bootstrapped** term structures, never flat — back out `D(T)` from FBIL OIS/T-bills shortest-maturity-first; interpolation choice (log-DF vs monotone-convex forwards) and what a bad one does to the forward curve.
- Why the snapshot carries **two** curves: OIS/risk-free (drift + option-leg discount) vs issuer funding (discounts the ZCB leg); a note is the issuer's debt.
- Why the funding curve is a **spread over OIS** (small parametric `s(T)`), not a direct issuer bootstrap — sparse issuer data, coherent rate risk, shockable spread (ADR 0002); when you'd flip to direct bootstrap.

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

## XVA / CCR (the exposure seam)
- Why couple the two desks at **exposure** (path × time NPV), not the product model — the one thing XVA needs from SPDT and the narrowest sufficient interface (ADR-0007).
- Why **mark-to-future** EE uses Longstaff–Schwartz continuation value, not realised pathwise cashflows — the latter biases EE up (Jensen, `max` outside the conditional expectation).
- Why an **autocallable's EE collapses** at each autocall date (redeemed paths leave the book) while a non-callable note's stays elevated.
- **CVA** = LGD · Σ EE·ΔPD·DF; why it's unilateral by default and what DVA adds (own-default benefit on the *negative* exposure); the FVA/DVA overlap debate.
- **FVA** = funding the EPE at the issuer spread; **KVA** = cost of capital over the life; **MVA** = funding initial margin (99%/10-day close-out). Why the all-in charge is `CVA+FVA+KVA+MVA−DVA`.
- **EEPE** is the time-average of *effective* EE (running max) over `[0, min(1y, T)]` — why Basel caps the window at one year, and how EAD = α·EEPE (α = 1.4).
- **EAD two ways**: cube-based economic α·EEPE vs supervisory **SA-CCR** (RC + PFE add-on, equity SF 32%/20%) — why SA-CCR ignores your MC and uses supervisory factors.
- **Capital two ways**: ASRF economic capital (unexpected loss, 99.9%) vs **BA-CVA** regulatory capital — and why they differ.
- **Collateral**: how a CSA (threshold/MTA/**MPoR**) reduces residual exposure to the close-out gap; why a coarse grid needs a variance-corrected close-out.
- **Wrong-way risk**: why correlation of exposure with the counterparty's default raises CVA; parametric (Esscher tilt) vs jointly-simulated intensity.
- **CS01 / JTD**: the CVA desk's two first-order credit risks and how each is hedged.
- The **all-in price**: why fairness becomes `PV = par − fee − XVA`, so the offerable coupon falls as the counterparty's spread widens (7.25% → 1.09% p.a. at 300bp, full CVA+FVA+KVA+MVA).
- **Governance**: limit check on EAD/PFE + RAROC vs hurdle → APPROVED / REJECTED / MANUAL_REVIEW.

## Market-data sourcing (L1, live)
- Why NSE blocks public *scraping* (anti-bot on the option-chain API) but the bhavcopy **archive** is reachable — so the reliable free live path is **EOD bhavcopy** (walk back to the latest published file).
- EOD settlement marks vs **intraday** LTPs: why bhavcopy is the better default (official marks, full chain in one file, reproducible) and Dhan only when real-time matters.
- Why a keyed **broker API** (Dhan) beats scraping for intraday — authenticated, not IP-blocked — and the trade-off (account + expiring token, not reproducible).
