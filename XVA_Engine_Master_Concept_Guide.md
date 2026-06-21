# XVA Engine — Master Concept Guide
### Learn the whole platform end-to-end, one concept at a time

> **Purpose:** This is a teaching document, not a changelog. For every concept the app uses, it answers four questions in order:
> 1. **The concept** — what it is, the maths, the intuition (taught from scratch).
> 2. **Why it's needed** — the real risk/business problem it solves.
> 3. **How this app uses it** — the actual implementation, file, and design.
> 4. **Why this solution** — why this choice over the alternatives.
>
> Read top to bottom and you can narrate the app as a single pipeline:
> **free market data → curves → simulate the future → price exposure → adjust for credit/funding/capital (XVA) → regulatory capital → governance.**
>
> ⚠️ **Accuracy notes vs the marketing audit** are flagged with `REALITY CHECK` boxes so you never overclaim in an interview.

---

## PART 0 — THE BIG PICTURE (read this first)

### The one question the whole platform answers
Post-2008, a bank cannot price a derivative at its "textbook" value. It must answer:

> *"What is the **true all-in cost** of this trade once I account for the chance my counterparty defaults, the chance I default, the cost of funding it, the regulatory capital it consumes, and the margin I must post — and given all that, should I even do the trade?"*

The "textbook value" is the **clean price** (or **clean MTM** = mark-to-market). All the adjustments are the **XVA** family (Valuation Adjustments, "X" = a placeholder for C, D, F, K, M…):

```
Risky price = Clean MTM  −  CVA  +  DVA  −  FVA  −  KVA  −  MVA
                            (their   (my    (funding (capital (margin
                            default) default) cost)   cost)   cost)
```

### The pipeline (this is the app's spine)
```
   FREE MARKET DATA          (FIMMDA, RBI DBIE, CCIL, NSE)
        │
   BUILD CURVES              OIS discount curve, projection curve, credit curve
        │
   SIMULATE THE FUTURE       Hull-White Monte Carlo → thousands of rate paths
        │
   PRICE ON EACH PATH        swap MTM at every (path, time) → the "exposure cube"
        │
   EXPOSURE METRICS          EE, EPE, EEPE, PFE, ENE
        │
   APPLY COLLATERAL/NETTING  CSA rules, MPoR, netting sets
        │
   XVA STACK                 CVA, DVA, FVA, KVA, MVA  (+ sensitivities)
        │
   REGULATORY CAPITAL        SA-CCR EAD → RWA, BA-CVA, FRTB SA-CVA, Economic Capital
        │
   GOVERNANCE                Limits, RAROC, Trade Approval, Attribution, Stress, Reporting
```

Every module below sits somewhere on this spine. Keep the spine in your head and the 30 concepts stop feeling like a pile and start feeling like a machine.

---
---

# PART 1 — THE FOUNDATION: MARKET DATA & CURVES

## 1.1 Discount factors, zero rates, and the yield curve (the absolute basics)

**The concept.** Money today is worth more than money tomorrow. A **discount factor** `P(0,T)` (a.k.a. `DF(T)`) is the value *today* of ₹1 paid at time `T`. From it you get:
- **Zero rate** `z(T)`: the single continuously-compounded rate such that `P(0,T) = e^(−z(T)·T)`.
- **Forward rate** `f(0;T1,T2)`: the rate, agreed today, for borrowing between two *future* dates. `f = (P(0,T1)/P(0,T2) − 1) / (T2−T1)`.
- **Instantaneous forward** `f(0,t) = −∂ ln P(0,t)/∂t`: the forward rate over an infinitesimally short future window — this is the quantity the Hull-White model needs (Part 3).

A **curve** is just `P(0,T)` for all `T`, built from a handful of market-quoted instruments.

**Why it's needed.** Everything downstream — swap value, exposure, CVA discounting — is a sum of future cashflows multiplied by discount factors. No curve, no valuation.

**How this app uses it.** `src/curves/ois_curve.py` (`OISCurve`, `GSecCurve`) stores the curve and exposes `df(T)`, `zero_rate(T)`, `forward_rate(T1,T2)`, and `instantaneous_forward(t)`. It also has `shift()` (parallel bump) and `bump_tenor()` (single-node bump) — these exist specifically so you can compute **key-rate DV01** and build the **multi-curve** framework.

**Why this solution.** Interpolation is **log-linear on discount factors** (linear in `ln P`), which guarantees positive forward rates (no arbitrage) and is the standard, robust desk choice. A cubic spline on rates can look smoother but can produce negative forwards (arbitrage) — avoided here on purpose.

---

## 1.2 OIS discounting and curve bootstrapping

**The concept — OIS.** An **Overnight Indexed Swap** exchanges a fixed rate for the compounded overnight rate (in India, the overnight MIBOR). The overnight rate is the closest thing to "risk-free + funded" that exists, so the OIS curve is used as the **discount curve**.

**Bootstrapping** = solving for the curve one instrument at a time, shortest first. Short end from deposit rates (`DF = 1/(1+r·t)`); long end by iterating par OIS rates so that each quoted swap prices to par. Each new instrument pins down one more curve node.

**Why it's needed — the 2008 lesson.** Before 2008 banks discounted with LIBOR. After Lehman, everyone realised collateralised trades are funded at the overnight (OIS) rate, not LIBOR. Discounting with the wrong curve mis-prices every trade. "**OIS discounting**" is now mandatory market practice. Using it signals you understand post-GFC plumbing.

**How this app uses it.** `OISCurve` bootstraps from INR OIS par rates sourced free from FIMMDA/RBI. `GSecCurve` (government bond yields) is built alongside to show the **sovereign basis** (G-Sec vs OIS).

**Why this solution.** It's the literal market standard, and it's buildable from *free* Indian data. The honest limitation: the OIS–MIBOR **basis** isn't separately bootstrapped (see 1.3).

---

## 1.3 Multi-curve framework (the OIS–MIBOR basis)

**The concept.** Post-2008 you need **two** curves, not one:
- **Discount curve** (OIS) — for present-valuing cashflows.
- **Projection/forecast curve** (MIBOR) — for predicting the floating-rate fixings a swap will pay.

They differ by the **basis spread** (credit/liquidity premium in the term rate over the overnight rate). Using one curve for both ("single-curve") is the pre-2008 simplification.

**Why it's needed.** A floating leg pays MIBOR but is discounted at OIS. If you assume they're equal you misprice the floating leg by the basis — a real, first-order XVA driver.

**How this app uses it.** `src/curves/multi_curve.py` builds a projection curve = OIS + constant basis. `HullWhite1F.compute_swap_mtm_paths` takes an optional `projection_curve`; when supplied it projects the float leg off MIBOR and discounts off OIS.

**Why this solution / `REALITY CHECK`.** The basis here is a **constant spread**, not a separately bootstrapped MIBOR-swap curve (that needs paid MIBOR swap quotes). Also, the **default** exposure simulation runs the *single-curve shortcut* (`float PV = N·(1 − P(t,T))`) unless you explicitly pass a projection curve. So: the multi-curve machinery exists and is correct, but the headline exposure numbers use the single-curve shortcut. Say it that way.

---

## 1.4 The 3-tier free-data architecture

**The concept.** Production desks pay for Bloomberg/Refinitiv. A student has ₹0. So the data layer is built as **Live → Cache → Synthetic fallback**: try the free public endpoint (FIMMDA Excel, RBI DBIE, NSE); if it fails, use a local JSON cache; if that's empty, use a hard-coded value calibrated to recent market levels.

**Why it's needed.** Free endpoints are flaky (FIMMDA changes formats, NSE blocks non-Indian IPs). Without graceful fallback the whole app dies when a website is down.

**How this app uses it.** `src/data_ingestion/market_data.py` and `equity_data.py` follow this pattern everywhere; each result carries a `source` field (`LIVE` / `CACHE` / `CALIBRATED_FALLBACK`) so you always know data provenance.

**Why this solution.** It's the only way to make a free-data app robust. `REALITY CHECK`: when you demo it outside India, you're almost always on `CALIBRATED_FALLBACK` — be upfront that the numbers are realistic synthetic levels, not live quotes.

---
---

# PART 2 — PRICING THE INSTRUMENTS

## 2.1 The interest-rate swap (IRS/OIS) and its risk

**The concept.** A vanilla IRS exchanges a **fixed** leg for a **floating** leg on a notional. Value = PV(fixed) − PV(float) (sign flips for pay/receive). Two key by-products:
- **Par rate** — the fixed rate that makes the swap worth zero today (the "fair" quote).
- **DV01 / PV01** — the change in value for a 1bp move in rates (the core interest-rate risk number). **Key-rate DV01** breaks that into sensitivity to each curve tenor.

**Why it's needed.** The IRS is the single most traded OTC derivative on earth and the app's primary instrument. DV01 is how every rates desk measures and hedges its book.

**How this app uses it.** `src/pricing/swap_pricer.py` (`SwapPricer`) decomposes the legs, computes `mtm`, `par_rate`, `dv01`, `pv01`, and key-rate DV01 by bumping individual nodes.

**Why this solution.** Analytic leg decomposition is exact and instant — no simulation needed for *today's* value. (Simulation comes in only for *future* exposure, Part 3.)

---

## 2.2 Swaptions and the Bachelier (normal) model

**The concept — a swaption** is an option to enter a swap at a future date. To price an option you need a model for how the underlying rate moves. Two choices:
- **Black (lognormal):** assumes the rate is lognormal — can't handle negative or near-zero rates (rate can't go below 0 in the model).
- **Bachelier (normal):** assumes the rate moves as an *arithmetic* Brownian motion — **allows negative rates** and is the market standard for low-rate regimes.

**Why it's needed.** Swaptions are the main instrument for hedging rate **optionality**, and — crucially — swaption prices are what you'd normally calibrate the Hull-White volatility to (Part 3.6).

**How this app uses it.** `src/pricing/swaption.py` prices swaptions with the **Bachelier** formula, feeding off the SABR vol surface (2.3).

**Why this solution.** Normal/Bachelier is chosen because INR rates can sit low and the normal model is numerically stable there; it's also the convention for the SABR "normal vol" parameterisation used next.

---

## 2.3 SABR — a stochastic-volatility model for the smile

**The concept.** A single volatility number can't fit the market: options at different strikes imply different vols (the **volatility smile/skew**). **SABR** (Stochastic Alpha-Beta-Rho) models the forward `F` and its vol `α` as two correlated random processes:
```
dF = α·F^β dW₁ ,   dα = ν·α dW₂ ,   corr(dW₁,dW₂) = ρ
```
- `α` = overall vol level, `β` = backbone (0 = normal, 1 = lognormal), `ρ` = skew, `ν` = vol-of-vol (smile curvature).
Hagan et al. (2002) give a famous closed-form approximation for the implied vol as a function of strike — so you fit 4 parameters and get the whole smile.

**Why it's needed.** A vol *surface* (vol by strike and expiry) is required to price any non-ATM option consistently and to build a realistic vol input.

**How this app uses it.** `src/pricing/sabr.py` implements Hagan's **normal-vol** approximation, calibrates `(α,ρ,ν)` via `scipy.optimize.minimize`, and builds a `VolSurface`. Because real INR swaption vols are paid data, it anchors the ATM level to **realised** vol from free DBIE history.

**Why this solution / `REALITY CHECK`.** SABR is *the* market-standard smile model. The honest gap: the ATM anchor is **realised** vol, not **market-implied** vol — these differ by a volatility risk premium. Hagan's approximation can also produce tiny arbitrage in the wings (a known SABR issue). Both are fair interview talking points.

---
---

# PART 3 — SIMULATING THE FUTURE: MONTE CARLO EXPOSURE

This is the heart of the engine. Pricing gives today's value; **exposure** asks: *how much could the counterparty owe me at every future date, across thousands of scenarios?*

## 3.0 Why simulate at all? (Expected Exposure)

**The concept.** If a counterparty defaults at time `t`, your loss is whatever they owe you then — i.e. `max(MTM(t), 0)` (you lose the positive value; if you owe them, there's no loss to you). But `MTM(t)` is unknown today because rates move. So you **simulate** many possible rate paths, reprice the trade on each, and look at the distribution of `max(MTM,0)`.

**The exposure metrics** (all functions of time):
- **EE (Expected Exposure):** the average of `max(MTM,0)` across paths. *"On average, how much am I owed?"*
- **PFE (Potential Future Exposure):** a high percentile (e.g. 95th) of exposure. *"In a bad-but-plausible case, how much am I owed?"* — the standard **limit** metric.
- **ENE (Expected Negative Exposure):** average of `min(MTM,0)` — what *I* owe (drives DVA/FBA).
- **EPE (Expected Positive Exposure):** the time-average of EE.
- **EEPE (Effective EPE):** the time-average of the **running maximum** of EE, capped at 1 year — this is the Basel III regulatory exposure used for capital. The running-max and 1Y cap are deliberately conservative regulatory choices.

**Why it's needed.** CVA, regulatory capital (SA-CCR/IMM), and limit monitoring all consume these profiles. They are the bridge from "market risk" to "counterparty credit risk."

---

## 3.1 Hull-White 1-Factor (the core short-rate model)

**The concept.** Hull-White (HW1F) models the instantaneous short rate `r(t)`:
```
dr(t) = [θ(t) − a·r(t)]·dt + σ·dW(t)
```
- `a` = **mean reversion** speed (how fast rates pull back to their long-run level).
- `σ` = **volatility** of the short rate.
- `θ(t)` = a **time-dependent drift** chosen so the model **exactly reproduces today's curve**. This is the defining trick of HW: it's an *arbitrage-free* model that fits the initial term structure perfectly.

Two more pieces make it production-grade:
- **Exact transition (not Euler).** The model is decomposed as `r(t) = x(t) + α(t)`, where `x` is a zero-mean Ornstein-Uhlenbeck process and `α(t)` is a deterministic shift. The OU process has an **exact** one-step update — no time-stepping (Euler) discretisation error:
  ```
  x(t+Δ) = x(t)·e^(−aΔ) + σ·√[(1−e^(−2aΔ))/(2a)]·Z ,   Z ~ N(0,1)
  ```
- **Exact bond pricing.** On any path you can price a zero-coupon bond in closed form:
  ```
  P(t,T) = A(t,T)·exp(−B(t,T)·x(t)) ,   B(t,T) = (1−e^(−a(T−t)))/a
  ```
  with `A(t,T) = [P(0,T)/P(0,t)]·exp(½·B²·Var[x(t)])` — the `½B²Var[x]` term is the **convexity correction**. Getting this term right is the classic HW bug; this codebase gets it right (the "y-process reconstitution").

**Why it's needed.** You must reprice the swap at every future date on every path. Re-bootstrapping a curve 60×10,000 times would be impossibly slow; the closed-form `A·exp(−B·x)` reprices instantly. HW1F is the workhorse rates model for exposure because it's analytically tractable *and* fits the curve.

**How this app uses it.** `src/montecarlo/hull_white.py`: `simulate_rates` (exact OU), `compute_swap_mtm_paths` (exact bond pricing on each path), `compute_exposure_metrics` (EE/PFE/EEPE…).

**Why this solution.** HW1F is the standard first model on every rates desk: Gaussian, mean-reverting, fits the curve, closed-form bonds. `REALITY CHECK`: it's **single-factor**, so the whole curve moves off one shock — it can't represent steepeners/flatteners (curve-shape risk). It's also **Gaussian**, so rates can go negative (a "floor at 0.1%" is applied to the *displayed* paths but the MTM is priced off the unfloored Gaussian factor — the floor is cosmetic).

---

## 3.2 Antithetic variates (variance reduction)

**The concept.** Monte Carlo error shrinks like `1/√N`. **Antithetic variates** is a cheap trick: for every random draw `Z`, also use `−Z`. The two mirror paths are negatively correlated, so their average has lower variance — you get the accuracy of more paths for free.

**Why it's needed.** Exposure tails (PFE) are noisy; variance reduction tightens them without more compute.

**How this app uses it.** Built into `simulate_rates` (`antithetic=True`): it generates `N/2` normals and concatenates their negatives.

**Why this solution.** It's the simplest, most robust variance-reduction method and essentially free. (Quasi-MC, 3.3, is the more powerful alternative.)

---

## 3.3 Quasi-Monte Carlo (Sobol sequences)

**The concept.** Ordinary MC uses *pseudo-random* numbers, which clump and leave gaps. **Quasi-MC** uses **low-discrepancy sequences** (Sobol) that fill space more evenly, improving convergence from `~1/√N` toward `~1/N` (often hundreds of times more accurate at the same `N`). A **Brownian bridge** is used to assign the most "important" Sobol dimensions to the largest time-steps.

**Why it's needed.** Faster convergence = same accuracy with far fewer paths = cheaper.

**How this app uses it.** `src/montecarlo/quasi_mc.py`: Sobol normals + Brownian bridge, with a convergence demo (QMC vs MC vs the analytic Bachelier answer — QMC ~hundreds× better at N≈2048).

**Why this solution.** Sobol+bridge is the standard QMC setup in finance; pure NumPy/SciPy, no exotic dependencies.

---

## 3.4 Hull-White 2-Factor

**The concept.** HW2F adds a **second** correlated factor so the curve can move in two independent ways — level *and* slope — capturing steepeners and flatteners that HW1F cannot.

**Why it's needed.** Long-dated and curve-shape-sensitive trades need richer curve dynamics for realistic exposure.

**How this app uses it.** `src/montecarlo/hull_white_2f.py` — shown on the "HW2F Term Structure" page. `REALITY CHECK`: it's a **demonstration** model; the main exposure pipeline (and CVA) still runs off **HW1F**. Don't claim HW2F drives the headline CVA.

---

## 3.5 Calibration — fitting `a` and `σ`

**The concept.** A model needs parameters. Here `a` and `σ` are estimated by **OLS regression** on historical overnight MIBOR: discretise the SDE as `Δr = α + β·r + noise`, regress, then recover `a = −β/Δt` and `σ = std(residuals)/√Δt`.

**Why it's needed.** Static guessed parameters aren't defensible; calibrating to data shows econometric rigour. MIBOR history is free from RBI.

**How this app uses it.** `calibrate_hw1f` in `hull_white.py`, plus `src/calibration/hw_calibrator.py`, with sanity-clipping to INR-plausible ranges (`a∈[0.01,0.50]`, `σ∈[0.001,0.05]`).

**Why this solution / `REALITY CHECK` (important interview point).** Two honest caveats: (1) **Measure mismatch** — σ from history is the **real-world (P-measure)** vol, but exposure/XVA are **risk-neutral (Q-measure)** quantities that should be calibrated to **swaption-implied** vol (paid data the app doesn't have). (2) OLS mean-reversion estimates are biased toward zero in short samples, and the **sanity-clip** can end up choosing the number when the estimate is poor. Know these — a senior quant *will* ask.

---
---

# PART 4 — THE EXPOSURE CUBE

**The concept.** Once you simulate, you have a 3-D array: **path × time × trade** of MTM values. That's the **exposure cube**. From it you can slice any exposure (per trade, per netting set, per counterparty) and recompute any XVA *without re-simulating*.

**Why it's needed.** Re-running Monte Carlo for every query (every CVA, every limit check) is wasteful. Banks compute the cube once overnight and reuse it all day. Persisting it also enables incremental/portfolio analytics.

**How this app uses it.** `src/exposure/exposure_cube.py` stores the cube in **Apache Parquet** (via PyArrow) — a columnar, compressed, language-agnostic format ideal for big numeric tables. Supports trade-level retrieval and portfolio netting.

**Why this solution.** Parquet is the industry standard for analytical data at rest (fast columnar reads, good compression). `REALITY CHECK`: it does a full re-write each run (no incremental updates) and isn't tuned for millions of paths — fine for a prototype.

---
---

# PART 5 — COUNTERPARTY CREDIT & THE XVA STACK

## 5.1 Credit curves: hazard rate, survival probability, the credit triangle

**The concept.** To value default risk you need the probability the counterparty defaults over time. Model it with a **hazard rate** (default intensity) `h` — the instantaneous default probability per unit time. Then:
- **Survival probability:** `SP(t) = e^(−h·t)` (flat hazard) or a piecewise version.
- **Marginal default probability** in `[t1,t2]`: `SP(t1) − SP(t2)`.
- **The credit triangle:** `h ≈ s / (1−R)`, where `s` is the CDS spread and `R` is recovery. This links a *traded* CDS spread to a default intensity — the most-used approximation in credit.

**Why it's needed.** CVA = expected loss from counterparty default = exposure × default probability × loss-given-default. You can't compute it without `SP(t)`.

**How this app uses it.** `src/xva/cva.py`: `CreditCurve` (flat hazard from one spread) and `TermStructureCreditCurve` (bootstrapped, 5.2).

**Why this solution.** The credit triangle is the standard quick map from spreads to intensities. `REALITY CHECK`: India has **no liquid single-name CDS market**, so the spreads feeding this are **synthetic** (rating-based ladder). This is the app's biggest data weakness and you should name it before the interviewer does — a real Indian CVA desk proxies credit from bond asset-swap spreads.

---

## 5.2 CDS bootstrapping (term-structure hazard rates)

**The concept.** A single flat hazard rate distorts short- and long-dated default probabilities. **Bootstrapping** fits a *piecewise-constant* hazard curve to a *term structure* of CDS spreads (1Y, 2Y, 3Y, 5Y, 7Y) by equating, at each tenor, the PV of the premium leg and the PV of the protection leg.

**Why it's needed.** Default probability has a term structure; a flat curve misprices CVA for trades of different maturities.

**How this app uses it.** `src/curves/credit_curve_bootstrapper.py` (`CDSBootstrapper`) → `TermStructureCreditCurve`.

**Why this solution.** Piecewise-constant hazard bootstrapping is the standard credit-curve build. (The full ISDA Standard Model adds upfront/accrual conventions — out of scope.)

---

## 5.3 CVA (Credit Valuation Adjustment)

**The concept.** CVA is the **market price of the counterparty's default risk** — the expected discounted loss if they default:
```
CVA = LGD · Σ_i  EE(t_i) · ΔPD(t_i) · DF(t_i)
```
- `LGD = 1−R` (loss given default), `EE` (expected exposure, Part 3), `ΔPD` (marginal default prob in the period), `DF` (risk-free discount). Quoted as a positive cost; it reduces the value of a trade to you.

**Why it's needed.** It's the central post-GFC adjustment — every bank has a CVA desk. "Risky value = clean − CVA."

**How this app uses it.** `CVAEngine.compute_cva` integrates the formula with mid-point EE and OIS discounting, using either credit curve.

**Why this solution.** This is the textbook unilateral-CVA discretisation. `REALITY CHECK`: it assumes **independence** between exposure and default (no wrong-way risk inside the integral — WWR is handled separately in Part 8), and uses a deterministic EE.

---

## 5.4 DVA (Debit Valuation Adjustment) & Bilateral CVA

**The concept.** Symmetric to CVA but for **your own** default: if *you* default when you owe the counterparty (negative exposure), you "save" that payment — an accounting *benefit*.
```
DVA = LGD_own · Σ |ENE(t_i)| · ΔPD_own(t_i) · DF(t_i)
Bilateral CVA = CVA − DVA
```

**Why it's needed.** **IFRS 13** (fair-value accounting) requires DVA in the fair value of derivatives. The bilateral framework gives the net credit adjustment.

**How this app uses it.** `CVAEngine.compute_dva` / `compute_bilateral_cva`, with own-credit curve and DVA01 sensitivity in the workflow layer.

**Why this solution.** Standard mirror of CVA. `REALITY CHECK`: DVA is *philosophically* controversial — booking a gain because *your own* credit deteriorated is counter-intuitive and regulators strip it from capital (it stays in accounting). Good thing to mention.

---

## 5.5 FVA (Funding Valuation Adjustment)

**The concept.** Uncollateralised derivative positions must be **funded** at the bank's funding rate, not the risk-free rate. FVA = the cost/benefit of that funding spread over the life of the trade:
- **FCA** (cost): funding positive exposure you can't collateralise.
- **FBA** (benefit): negative exposure provides funding.
- `FVA = FCA + FBA`. Properly, the funding integral is **survival-weighted** by both parties (you only fund while both are alive).

**Why it's needed.** Funding is a real cash cost; Treasury charges it back to the desk via FVA.

**How this app uses it.** `src/xva/fva.py` (`FVAEngine`) computes FCA/FBA with optional `SP_bank·SP_cpty` weighting; `fva_v2.py` adds path-wise FVA/ColVA.

**Why this solution / `REALITY CHECK`.** FVA is the **most debated** XVA (Hull-White argue it's partly double-counting; Burgard-Kjaer formalise it). Two honest points: (1) the funding spread here is a **static** entity-type ladder, not a term structure; (2) the live app adds **both** DVA and FBA, which economically **overlap** (the FVA/DVA symmetry debate) — a deliberate-looking choice you should be ready to defend.

---

## 5.6 KVA (Capital Valuation Adjustment)

**The concept.** Holding a trade consumes **regulatory capital**, and capital has a cost (the shareholders' required return). KVA = the lifetime cost of the capital a trade ties up:
```
KVA = CoC · ∫ EK(t) · DF(t) dt
```
where `EK(t)` is expected capital over time and `CoC` is the cost of capital.

**Why it's needed.** Without KVA, traders don't "see" the capital their trades burn, and the desk over-trades capital-hungry business.

**How this app uses it.** `src/xva/kva.py` ties `EK(t)` to the **SA-CCR EAD profile** (Part 7), using RBI's 10.5% capital ratio and ~12% cost of equity.

**Why this solution.** Linking KVA to SA-CCR is the standard way to get a capital profile without IMM. `REALITY CHECK`: the capital profile is a simple amortisation, not re-simulated each step.

---

## 5.7 MVA (Margin Valuation Adjustment) & ISDA SIMM

**The concept.** Under **UMR** (Uncleared Margin Rules) banks must post **Initial Margin (IM)** — collateral sized to cover a 10-day stressed move — on uncleared trades. That IM must be *funded*, and **MVA** is the lifetime cost of funding it. IM itself is computed by **ISDA SIMM** (Standard Initial Margin Model): a sensitivity-based formula with prescribed risk weights and correlation matrices per risk class.

**Why it's needed.** Post-2016 UMR, IM funding is a material cost; MVA prices it in.

**How this app uses it.** `src/xva/simm.py` implements SIMM v2.7 risk weights + the tenor correlation matrix and projects IM **dynamically** over the trade's life to integrate MVA.

**Why this solution / `REALITY CHECK`.** SIMM with public ISDA parameters is exactly right. The implementation covers **Interest-Rate Delta only** — no Vega/Curvature, no cross-currency aggregation. State that scope.

---

## 5.8 Sensitivities & AAD (the hedging numbers)

**The concept.** A CVA desk must **hedge**, so it needs sensitivities: **CS01** (CVA change per 1bp CDS-spread move — the primary credit hedge ratio), **IR01** (per 1bp rate move), and **CDS Gamma** (second-order). The naive way is **bump-and-revalue** (shift each input, recompute) — O(N) revaluations. **AAD** (Adjoint/Algorithmic Differentiation) computes *all* sensitivities in essentially **one** reverse pass by propagating derivatives backward through the computation graph — the technique that makes real-time XVA Greeks feasible without a GPU farm.

**Why it's needed.** A book has thousands of risk factors; bumping each is too slow for live risk. AAD is how tier-1 desks get the full Greek vector cheaply.

**How this app uses it.** `src/utils/autodiff.py` (a self-contained reverse-mode tape) + `src/xva/aad_greeks.py` (`AADCVAEngine`) produce the full CVA Greek vector in one sweep and benchmark it against bump-and-revalue (matches to machine precision).

**Why this solution.** Hand-rolled reverse-mode AAD (no JAX/PyTorch) shows you understand the *mechanism*, not just the library — a strong signal.

---
---

# PART 6 — COLLATERAL & NETTING

## 6.1 Netting sets, ISDA, and CSA

**The concept.** Trades with one counterparty are governed by an **ISDA Master Agreement**; on default they **net** (positives offset negatives) into a single claim — the **netting set**. A **CSA** (Credit Support Annex) attached to it governs **collateral** (margin) exchange. Key CSA parameters:
- **Threshold:** unsecured amount allowed before collateral must be posted.
- **MTA (Minimum Transfer Amount):** don't bother moving collateral for tiny changes.
- **IA (Independent Amount):** extra collateral held regardless of MTM.

**Why it's needed.** Netting and collateral *massively* reduce exposure. Computing gross (un-netted) exposure overstates EAD and capital by multiples — getting netting right is first-order.

**How this app uses it.** `src/portfolio/netting_engine.py` aggregates MTM paths by CSA; `src/csa/collateral.py` applies threshold/MTA/IA to produce **collateralised exposure**.

**Why this solution.** Netting-by-CSA mirrors the legal reality. `REALITY CHECK`: no CCP/cross-product netting; one asset class per netting set.

---

## 6.2 Margin Period of Risk (MPoR) — and the fix in this app

**The concept (this is subtle and a favourite interview topic).** A CSA does **not** make exposure zero. When a counterparty defaults, there's a **close-out window** — the **Margin Period of Risk**, typically **10 business days** — during which you've stopped receiving fresh margin but the market keeps moving. The collateral you hold reflects the MTM as of the **last successful margin call** (`t − δ`), while your actual exposure is `MTM(t)`. The residual **gap risk** is `MTM(t) − Collateral(t−δ)`.

**Why it's needed.** Collateralised exposure (and therefore CVA/EAD on margined books) is driven *entirely* by this gap. Mis-modelling the MPoR mis-states the whole collateralised book.

**How this app uses it — and the bug that was fixed.** `src/csa/collateral.py` lags collateral to `t − δ`. The original code computed the lag as `round(δ / Δt)` grid steps, clamped to a 1-step minimum. On the coarse grids the engine actually runs (Δt ≈ 1 month), a 10-day MPoR **rounded to a whole grid step** — so the close-out window was set by the *plotting resolution*, not the CSA. The fix:
1. **Exact tenor:** interpolate MTM at the precise `t − δ` (no integer rounding, no min-1-step clamp) — MPoR is now a continuous parameter.
2. **Diffusion correction:** pure interpolation between coarse nodes *understates* the gap's variance by `√(δ/Δt)` (the dangerous direction — under-reserving). The gap is rescaled by **`√(Δt_local/δ) ≥ 1`** so its variance matches a true δ-horizon move. It's a **no-op once the grid already resolves δ**, so a fine grid recovers the exact answer. Validated: corrected gap variance = 0.999× the true value, vs 2.5× (old) and 0.4× (naive interpolation).

**Why this solution.** It makes collateralised exposure *resolution-independent* without forcing an expensive fine global grid. `REALITY CHECK` (note the audit got this backwards): the correct multiplier is **`√(Δt/δ)`**, not `√(δ/Δt)`. The fully exact alternative — simulating an extra path node at every `t−δ` — is a larger change that wasn't done; this two-moment correction is the pragmatic fix.

---
---

# PART 7 — REGULATORY CAPITAL

## 7.1 SA-CCR (the standardised EAD)

**The concept.** Basel requires an **Exposure at Default** for capital. **SA-CCR** (Standardised Approach for Counterparty Credit Risk) is the formula for banks without internal-model approval:
```
EAD = α · (RC + PFE) ,   α = 1.4
```
- **RC (Replacement Cost):** current loss if the counterparty defaulted today (handles margined vs unmargined, threshold, MTA differently).
- **PFE add-on:** a forward-looking buffer built from **supervisory factors** (per asset class), **supervisory duration**, a **maturity factor**, and **maturity-bucket aggregation** with prescribed cross-bucket correlations; a **multiplier** gives credit for over-collateralisation.
- `α = 1.4` is a regulatory scaling constant.

**Why it's needed.** EAD → RWA → capital. It answers "how much capital does this trade consume?" and feeds KVA.

**How this app uses it.** `src/sa_ccr/regulatory.py` implements the full IR pipeline: RC (margined/unmargined), add-ons with supervisory factors, maturity buckets + correlations, the over-collateralisation multiplier, RBI risk weights, and portfolio aggregation across netting sets.

**Why this solution.** SA-CCR is **mandatory** for non-IMM banks; it's a faithful Basel implementation. `REALITY CHECK`: **Interest-Rate asset class only** (no FX/credit/equity/commodity add-ons), and hedging-set recognition is limited to maturity buckets.

---

## 7.2 RWA and RBI risk weights

**The concept.** **Risk-Weighted Assets** scale EAD by a counterparty **risk weight** reflecting credit quality: `RWA = EAD × RW`; capital = `RWA × capital ratio`.

**Why it's needed / how used.** The app uses the **Indian (RBI)** risk-weight table (e.g. PSU Bank 20%, NBFC 75%, Stressed 150%) and RBI's 10.5% capital ratio — INR-market specificity that signals you know your jurisdiction.

---

## 7.3 BA-CVA and FRTB SA-CVA (CVA capital)

**The concept.** Beyond default capital, Basel charges capital for **CVA volatility** (mark-to-market CVA risk). Two tiers:
- **BA-CVA (Basic Approach):** simple supervisory formula needing only EAD, effective maturity, and a sector×rating risk weight. Has a **reduced** form (no hedges) and a **full** form (with hedge benefit + supervisory floor). Aggregation: `K = √[(ρ·ΣSCVA)² + (1−ρ²)·ΣSCVA²]`, `ρ=0.5`.
- **FRTB SA-CVA (Standardised Approach):** the new **sensitivity-based** framework (Basel IV). Capital = aggregation of **CS-Delta** (credit-spread), **IR-Delta** (rates), **Vega** (vol), and **Curvature** (second-order vol) with prescribed risk weights and correlations.

**Why it's needed.** CVA capital is one of the largest charges for derivative-heavy banks; the Current-CVA → FRTB-CVA transition is the big regulatory change of the decade.

**How this app uses it.** `src/sa_ccr/ba_cva.py` (full BIS d424 sector×rating table) and `src/sa_ccr/frtb_cva.py` (CS/IR delta, vega, curvature), with `compute_from_eod_report()` bridging the existing EOD engine to FRTB capital.

**Why this solution.** Having *both* shows you understand the regulatory landscape. `REALITY CHECK`: FRTB uses a simplified **3 IR tenor buckets** (not the full 12), and CS01/IR01 are derived via a flat-hazard approximation.

---

## 7.4 Economic Capital — ASRF / Vasicek

**The concept.** **Economic Capital (EC)** is the *internal* capital needed to survive losses at a chosen confidence (e.g. **99.9%**) — i.e. **Unexpected Loss**. The **ASRF** (Asymptotic Single-Risk-Factor) / **Vasicek** model (which underpins Basel IRB) gives a closed form for the default rate under a stressed systematic factor:
```
EC = EAD · LGD · [ N( (N⁻¹(PD) + √R·N⁻¹(conf)) / √(1−R) ) − PD ]
```
where `R` is the asset correlation and `N` the normal CDF. Intuition: push the single common factor to its 99.9% bad tail and ask what fraction defaults.

**Why it's needed.** EC drives internal capital allocation and RAROC; it differs from regulatory capital and is the "true" economic risk measure.

**How this app uses it.** `src/economic_capital/econ_capital.py` implements the ASRF Unexpected-Loss formula with configurable confidence.

**Why this solution.** ASRF is *the* analytically tractable portfolio-credit model and the basis of Basel IRB. `REALITY CHECK`: single-name (no portfolio diversification via a multi-factor model), constant PD/LGD, no credit migration.

---
---

# PART 8 — WRONG-WAY RISK (WWR)

**The concept.** **Wrong-Way Risk** is when exposure and counterparty default are **positively correlated** — exposure tends to be *high exactly when the counterparty is most likely to default*. Two flavours:
- **General WWR:** macro correlation (e.g. exposure rises with rates, and the counterparty is rate-sensitive).
- **Specific WWR:** structural link (e.g. a company writing options on its own stock).
Standard CVA assumes independence, so WWR is an add-on.

**Why it's needed.** WWR is a real tail risk; **CRD IV Art. 291 / EBA** require banks to identify and stress it.

**How this app uses it — three levels of sophistication (a nice "evolution" story):**
1. **Deterministic multipliers** (`src/wwr/wwr_stress.py`): tag-based detection, multiply EE by 1.2× (general) / 1.5× (specific). Simple, regulatory-compliant as a stress overlay, but a "fudge factor."
2. **Gaussian copula** (`src/wwr/gaussian_copula_wwr.py`): couples default and exposure through a copula correlation — a genuine joint distribution.
3. **Stochastic intensity / Cox process** (`src/wwr/stochastic_intensity_wwr.py`) — *the rigorous one*: the default intensity `λ(t)` follows a **CIR** process `dλ = κ(θ−λ)dt + ξ√λ dW_λ` (mean-reverting, stays positive via full-truncation) **correlated** with the HW1F rate factor. Default times come from the **Cox (doubly-stochastic) construction**: `τ = inf{ t : ∫₀ᵗλ ds > E }`, `E~Exp(1)`. The WWR multiplier = `CVA(ρ)/CVA(ρ=0)`. `ρ>0` ⇒ wrong-way (multiplier >1); `ρ<0` ⇒ right-way (<1); `ρ=0` ⇒ exactly 1.

**Why this solution.** The Cox/CIR approach (Brigo–Pallavicini–Papatheodorou) is the academically correct way to make WWR emerge from *dynamics* rather than a multiplier — genuinely advanced (usually PhD-level credit material). The simpler two remain because they're fast and regulator-friendly as overlays.

---
---

# PART 9 — ADVANCED EXPOSURE: EXOTICS & MULTI-ASSET

## 9.1 Longstaff-Schwartz (LSM) — callable/Bermudan exposure

**The concept.** A **Bermudan** option can be exercised at several dates — its value depends on an optimal **early-exercise** decision, which forward Monte Carlo can't directly handle. **Longstaff-Schwartz (LSM)** solves this by **backward induction with regression**: at each exercise date, regress the (discounted) *continuation value* on basis functions of the state variable, and exercise wherever immediate payoff beats the regression-estimated continuation. The exercise decision reshapes the **exposure** profile.

**Why it's needed.** Callable trades (Bermudan swaptions, cancellable swaps) are among the **largest XVA line items** on a rates book; their EE is fundamentally different from European trades.

**How this app uses it.** `src/montecarlo/longstaff_schwartz.py`: HW1F state `x(t)`, exact bond pricing, **cubic-polynomial** regression `{1,x,x²,x³}` on in-the-money paths, standard backward induction, then EE/ENE/PFE from the stopped paths. Verified: Bermudan price ≥ European reference.

**Why this solution.** LSM is *the* market-standard American/Bermudan MC method; the cubic basis is the conventional choice.

---

## 9.2 Cross-currency swaps — 3-factor FX-XVA

**The concept.** A **cross-currency swap** exchanges fixed cashflows in two currencies plus a **final notional exchange** — which is fully exposed to FX. You need **three** correlated factors: domestic rate (HW1F, INR), foreign rate (HW1F, USD), and the FX spot (lognormal). The FX drift follows **covered interest parity**: `d log X = (r_d − r_f − ½σ²)dt + σ dW`.

**Why it's needed.** CCS carry the **largest** CCR exposures on most books (the back-end notional exchange). Moving from single-asset rates to multi-asset is the single biggest credibility jump.

**How this app uses it.** `src/montecarlo/cross_currency.py`: 3×3 correlation via **Cholesky**, CIP drift, fixed-vs-fixed MTM with notional exchange, full EE/PFE. Verified: INR depreciates when `r_d>r_f` (CIP holds), and PFE peaks **near maturity** (notional-exchange risk).

**Why this solution.** Lognormal FX + flat foreign curve is the standard textbook CCS exposure model. `REALITY CHECK`: no FX vol smile, no stochastic basis.

---

## 9.3 Equity derivatives — BSM, the vol smile, and GBM exposure

**The concept.** Equity options are priced with **Black-Scholes-Merton (BSM)** including a continuous **dividend yield** `q`. Real markets show a **skew** (OTM puts richer than calls), captured here by a **quadratic vol smile** in log-moneyness. The underlying is simulated as **Geometric Brownian Motion (GBM)**: `dS = (r−q)S dt + σ S dW`.

**Why it's needed.** Adds Equity as a second asset class and enables the hybrid cross-asset engine (9.5).

**How this app uses it.** `src/pricing/equity_options.py` (BSM, Greeks, implied vol, `EquityVolSmile`) and `src/montecarlo/equity_mc.py` (`EquityGBM` — correlated GBM paths, option/forward/TRS MTM, exposure). NSE Nifty/Bank-Nifty data feeds it. The option re-pricing across paths is **vectorised** (one NumPy broadcast instead of 164k scalar calls — ~600× faster).

**Why this solution.** BSM + a parametric smile + GBM is the right, lightweight equity-exposure stack for a prototype.

---

## 9.4 Heston — stochastic volatility `REALITY CHECK`

**The concept.** **Heston** makes volatility itself random: the variance `v(t)` follows a CIR process correlated with the spot:
```
dS = (r−q)S dt + √v · S dW₁
dv = κ(θ−v)dt + ξ√v dW₂ ,   corr(dW₁,dW₂) = ρ
```
This generates a realistic, persistent smile/skew that BSM can't. Options are priced by **Fourier inversion of the characteristic function** (complex-analysis integrals `P1, P2`), and the **Feller condition** `2κθ > ξ²` tells you whether variance can hit zero (affecting the simulation scheme — here a Quadratic-Exponential/Andersen scheme).

**Why it's needed.** Stochastic vol is the realistic equity dynamics; the char-function pricer is a classic hard quant benchmark (complex numbers, numerical integration).

**How this app uses it — and the honest truth.** `src/pricing/heston.py` (201 lines) implements the char-function pricer (`scipy.integrate.quad`), Feller check, least-squares calibration, and a QE Monte-Carlo scheme. **BUT:** grep confirms `heston.py` is **not imported anywhere** — not by the app, the exposure engine, the hybrid XVA, or even the tests. The **live** equity path uses **GBM + BSM + the quadratic smile**, *not* Heston.

> 🚩 **Interview-safe phrasing:** *"I implemented a standalone Heston module — characteristic-function pricing and a QE Monte-Carlo scheme — as a quant showcase. The live equity exposure pipeline currently runs GBM with a calibrated quadratic smile; wiring Heston into the exposure cube is the natural next step."*
> Do **not** say "my exposure engine uses Heston" or "I implemented local volatility" — the audit claims both, but the code shows Heston is unwired and **there is no local-vol implementation at all**.

---

## 9.5 Hybrid cross-asset XVA

**The concept.** A real netting set can hold **both** a rates swap and an equity trade. To value them together you need **one joint simulation** with a consistent time grid and a **rate–equity correlation**, then net the *combined* MTM. The headline result is **cross-asset diversification**: hybrid CVA ≤ sum of standalone CVAs (sub-additivity), with the netting benefit depending on the correlation.

**Why it's needed.** It's the qualitative jump from a "rates XVA engine" to a "**multi-asset** XVA engine" — exactly what a central CVA desk is.

**How this app uses it.** `src/xva/hybrid_xva.py` (`HybridXVAEngine`): joint correlated simulation (HW1F rate factor + GBM equity), a mixed netting set, netted exposure, hybrid CVA/DVA/FVA, and a correlation slider showing the diversification benefit. Verified sub-additive.

**Why this solution.** Enforcing a shared time grid and path-mapping across two different stochastic engines (HW1F + GBM) is the correct architecture for cross-asset netting — and is the system-design highlight of the whole project.

---
---

# PART 10 — THE INSTITUTIONAL WORKFLOW LAYER

This is the layer that turns "analytics" into a "platform" — the governance that decides whether a trade actually happens.

## 10.1 Incremental XVA — the identical-path trick
**Concept.** Pre-trade, you need the **marginal** XVA of adding *one* trade to the book: `ΔXVA = XVA(book+trade) − XVA(book)`. **Why it's needed:** that's the price the XVA desk charges the trader. **How/why:** `src/workflow/incremental_xva.py` re-uses the **identical Monte Carlo paths** (shared seed) for both portfolios so the MC noise **cancels** in the difference — otherwise the noise (often larger than the signal) swamps the marginal number. This identical-path trick is the subtle, essential insight.

## 10.2 Counterparty Limits — RAG
**Concept.** Every counterparty has credit **limits** (on EAD/PFE). **Why:** no trade executes without a limit check. **How:** `src/limits/limit_engine.py` classifies utilisation **GREEN (<80%) / AMBER (>80%) / RED (>100%)** per legal entity.

## 10.3 RAROC & EVA
**Concept.** **RAROC** = Risk-Adjusted Return on Capital = `(Revenue − Expected Loss − Costs − XVA) / Capital`; **EVA** = Net income − Hurdle × Capital. **Why:** banks only approve trades that clear the **hurdle rate** on the capital they consume. **How:** `src/raroc/raroc_engine.py`, with pre-trade accretion ("does this trade improve portfolio RAROC?").

## 10.4 Trade Approval Workflow
**Concept.** The "last mile": orchestrate **Incremental XVA → Limit check → RAROC** into an automated **APPROVED / REJECTED / MANUAL_REVIEW** decision. **Why:** analytics that don't drive a decision are just information. **How:** `src/workflow/trade_approval.py` (+ REST endpoint, DB model). The value is the *connection* of the engines, not the maths.

## 10.5 PnL Attribution (Product Control)
**Concept.** Decompose a day's P&L into **Carry, Roll-Down, Delta (ΣDV01·Δrate), Gamma (½ΣΓ·Δrate²), New Fixing, Unexplained**. **Why:** Product Control verifies trader P&L; large "Unexplained" (>~10%) triggers investigation. **How:** `src/xva/pnl_attribution.py`; correct **ordering** (carry → roll → delta → gamma) is what makes the waterfall balance.

## 10.6 XVA Attribution
**Concept.** Explain the day's CVA move: **Spread, Exposure, Time-Decay (theta), Unexplained** via a first-order Taylor expansion that must sum to the total. **Why:** the XVA desk must explain CVA P&L to management. **How:** `src/xva/attribution.py`, `src/workflow/exposure_attribution.py`.

## 10.7 Stress Testing
**Concept.** Re-run all metrics under **parallel shocks (±50/100/200bp), steepeners/flatteners, credit-spread stress, combined scenarios**. **Why:** ICAAP/SREP and RBI mandate it. **How:** `src/stress/stress_testing.py`. `REALITY CHECK`: no reverse stress, no historically-calibrated crisis scenarios (2008/2013).

## 10.8 Exposure Backtesting — Kupiec & traffic light
**Concept.** To earn **IMM** approval you must prove your model's PFE isn't optimistic: count **breaches** (realised exposure > predicted PFE), run the **Kupiec Proportion-of-Failures** likelihood-ratio test, and assign the **Basel traffic-light** zone (GREEN/AMBER/RED) with its capital multiplier (1.00→1.33). **Why:** core regulatory model-validation. **How:** `src/validation/exposure_backtest.py`; verified a calibrated model passes (GREEN) and an understated one fails (RED). `REALITY CHECK`: "realised" exposures are resampled from the model's own MC (no live trading P&L).

## 10.9 IFRS 13 Accounting view
**Concept.** XVA isn't just risk — it hits the **balance sheet**. IFRS 13 needs a **fair-value reserve** (`FV adj = −CVA + DVA − FVA − MVA − KVA`), a **fair-value hierarchy** (Level 2 = observable e.g. CVA from CDS; Level 3 = model-dependent e.g. FVA/KVA), and **day-over-day P&L attribution**. **Why:** Product Control/Finance consume XVA this way; shows business context, not just maths. **How:** `src/xva/ifrs13.py`.

## 10.10 Management Reporting & Model Validation
**Concept.** Consolidated daily report with **RAG** governance status (`src/reporting/management_report.py`), plus an **8-test model-validation** battery (MC convergence, antithetic effectiveness, CVA-vs-analytic, positive forwards/no-arbitrage, SA-CCR maturity factor, HW term-structure fit, negative-rate frequency) in `src/validation/model_validator.py`. **Why:** boards need risk-appetite monitoring; **MRM** requires independent validation. `REALITY CHECK`: validation uses the same engine (no independent challenger model).

---
---

# PART 11 — HONEST CAVEATS (your anti-embarrassment checklist)

Memorise these — they're where a sharp interviewer probes, and owning them *raises* your credibility:

1. **Measure mismatch (the big one).** `σ` is calibrated from **historical MIBOR (P-measure)** but used for **risk-neutral (Q-measure)** exposure/XVA. Correct calibration is to **swaption-implied** vols (paid data). Know the direction and why it matters.
2. **Synthetic credit.** India has **no liquid single-name CDS**; the spreads driving CVA are a **rating-based synthetic ladder**. A real INR desk proxies credit from bond asset-swap spreads.
3. **No swaption vol surface.** SABR's ATM anchor is **realised**, not implied vol.
4. **Single-curve default.** The multi-curve framework exists but the default exposure run uses the **single-curve float shortcut** (ignores OIS–MIBOR basis).
5. **HW1F is single-factor & Gaussian.** No curve-shape risk; rates can go negative; the "floor" is cosmetic (MTM prices off the unfloored factor). HW2F exists but doesn't drive the headline CVA.
6. **FVA/DVA overlap.** The app books **both** DVA and FBA, which economically overlap — be ready to defend or flag it.
7. **Heston is unwired; there is no local vol.** The audit overclaims both. Live equity = GBM + BSM + quadratic smile. (See 9.4 for safe phrasing.)
8. **SA-CCR / SIMM / FRTB-CVA are IR-scoped & simplified.** SA-CCR is IR-only; SIMM is IR-Delta only; FRTB-CVA uses 3 tenor buckets not 12.
9. **MPoR correction is two-moment.** The fix makes collateralised exposure resolution-independent (multiplier `√(Δt/δ)`, *not* the audit's inverted `√(δ/Δt)`), but the *exact* fix is to simulate a node at each `t−δ`.
10. **Free-data demo runs on fallbacks.** Outside India you're usually on calibrated synthetic levels, not live quotes.

---

## HOW TO NARRATE THE WHOLE APP IN 60 SECONDS

> *"It's an INR multi-asset CCR/XVA engine. It pulls free Indian market data, bootstraps an OIS discount curve, and runs a Hull-White Monte Carlo to simulate thousands of future rate paths. On each path it reprices the trades using exact Hull-White bond pricing to build an exposure cube, from which it computes EE/PFE/EEPE. It applies CSA collateral with a proper Margin-Period-of-Risk close-out, nets by counterparty, then layers the full XVA stack — CVA, DVA, FVA, KVA, MVA — with AAD sensitivities for hedging. On top it computes regulatory capital (SA-CCR, BA-CVA, FRTB SA-CVA, ASRF economic capital), models wrong-way risk up to a Cox-process stochastic-intensity model, and handles exotics and multi-asset — Bermudans via Longstaff-Schwartz, cross-currency swaps, and a hybrid rates+equity netting set. Finally a governance layer — incremental XVA, limits, RAROC, automated trade approval, P&L and CVA attribution, stress testing, IMM backtesting, and IFRS-13 reporting — turns the analytics into an actual approve/reject decision. It's all free-data and CPU-only, so the honest gaps are paid vol surfaces, real CDS, and GPU scale."*

*End of Master Concept Guide.*
