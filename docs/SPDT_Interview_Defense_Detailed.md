# SPDT — Interview Defense & Derivations (The Master Answer Key)

> This is the **answer key**. For every "Defend it" question in the layer walkthrough — plus the
> wider set of questions an **equity structuring / exotics / quant** interview will throw at you —
> this document gives the *full* answer: the concept, the derivation from first principles, and the
> intuition. The spec said it best: *"the math is the asset."* Being able to **derive** these, out
> loud, from scratch, is the real deliverable.
>
> **How to use it:** cover the answer, try to derive it yourself on paper, then check. If you can't
> reproduce a derivation unaided, you don't own it yet. Companion to `SPDT_Layer_Walkthrough.md`.

## Contents
- [Part I — Foundations: risk-neutral pricing, BS, Greeks](#part-i--foundations)
- [Part II — Volatility: implied vol, SVI/SSVI, arbitrage, Dupire](#part-ii--volatility)
- [Part III — Correlation & multi-asset](#part-iii--correlation--multi-asset)
- [Part IV — Products & decomposition](#part-iv--products--decomposition)
- [Part V — Numerical methods: Monte Carlo, PDE, barriers](#part-v--numerical-methods)
- [Part VI — Models: Heston & LSV](#part-vi--models-heston--lsv)
- [Part VII — Greeks: bump, pathwise, LR, AAD](#part-vii--greeks-the-four-methods)
- [Part VIII — Structuring: price-to-par](#part-viii--structuring)
- [Part IX — Risk: hedging, P&L attribution, reserves, stress](#part-ix--risk-management)
- [Part X — Data & backtesting](#part-x--data--backtesting)
- [Part XI — Broad equity-structuring interview questions](#part-xi--broad-equity-structuring-questions)
- [Part XII — Project-level & behavioural questions](#part-xii--project-level-questions)

### Notation
`S` spot, `K` strike, `T` maturity, `r` risk-free rate, `q` dividend yield, `σ` volatility,
`F = S e^{(r−q)T}` forward, `N(·)` standard-normal CDF, `n(·)` its density, `W_t` Brownian motion,
`E^Q[·]` expectation under the risk-neutral measure `Q`, `Δ Γ ν Θ ρ` the Greeks.

---

# Part I — Foundations

## I.1 Risk-neutral pricing — the Fundamental Theorem of Asset Pricing (FTAP)

**Q: What does it mean to "price" a derivative? Why discount expected payoff under a special measure?**

**Concept.** The First FTAP: *a market is arbitrage-free if and only if there exists an equivalent
martingale measure `Q`* under which **discounted** tradable asset prices are martingales. The Second
FTAP: that measure is **unique** iff the market is **complete** (every payoff is replicable). Under
`Q`, the price of any attainable payoff `H` maturing at `T` is

```
V_0 = E^Q[ e^{−rT} H ].
```

**Why it works (replication intuition, the real engine).** Pricing is *not* about predicting the
real-world expected payoff. It is about **replication cost**. If I can build a self-financing trading
strategy in the underlying + bond that reproduces `H` at `T`, then by no-arbitrage the derivative
must cost exactly what that strategy costs today. The "risk-neutral expectation" is just the
mathematical bookkeeping of that replication cost.

**Why the drift becomes `r`.** Under `Q`, every asset earns the risk-free rate (the real-world drift
`μ` is replaced by `r`). This is Girsanov's theorem: changing measure shifts the Brownian drift but
leaves the volatility (the quadratic variation) unchanged. Volatility is measure-invariant — which is
*why* options, which are bets on volatility, can be priced without knowing `μ`. **This is the single
most important idea in derivatives.**

**The defend-it punchline.** "We don't price with real-world probabilities because we're not betting
— we're hedging. The price is the cost of the replicating hedge, and the risk-neutral measure is the
unique reweighting of outcomes that makes that cost equal a discounted expectation."

## I.2 Deriving the Black-Scholes PDE (delta-hedging argument)

**Setup.** Underlying follows geometric Brownian motion under the real measure:
`dS = μS dt + σS dW`. Let `V(S,t)` be the derivative value. By **Itô's lemma**,

```
dV = (V_t + μS V_S + ½σ²S² V_SS) dt + σS V_S dW.
```

**Build a riskless portfolio.** Hold the option and short `Δ` units of the stock: `Π = V − ΔS`.

```
dΠ = dV − Δ dS = (V_t + μS V_S + ½σ²S² V_SS) dt + σS V_S dW − Δ(μS dt + σS dW).
```

Choose `Δ = V_S`. The `dW` term (and the `μ` term) **cancels** — the portfolio is instantaneously
riskless:

```
dΠ = (V_t + ½σ²S² V_SS) dt.
```

**No-arbitrage.** A riskless portfolio must earn `r`: `dΠ = rΠ dt = r(V − S V_S) dt`. Equate:

```
V_t + ½σ²S² V_SS = r(V − S V_S)
⟹  V_t + rS V_S + ½σ²S² V_SS − rV = 0.     ← the Black-Scholes PDE
```

With dividends `q`, the drift term becomes `(r−q)S V_S`. Terminal condition `V(S,T) = payoff(S)`.

**Key insight to state:** `μ` vanished. The hedge removed exposure to the stock's direction; only its
*volatility* matters. Same conclusion as I.1, via PDE instead of measure.

## I.3 The Black-Scholes formula and its Greeks

Solving the PDE for a European call (or taking `E^Q[e^{−rT}(S_T−K)^+]` with lognormal `S_T`):

```
C = S e^{−qT} N(d₁) − K e^{−rT} N(d₂),
d₁ = [ln(S/K) + (r − q + ½σ²)T] / (σ√T),     d₂ = d₁ − σ√T.
```

Put: `P = K e^{−rT} N(−d₂) − S e^{−qT} N(−d₁)`.

**A crucial identity** (used everywhere, e.g. vega, and worth being able to show):
`S e^{−qT} n(d₁) = K e^{−rT} n(d₂)`. *(Proof: take the ratio `n(d₁)/n(d₂) = exp(−½(d₁²−d₂²))`; since
`d₁²−d₂² = (d₁−d₂)(d₁+d₂) = σ√T·(d₁+d₂)`, substitute `d₁+d₂` and simplify — the stock and discounted
strike terms balance.)*

**The Greeks** (call; differentiate the formula):

| Greek | Formula | Meaning |
|---|---|---|
| Delta `Δ` | `e^{−qT} N(d₁)` | ∂V/∂S — hedge ratio |
| Gamma `Γ` | `e^{−qT} n(d₁) / (Sσ√T)` | ∂²V/∂S² — convexity; **identical for call & put** |
| Vega `ν` | `S e^{−qT} n(d₁) √T` | ∂V/∂σ — **identical for call & put**, always ≥ 0 |
| Theta `Θ` | `−[S e^{−qT} n(d₁) σ]/(2√T) − rKe^{−rT}N(d₂) + qSe^{−qT}N(d₁)` | ∂V/∂t |
| Rho | `KT e^{−rT} N(d₂)` | ∂V/∂r |

**The fundamental relation linking them** (substitute the Greeks back into the PDE):

```
Θ + (r−q)S·Δ + ½σ²S²·Γ − rV = 0.
```

This is the algebraic seed of the **gamma-theta trade-off** (see IX.2) and of **P&L attribution**
(IX.3). Commit it to memory.

## I.4 Put-call parity, forwards, and dividends

**Put-call parity** (model-free — pure no-arbitrage): a call minus a put replicates a forward.

```
C − P = S e^{−qT} − K e^{−rT}.
```

*Proof:* portfolio A = long call + `Ke^{−rT}` cash; portfolio B = long put + `e^{−qT}` shares. At `T`
both are worth `max(S_T, K)`. Equal payoffs ⟹ equal cost today. ∎

**Forward price:** `F = S e^{(r−q)T}` (cost-of-carry). Dividends lower the forward, raising puts and
lowering calls. **Dividend delta / dividend risk** is real for structured notes: a long-dated
autocallable is sensitive to the assumed dividend path, and discrete vs continuous dividend modelling
matters for barrier proximity.

---

# Part II — Volatility

## II.1 Implied volatility — definition, Newton vs Brent

**Q: What is implied vol and how do you invert for it? (Defend: Newton vs Brent.)**

Implied vol `σ_imp` is the unique `σ` solving `BS(σ) = C_market`. It exists and is unique because
**vega > 0 everywhere**, so `BS(σ)` is strictly increasing in `σ` — a monotone 1-D root.

**Newton's method:** `σ_{n+1} = σ_n − [BS(σ_n) − C_mkt] / vega(σ_n)`. Converges *quadratically* near
the root and we have vega in closed form, so it's cheap and fast — the default.

**Why it breaks on the wings → Brent.** Deep ITM/OTM options have `vega → 0` (n(d₁)→0). Newton's
update divides by a vanishing vega → it overshoots or diverges. **Brent's method** (bracketing +
inverse-quadratic interpolation) needs no derivative and is guaranteed to converge given a sign
change `[σ_lo, σ_hi]`. So: Newton for the liquid core, Brent as the robust fallback on the wings.

**Why settlement-price IVs are biased (defend).** Bhavcopy gives *settlement* prices, not traded
mids. Settlement ≠ mid, and on the wings the bid-offer is very wide, so the inverted IV is noisy and
biased there. State this honestly: your wing IVs carry the most uncertainty, which is exactly why you
flag provenance and don't over-trust them in calibration.

## II.2 Why a smile/skew exists at all

**Q: Black-Scholes assumes constant vol — why does the market show a skew?**

Three complementary reasons:
1. **Fat tails / non-normal returns.** Real returns have heavier tails than lognormal; OTM options
   (which pay only in the tails) are therefore worth more than BS-with-ATM-vol says → higher IV away
   from ATM.
2. **Leverage effect / crashophobia (equity skew).** Equities fall faster than they rise; firms'
   leverage rises as price drops, raising vol. So downside puts carry a premium → the characteristic
   *negative* equity skew (downside IV > upside IV).
3. **Supply/demand.** Structural hedging flows (investors buy downside protection, dealers sell it)
   bid up put IV. The skew is partly a risk-premium artefact, not just a probabilistic one.

## II.3 SVI and SSVI — parametrising the surface

**Raw SVI (one slice), in total variance `w = σ²T` and log-moneyness `k = ln(K/F)`:**

```
w(k) = a + b[ ρ(k − m) + √((k − m)² + σ²) ].
```

Five params: `a` (level), `b` (wing slope, ≥0), `ρ∈(−1,1)` (skew/tilt), `m` (shift), `σ>0`
(curvature). Asymptotically linear wings (`w ~ a + b(±1+ρ)(k−m)`), smooth ATM — exactly the observed
shape. Fit by least squares to observed total variance per maturity.

**SSVI (whole surface):**

```
w(k, θ_T) = (θ_T/2)( 1 + ρφ(θ_T)k + √( (φ(θ_T)k + ρ)² + (1 − ρ²) ) ),
```

where `θ_T` is the ATM total variance term structure and `φ(θ)` a shape function (power-law
`φ(θ)=η θ^{−λ}` or Heston-like). **Why SSVI:** it is **calendar-arbitrage-free by construction** under
simple conditions (e.g. `θ_T` nondecreasing and a bound on `∂(θφ)`). Independent SVI slices give no
such guarantee and can cross. (See II.5.)

## II.4 Butterfly arbitrage and Durrleman's condition

**Q: What is butterfly arbitrage and how do you detect it?**

A vertical **butterfly** (long `K−ΔK`, short 2× `K`, long `K+ΔK`) costs, in the limit,
`∝ ∂²C/∂K²`. Its payoff is ≥ 0 always, so its price must be ≥ 0 ⟹ **`∂²C/∂K² ≥ 0`**. But by the
Breeden-Litzenberger result, the risk-neutral density is

```
p(K, T) = e^{rT} ∂²C/∂K².
```

So **butterfly-arbitrage-free ⟺ density ≥ 0 everywhere.** A too-curved/wiggly smile produces a
*negative* implied density — nonsense (negative probability), and a literal arbitrage.

**In SVI terms — Durrleman's condition.** Translating `p ≥ 0` into total-variance space gives a
condition `g(k) ≥ 0` for all `k`, where

```
g(k) = (1 − k w'/(2w))² − (w'/2)²(1/w + 1/4) + w''/2.
```

You evaluate `g` on a dense `k`-grid after each fit; if it dips below 0, you re-fit with constrained
SVI parameters (or use SSVI sub-conditions) until `g ≥ 0`.

## II.5 Calendar arbitrage

**Q: What is calendar arbitrage?**

**Total variance must be nondecreasing in maturity at fixed (forward) moneyness:**
`∂w(k,T)/∂T ≥ 0`. Intuition: a longer-dated option contains a shorter-dated one plus more time —
more uncertainty can only add value. If two SVI slices **cross** in total-variance space, there's a
calendar spread that's worth negative money to set up but always pays ≥ 0 — free money. Equivalently
in price space, `∂C/∂T ≥ 0` (with the carry adjustment). SSVI removes this by tying all slices to a
single nondecreasing `θ_T`.

> **Summary you must nail:** *butterfly* = static, within a maturity, density ≥ 0, Durrleman test;
> *calendar* = across maturities, total variance ↑ in T, slice non-crossing. SVI controls butterfly
> per slice; SSVI controls calendar by construction.

## II.6 Dupire local volatility — full derivation

**Q: Derive the Dupire formula. Why compute derivatives on the parametrised surface?**

**Goal.** Find the *unique* deterministic local vol function `σ_LV(S,t)` such that the model
`dS = (r−q)S dt + σ_LV(S,t) S dW` reproduces *all* European option prices `C(K,T)`.

**Derivation (forward equation route).** The risk-neutral density `p(S,T)` of the local-vol diffusion
satisfies the **Fokker-Planck (forward Kolmogorov) equation**:

```
∂p/∂T = −∂/∂S[(r−q)S p] + ½ ∂²/∂S²[σ_LV²(S,T) S² p].
```

Start from `C(K,T) = e^{−rT} ∫_K^∞ (S−K) p(S,T) dS`. Differentiate:

- `∂C/∂K = −e^{−rT} ∫_K^∞ p dS`  (so `∂²C/∂K² = e^{−rT} p(K,T)` — Breeden-Litzenberger).
- `∂C/∂T`: differentiate under the integral, substitute the Fokker-Planck expression for `∂p/∂T`,
  and integrate by parts twice (boundary terms vanish). After collecting terms you obtain:

```
∂C/∂T = ½ σ_LV²(K,T) K² ∂²C/∂K² − (r−q)K ∂C/∂K − qC.
```

Solve for the local variance:

```
┌─────────────────────────────────────────────────────────────┐
│  σ_LV²(K,T) = [ ∂C/∂T + (r−q)K ∂C/∂K + qC ] / [ ½ K² ∂²C/∂K² ] │
└─────────────────────────────────────────────────────────────┘
```

**Why use the SVI/SSVI parametrisation, not raw quotes (the defend-it).** The formula needs `∂C/∂T`,
`∂C/∂K`, and especially `∂²C/∂K²`. Finite-differencing **raw, noisy quotes** for a *second*
derivative amplifies noise catastrophically — the denominator `∂²C/∂K²` is tiny and the result
explodes or goes negative (implying imaginary vol). Computing the derivatives **analytically off the
smooth, arbitrage-free SVI/SSVI surface** (best done directly in total-variance space, where Dupire
has a clean closed form `σ_LV² = ∂w/∂T / [ (1 − k w'/2w)² − ¼(w'/4 + ... ) ... ]`) is stable and
guaranteed non-negative when the surface is arb-free.

**What it buys you and what it doesn't.** By construction LV reprices *every vanilla exactly*. But it
imposes deterministic dynamics — see II.7 and VI.4.

## II.7 Forward smile and the local-vol pathology

**Q: What's the forward smile, and why does it matter?**

The **forward smile** is the implied-vol smile of a *future* return `S_{T₂}/S_{T₁}` as seen today
(the smile that will be observed at `T₁` for options expiring `T₂`, in expectation). **Local vol
flattens the forward smile**: as time passes, an LV model predicts the future smile becomes nearly
flat, contradicting markets (which stay skewed). Stochastic-vol / LSV models keep the forward smile
alive because vol can re-randomise. This is *the* reason forward-smile-sensitive products
(autocallables, cliquets, forward-starts) need more than LV — and the seed of the **model reserve**
(IX.4).

## II.8 Stickiness regimes

**Q: Sticky-strike vs sticky-delta — which does your delta assume?**

- **Sticky-strike:** the IV at each *fixed strike* stays constant as spot moves. Then BS delta is the
  full delta.
- **Sticky-delta (sticky-moneyness):** the smile rides along with spot — IV at fixed *moneyness*
  `K/S` is constant. Then a spot move also shifts the relevant IV, adding a `vega × ∂σ/∂S` term to
  delta (the "skew delta").

It matters because the *same option* has a different hedge ratio under each regime. Equity markets
are often closer to sticky-delta in calm regimes and sticky-strike in jumps. Your delta is only as
good as the regime assumption baked into it — state which one your engine uses.

---

# Part III — Correlation & multi-asset

## III.1 Estimating correlation; implied correlation

**Historical / EWMA:** sample correlation of log-returns; EWMA weights recent data
`σ²_t = (1−λ)r²_{t−1} + λσ²_{t−1}` (similarly for covariances) to capture regime shifts.

**Implied correlation (derive).** Index variance in terms of constituents:

```
σ²_idx = Σᵢ wᵢ²σᵢ² + Σ_{i≠j} wᵢwⱼσᵢσⱼρ_{ij}.
```

Assume a single average pairwise `ρ` and solve:

```
ρ_implied = ( σ²_idx − Σᵢ wᵢ²σᵢ² ) / ( Σ_{i≠j} wᵢwⱼσᵢσⱼ ).
```

This is what a **dispersion** desk trades: sell index vol / buy single-name vol when implied
correlation is "too high." Worst-of structured notes are inherently **short correlation** for the
issuer in a specific sense (see IV.4).

## III.2 PSD repair — why, and Higham

**Q: Why does a shocked correlation matrix break PSD, and what goes wrong?**

A valid correlation matrix is symmetric, unit-diagonal, and **positive semi-definite (PSD)** (all
eigenvalues ≥ 0). Estimating entries pairwise, or **shocking** them in a stress scenario
(e.g. "set all ρ = 0.9"), easily produces a matrix with a **negative eigenvalue**. Then:
- **Cholesky fails** (no real `LLᵀ`), or
- you get **negative variance / imaginary "vols"** when generating correlated draws → simulation
  produces nonsense.

**Higham (2002) nearest-correlation-matrix** via alternating projections: repeatedly project onto
(a) the set of symmetric PSD matrices (clip negative eigenvalues to 0 in the spectral
decomposition) and (b) the set of unit-diagonal matrices, iterating to the closest valid correlation
matrix in Frobenius norm. ~30 lines; a strong, cheap signal.

## III.3 Copulas and tail dependence

**Q: Gaussian vs t copula — why does it matter for worst-of products?**

A copula separates *marginals* from the *dependence structure*. **Gaussian copula** (correlate via
Cholesky of ρ, map through normal CDFs) has **zero tail dependence**: extreme joint moves are
asymptotically independent. But equities **crash together**. **t-copula** adds a single chi-square
mixing variable (heavy-tailed radial component), giving **nonzero tail dependence** — joint crashes
are far more likely. For a **worst-of**, the payoff is driven by the *worst* performer in bad states,
so underestimating joint crash probability (Gaussian) **mis-prices the downside**. Use the t-copula
(or a jump/SV model with correlated shocks) when tails drive the payoff.

---

# Part IV — Products & decomposition

## IV.1 The golden rule: a note is a portfolio of options

Every structured note = **bond + coupons ± options**. Decomposing it tells you instantly *who is long
what optionality*, hence the risk the issuer must hedge.

## IV.2 Autocallable — decomposition and risks

An autocallable is, for the **investor**: a yield-enhancement note where they are **short a
down-and-in put** (they absorb the crash) and **short an up-and-out / digital call structure** (their
upside is capped and called away). For the **issuer/desk** it's the mirror: **long the KI put**
(long downside protection they must hedge), **short the coupon stream**. Key exposures for the issuer:
- **Short vega** overall (selling optionality), especially **short skew** near the KI.
- **Short gamma near the barrier** — the delta flips violently as spot approaches the KI.
- **Long correlation** sensitivity if multi-asset (worst-of).
- **Gap / pin risk** at the barrier.

## IV.3 Phoenix and the memory coupon

**Q: Why do memory coupons increase the note's value to the investor?**

A **memory coupon** pays not only the current coupon but **all previously missed coupons** the first
time the barrier is regained. This is strictly *more* cashflow than a plain conditional coupon (it can
never pay less), so it **raises the note's value to the investor** — and therefore the desk must
*lower another parameter* (e.g. raise the KI risk or cut the headline coupon) to bring it back to par.
Mechanically the memory feature is extra path-dependent optionality the issuer is **short**, deepening
the issuer's short-vol/short-skew exposure.

## IV.4 Barrier Reverse Convertible (BRC) — exact decomposition

```
BRC (investor) = ZeroCouponBond(100)        ← principal, discounted
              + FixedCoupon(c)              ← high coupon = the premium for...
              − DownAndIn Put(K=100, barrier=KI)   ← ...selling a knock-in put
```

So the **investor is SHORT a knock-in put**: they receive a fat coupon as the put premium, and lose
capital if the barrier is breached (the put knocks in and they're short it). The **issuer is LONG the
KI put** and hedges it. A plain **reverse convertible** is the same without the barrier (short a
vanilla put). This decomposition is the cleanest possible demonstration that you understand structured
notes — be able to draw it instantly.

## IV.5 Capital-protected note

```
Capital-protected note = ZeroCouponBond(protection level)   ← guarantees principal back
                       + Participation × Call(K = S₀)        ← the upside
```

The bond floor consumes most of the premium; whatever's left buys participation in the call. Low rates
→ expensive bond floor → little left for upside (why these sell poorly in low-rate regimes).

## IV.6 Barrier monitoring & the Broadie-Glasserman-Kou correction

**Q: Continuous vs discrete monitoring? State the BGK correction.**

A barrier monitored **continuously** is breached if the path *ever* crosses it; **discretely** only if
it's beyond the barrier *on observation dates*. Discrete monitoring breaches **less often** → a
down-and-in is worth *less* discretely than continuously. **Broadie-Glasserman-Kou (1997)** showed a
discretely-monitored barrier price ≈ the *continuous* price with the barrier **shifted**:

```
H_adj = H · exp( ± β σ √Δt ),     β = −ζ(½)/√(2π) ≈ 0.5826,
```

with `Δt` the monitoring interval and the sign chosen to move the barrier *away* from the spot (up for
an upper barrier, down for a lower). It's a remarkably accurate first-order fix and a great detail to
quote.

---

# Part V — Numerical methods

## V.1 Monte Carlo — why it works and its error

Price `= E^Q[e^{−rT}H]`. MC estimates the expectation by the sample mean over `N` simulated paths.
By the **CLT**, the estimator's standard error is `≈ σ_H / √N` — i.e. error `∝ 1/√N`: to halve the
error you need **4×** the paths. This slow rate is *why* variance reduction matters.

**One step of a GBM path (exact, no discretisation bias for GBM):**

```
S_{t+Δt} = S_t · exp[ (r − q − ½σ²)Δt + σ√Δt · Z ],   Z ~ N(0,1).
```

(The `−½σ²` is the Itô correction so that `E[S_{t+Δt}] = S_t e^{(r−q)Δt}`.)

## V.2 Variance reduction (each, with the mechanism)

- **Antithetic variates:** use `Z` and `−Z`. For a monotone payoff the two estimates are negatively
  correlated, so the average has lower variance. Free (halves the normal draws).
- **Control variate:** pick a `Y` with known `E[Y]` correlated with payoff `X`; estimate
  `X − c(Y − E[Y])` with optimal `c = Cov(X,Y)/Var(Y)`. Pricing a vanilla analytically as the control
  for an exotic can cut variance by an order of magnitude.
- **Sobol (quasi-MC):** low-discrepancy points fill `[0,1]^d` more evenly than pseudo-random; error
  improves toward `~ (log N)^d / N` (close to `1/N`) for smooth, low-effective-dimension problems.
- **Brownian bridge:** construct the path by filling in the *most important* time points first
  (terminal, then midpoints), so the leading Sobol dimensions carry the most variance — reduces
  effective dimension, making Sobol far more effective.
- **Importance sampling:** shift the sampling measure toward the region that matters (deep
  barrier/digital tails) and reweight by the likelihood ratio — slashes variance for rare-event
  payoffs.

## V.3 Common Random Numbers (CRN) — why mandatory for bump Greeks

**Q: Why is CRN essential for finite-difference Greeks?**

A bumped Greek is `[V(θ+ε) − V(θ−ε)] / 2ε`. If the two repricings use **different** random paths,
each carries MC noise `~σ_H/√N`; the difference divides that noise by `2ε`, which is *tiny* — the
Greek is swamped by Monte Carlo noise. With **CRN** (same seed/paths for both), the *common* noise
cancels in the subtraction, leaving the true sensitivity. Variance of the difference drops from
`O(σ²/N)/ε²` to `O(1)`-controlled. Without CRN, bump Greeks for path-dependents are essentially
unusable.

## V.4 PDE / Crank-Nicolson and the curse of dimensionality

For 1-D (one underlying) low-path-dependence payoffs, solve the BS/LV PDE on a grid with
**Crank-Nicolson** (average of explicit + implicit; second-order accurate in time, unconditionally
stable). Cost `O(space × time)`. But the grid is `O(M^d)` in `d` underlyings — the **curse of
dimensionality** — so PDEs die beyond ~2–3 dimensions. Baskets / worst-of / many-observation
autocallables ⟹ Monte Carlo, whose cost is roughly linear in dimension.

---

# Part VI — Models: Heston & LSV

## VI.1 Why go beyond Black-Scholes / Local Vol

BS: constant vol, no smile. LV: fits today's smile exactly but has **deterministic** vol → wrong
*dynamics* (flat forward smile, mis-hedges forward-vol products). **Stochastic vol (Heston)**: right
kind of dynamics (vol is random, smile persists) but **can't fit the whole spot smile exactly**,
especially short-dated wings. **LSV**: combine them — fit the smile *exactly* (like LV) **and** have
realistic dynamics (like SV). That's why LSV is the production standard.

## VI.2 Heston model and the QE scheme

```
dS = (r−q)S dt + √v S dW₁,
dv = κ(θ − v) dt + ξ√v dW₂,     d⟨W₁,W₂⟩ = ρ dt.
```

`κ` mean-reversion speed, `θ` long-run variance, `ξ` vol-of-vol, `ρ` spot/vol correlation (negative
for equity skew). **Feller condition** `2κθ ≥ ξ²` keeps `v > 0`.

**Q: Why not Euler on the variance? Why QE?**

A naïve Euler step `v_{t+Δt} = v_t + κ(θ−v_t)Δt + ξ√v_t √Δt Z` can go **negative** (then `√v` is
imaginary), and even with fixes (absorption/reflection) it's **biased**. Andersen's **Quadratic-
Exponential (QE)** scheme samples `v_{t+Δt}` from a moment-matched distribution: a **quadratic**
(squared-normal) form when variance is high, switching to an **exponential**-with-mass-at-zero form
when variance is low. It matches the exact conditional mean and variance of the CIR process, stays
nonnegative, and is far more accurate per step — the standard for Heston MC.

**Calibration via the characteristic function.** Heston has a closed-form characteristic function
`φ(u) = E[e^{iu ln S_T}]`. Vanillas price by Fourier inversion (**Carr-Madan FFT**):

```
C(k) = e^{−αk}/π · ∫₀^∞ e^{−iuk} ψ(u) du,   ψ(u) = e^{−rT}φ(u−(α+1)i) / (α²+α−u²+i(2α+1)u),
```

with damping `α` ensuring integrability. FFT prices a whole strip of strikes at once → fast
least-squares calibration of `(κ,θ,ξ,ρ,v₀)` to the market smile.

## VI.3 LSV and the leverage-function calibration (the hard part)

**Model:** `dS = (r−q)S dt + L(S,t)√v S dW₁`, with `v` a stochastic (Heston-like) variance and
`L(S,t)` the **leverage function**.

**Q: State and justify the leverage calibration identity. What is the conditional expectation?**

**Gyöngy's theorem (Markovian projection).** Any Itô process `dS = … dt + Σ_t S dW` has the *same
one-dimensional marginals* as the local-vol process whose local variance is the **conditional
expectation of the instantaneous variance given the spot**:

```
σ_LV²(K,T) = E[ Σ_T² | S_T = K ].
```

For the LSV diffusion, `Σ_t² = L²(S_t,t) v_t`, so

```
σ_Dupire²(K,T) = E[ L²(S_T,T) v_T | S_T = K ] = L²(K,T) · E[ v_T | S_T = K ].
```

Solve:

```
┌──────────────────────────────────────────────┐
│   L²(K,T) = σ_Dupire²(K,T) / E[ v_T | S_T=K ]  │
└──────────────────────────────────────────────┘
```

**Meaning of the conditional expectation.** `E[v_T | S_T=K]` is the *average level of stochastic
variance in those scenarios where the spot is at `K` at time `T`*. The leverage function `L` is the
multiplicative correction that "re-tunes" the stochastic-vol model's local behaviour so that, after
averaging over the stochastic vol, it reproduces the **exact Dupire local vol** — hence reprices all
vanillas. If `v` were frozen at 1, `L² = σ_Dupire²` and LSV collapses to LV; the SV part is what adds
correct dynamics on top.

**Why it's hard (the engineering).** `L` appears on *both* sides (it shapes the paths that define the
conditional expectation it's solved from) → a **fixed-point** problem solved **forward in time** with
the **particle method** (McKean): simulate many paths together, and at each time step estimate
`E[v|S=K]` by a **kernel-weighted (or binned) average over the particles** near `S=K`, set `L` from
the identity, step forward. This conditional-expectation estimation per step is the expensive,
delicate, highest-risk piece (your spec flags Week 14 — budget slack).

## VI.4 Why LV and LSV agree on vanillas but disagree on autocallables (THE model-reserve question)

**Q: They calibrate to the same smile — how can they disagree?**

- **Vanillas depend only on marginals.** A European payoff `f(S_T)` depends solely on the
  distribution of `S_T` at the single date `T`. By Gyöngy, LV and LSV share *all* one-dimensional
  marginals (that's *how* `L` was calibrated). So they price every vanilla **identically**. ✅
- **Path-dependent products depend on the joint law / dynamics.** An autocallable looks at the spot at
  *many* dates and at the **conditional** behaviour ("given we're here at `T₁`, how does vol behave to
  `T₂`?") — i.e. the **forward smile**. The marginals don't pin this down. LV says future vol is
  deterministic (flat forward smile); LSV keeps it stochastic (live forward smile). **Same marginals,
  different dynamics ⟹ different exotic prices.**

**The mind-bender to state crisply:** *Matching every snapshot of where prices may end up does not
determine how prices move between snapshots.* Two models can share all marginals and differ in the
joint law. Vanillas can't tell them apart; autocallables can.

**The reserve.** The price gap `|P_LSV − P_LV|` on the exotic is genuine model uncertainty. The desk
holds it as a **model reserve** — P&L it refuses to book because it can't justify it across plausible
models. Running multiple models is deliberate: the *spread between them* is the honest measure of
model risk.

---

# Part VII — Greeks: the four methods

## VII.1 Bump-and-revalue

Central difference with CRN: `Δ ≈ [V(S+h) − V(S−h)]/2h`, `Γ ≈ [V(S+h) − 2V(S) + V(S−h)]/h²`.
Pros: trivial, model-agnostic, works for any payoff. Cons: `O(n_inputs)` repricings; second-order
Greeks are noisy; choice of `h` trades bias (large `h`) vs noise (small `h`). Always use CRN (V.3).

## VII.2 Pathwise derivative — derivation and unbiasedness proof

**Setup.** Price `V(θ) = E[ e^{−rT} f(S_T(θ)) ]`. Want `∂V/∂θ`.

**Interchange and chain rule.** If `f` is Lipschitz and `S_T(θ)` is a.s. differentiable in `θ` with an
integrable dominating derivative, we may swap `∂/∂θ` and `E[·]`:

```
∂V/∂θ = e^{−rT} E[ f'(S_T) · ∂S_T/∂θ ].
```

This is an **unbiased** estimator (its expectation is exactly the derivative) — that's the content of
the interchange (dominated convergence / Leibniz).

**Delta for GBM (concrete).** `S_T = S₀ exp[(r−q−½σ²)T + σ√T Z]` ⟹ `∂S_T/∂S₀ = S_T/S₀`. So

```
Δ_pathwise = e^{−rT} E[ f'(S_T) · S_T/S₀ ].
```

For a call, `f'(S_T)=1_{S_T>K}`, giving `Δ = e^{−rT}E[ (S_T/S₀)1_{S_T>K} ]` — low variance, unbiased.

**Why it FAILS for a digital (defend).** A digital pays `1_{S_T>K}`. Then `f'` is a **Dirac delta**
`δ(S_T−K)` — not a function we can evaluate on finitely many paths (the event `S_T = K` has
probability 0, so the pathwise estimator is 0 almost surely, which is **wrong**). The interchange is
invalid because `f` is discontinuous (not Lipschitz). Same problem at a barrier. This is precisely
where LR steps in.

## VII.3 Likelihood-ratio (LR) — derivation and why it rescues digitals

**Idea.** Differentiate the **density**, not the payoff. Write the price as an integral against the
density `p(x;θ)` of the terminal variable:

```
V(θ) = e^{−rT} ∫ f(x) p(x;θ) dx.
```

Differentiate (payoff has no `θ`; only the density does):

```
∂V/∂θ = e^{−rT} ∫ f(x) ∂p/∂θ dx
       = e^{−rT} ∫ f(x) (∂ ln p/∂θ) p(x;θ) dx
       = e^{−rT} E[ f(x) · ∂ ln p/∂θ ].          ← the "score" weight
```

**Crucially, `f` is never differentiated** — so discontinuous payoffs (digitals, barriers) are fine.

**LR delta for GBM (concrete).** `ln S_T ~ N(μ, σ²T)` with `μ = ln S₀ + (r−q−½σ²)T`. The score w.r.t.
`S₀` (through `μ`, since `∂μ/∂S₀ = 1/S₀`):

```
∂ ln p/∂S₀ = (∂ ln p/∂μ)(∂μ/∂S₀) = [ (ln S_T − μ)/(σ²T) ] · (1/S₀) = Z / (S₀ σ√T),
```

where `Z = (ln(S_T/S₀) − (r−q−½σ²)T)/(σ√T)`. So

```
Δ_LR = e^{−rT} E[ f(S_T) · Z/(S₀ σ√T) ].
```

**The trade-off (defend):** LR works for *any* payoff (no smoothness needed) but the score weight
`Z/(S₀σ√T)` has high variance — it blows up for small `σ` or `T` and degrades for path-dependent
problems (the density gets high-dimensional). **Rule of thumb: pathwise for smooth payoffs (low
variance), LR for discontinuous ones (digitals/barriers).** Many desks use mixed/conditional
estimators (smooth the kink, then pathwise) to get the best of both.

## VII.4 AAD — the cheap-gradient theorem

**Q: Why does AAD give ALL sensitivities at ~constant cost, independent of input count?**

A price computation is a **DAG** of elementary operations `v₁,…,v_N` from inputs `x` to output `y`.

- **Forward (tangent) mode** propagates input perturbations forward: one sweep per *input* → cost
  `∝ n_inputs`. (This is essentially smart bumping.)
- **Reverse (adjoint) mode** propagates output sensitivities **backward**. Define adjoints
  `v̄_i = ∂y/∂v_i`. Seed `ȳ = 1`. Sweep the tape in reverse, accumulating

```
v̄_i = Σ_{j : i → j} v̄_j · ∂v_j/∂v_i.
```

After **one** reverse sweep, the adjoints of *all inputs* — i.e. the full gradient `∂y/∂x` — are
available. The **cheap-gradient (Baur-Strassen) theorem**: the cost of the reverse sweep is at most a
small constant (~3–5×) times the cost of evaluating `y`, **independent of the number of inputs**.

**The headline you must say:** "Bump costs `O(n_inputs × price)`; AAD costs `O(price)` for *every*
Greek at once. That asymmetry — one backward pass yields all sensitivities — is exactly why banks use
AAD to risk thousands of trades with thousands of inputs overnight." Build a small hand-rolled tape on
one product to prove you understand the adjoint accumulation; use JAX for breadth.

## VII.5 Vanna, volga, and the autocallable book

- **Vanna** `= ∂²V/∂S∂σ = ∂Δ/∂σ = ∂ν/∂S`: how delta moves when vol moves (and how vega moves with
  spot). Driven by **skew**; large near barriers.
- **Volga (vomma)** `= ∂²V/∂σ²`: convexity of vega in vol; the cost/benefit of being long/short the
  *wings* (vol-of-vol).

For a **short-vol autocallable book**, vanna/volga dominate the cost of **vega hedging**: you can't
flatten vega with a single vanilla because as spot and vol move, your vega itself moves
(vanna/volga). They are also the leading terms in the P&L attribution residual near barriers — which
is why a serious desk tracks them explicitly. (The "vanna-volga" pricing method even uses these three
Greeks — ATM vega, vanna, volga — to smile-adjust prices.)

---

# Part VIII — Structuring

## VIII.1 Price-to-par — what "fair" means and why it's well-posed

**Q: Walk me through solving a note to par.**

A note is **fair** when its **model PV equals the issue proceeds the desk keeps**:

```
PV_model(params) = Notional − fees − funding/credit adjustment.
```

`PV_model` is the desk's **hedging cost** (what it costs to replicate the payoff it sold), *not* the
client's expected return. The structurer fixes all parameters but one (the client specifies the rest:
"I want 12%, 3 years, on NIFTY") and solves the free one:

```
find c (coupon)   s.t. PV(c) = par − fee     # 1-D Brent root
find KI           s.t. PV(KI) = par − fee
```

**Well-posedness:** `PV` is **monotone** in the free parameter (more coupon ⟹ higher PV; lower KI ⟹
investor shorter the put ⟹ higher PV to the investor) — a strictly monotone continuous function has a
**unique root**, so Brent converges reliably. **The economic identity to state:** *higher coupon ⟺
lower (riskier) KI ⟺ the investor sells more optionality.* The coupon is the premium the investor
earns for the optionality they're short.

## VIII.2 Objective → structure mapping (the proposer)

| Client objective | Structure | Why |
|---|---|---|
| High income, can take measured downside | Phoenix / autocallable, KI≈70% | Sell downside + cap = fund the coupon |
| Principal protection + upside | ZC bond + call participation | Bond floor + leftover premium buys calls |
| Thematic income (AI/tech) | Worst-of autocallable on a basket | Correlation premium boosts the coupon |
| Income, mildly bearish/range view | Barrier reverse convertible | Short a KI put for premium |

---

# Part IX — Risk management

## IX.1 Discrete delta-hedging error scales with √Δt — derivation

**Q: Why does discrete delta-hedging P&L variance scale with rebalance frequency?**

Hold a delta-hedged option over `[t, t+Δt]`. The hedging P&L of the (option − Δ·stock − financing)
position over the step is, to leading order (Taylor + the BS PDE for theta):

```
ΔP&L_step ≈ ½ Γ_t [ (ΔS)² − σ²S_t² Δt ].
```

Interpretation: you earn theta (`−½Γσ²S²Δt`, baked into option decay) but pay realised gamma cost
`½Γ(ΔS)²`. Over the step `(ΔS)² ≈ σ²S²Δt·χ²₁` (a scaled chi-square with mean `σ²S²Δt`), so each step's
hedging error has **mean ≈ 0** and **variance `∝ (ΔS)²` variance `∝ (σ²S²Δt)² = O(Δt²)`**. Summing
`N = T/Δt` independent steps, total error variance `≈ N·O(Δt²) = O(Δt)`. Hence

```
std( total hedging error ) ∝ √Δt = √(T/N) ∝ 1/√N.
```

**Conclusion:** hedge twice as often (`Δt → Δt/2`) ⟹ hedging-error std falls by `√2`. More frequent
hedging reduces replication error but increases transaction costs — the practical trade-off, which is
why you parametrise slippage.

## IX.2 Gamma-theta trade-off; short gamma near barriers

From the BS relation `Θ + (r−q)SΔ + ½σ²S²Γ − rV = 0`, a **delta-hedged** position (Δ≈0, ignore
financing) gives `Θ ≈ −½σ²S²Γ`. So:
- **Long gamma ⟹ negative theta:** you pay time decay to own convexity; you profit when realised vol
  > implied (big moves help you).
- **Short gamma ⟹ positive theta:** you collect decay but lose on big moves.

An **autocallable issuer is structurally short gamma**, sharply so **near the KI barrier**, where the
delta whipsaws as spot crosses the barrier. They earn carry/theta in calm markets and bleed on sharp
moves through the barrier — the classic "picking up pennies in front of a steamroller" profile.

## IX.3 Gap risk — why it can't be delta-hedged

Delta hedging assumes you can **continuously** rebalance along a *continuous* path. An **overnight gap
or jump** moves spot discontinuously — straight *through* the KI before you can trade. No delta
position set the night before can replicate a discontinuous move; the loss is realised before
rebalancing. This **gap risk** is the structural tail of an autocallable book and must be reserved /
stress-tested, not hedged away (you can only partially mitigate it with OTM options or position
limits).

## IX.4 P&L attribution — the Taylor explain and the residual

**Q: Walk me through your daily P&L explain. What does the residual tell you?**

Expand the value change `D−1 → D` in the risk factors (second order):

```
ΔV ≈ Δ·ΔS + ½Γ·(ΔS)²            (delta, gamma)
   + Θ·Δt                       (theta)
   + ν·Δσ + ½·volga·(Δσ)²       (vega, volga)
   + vanna·ΔS·Δσ                (vanna — cross)
   + (corr Δ)·Δρ + ρ_r·Δr + (div Δ)·Δq
   + RESIDUAL.
```

Compute Greeks at `D−1`, observe the actual factor moves, sum the **"Greek/explained P&L"**, and
compare to the **"revaluation P&L"** (a full reprice on Snapshot(D)). The **residual = revaluation −
explained.**

**Why the residual is the headline number (defend):**
- **Small residual** ⟹ Greeks + repricing agree ⟹ the book is well-understood and well-hedged; the
  model is internally consistent.
- **Large residual** ⟹ a missing risk factor, large un-modelled convexity (high-order Greeks near
  barriers), or a model/calibration problem. **A desk that can't explain its P&L can't trade** — risk
  managers reconcile this every morning. Big residuals cluster in **high gamma/vanna** positions near
  barriers, telling you exactly where your linear risk picture is failing.

**Greek P&L vs revaluation P&L (why both):** the Taylor version *attributes* (tells you *why*); the
full reprice is the *truth* (tells you *how much*). Their difference (residual) is the diagnostic.

## IX.5 Model reserves — the three kinds

1. **Model reserve `= |P_model_A − P_model_B|`** (e.g. LSV vs LV): the dynamics-uncertainty reserve
   (see VI.4). Material for forward-smile products.
2. **Parameter-uncertainty reserve:** perturb calibrated parameters within their confidence/feasible
   region; reserve = spread of resulting prices. Captures "the calibration isn't unique."
3. **Bid-offer reserve:** reprice marks at bid and at offer; reserve `= ½·spread × sensitivity`.
   Captures the cost of unwinding.

A reserve is **P&L you decline to book** because you don't trust the mark to that precision —
conservative accounting of model/market uncertainty.

## IX.6 Stress testing — why coherence

**Q: Why must scenarios be coherent across spot/vol/correlation?**

In a real crash these factors move **together**: spot ↓, vol ↑ (and skew steepens), correlations →
1 ("everything sells off together"), dividends get cut, rates may move. A naïve **single-factor** bump
(spot −30%, vol and corr held flat) **understates** the loss because it ignores the simultaneous vol
and correlation blow-up that hits the same book. So you shock the snapshot **coherently** (joint
scenario) and reprice. **Correlation-up is the killer for a worst-of book** (the worst performer drags
the payoff when names fall together), and an **autocallable's worst day is a sharp drop *through* the
KI with no autocall relief** — maximum downside, zero coupon comfort. Historical replays (March 2020)
provide ready-made coherent scenarios.

---

# Part X — Data & backtesting

## X.1 Why invert to IV, not store prices

Storing **prices** ties your data to the spot/rate at capture; a small spot move makes every stored
price stale. **Implied vol** is the *normalised, model-agnostic* coordinate: it changes slowly and
lets the surface layer re-derive prices for any spot/rate. Hence you invert per contract to IV points
and let L2 own the surface.

## X.2 Settlement-price IV bias (recap) and arbitrage repair order

Settlement ≠ traded mid; wide wing bid-offer ⟹ noisy/biased wing IVs (II.1). Before calibrating you
**repair**: drop stale/zero-volume contracts, enforce monotone call prices in `K`, run the Durrleman
(butterfly) and calendar checks, and only then fit SVI→SSVI. Calibrating to dirty data bakes
arbitrage into the surface and poisons Dupire.

## X.3 Risk-neutral vs real-world — the classic error

**Q: Pricing vs backtesting — what's the difference?**

- **Pricing (L4)** is under **`Q`** (risk-neutral): average over *simulated* futures with drift `r` to
  get **fair value / hedging cost**.
- **Backtesting (L7)** is under **`P`** (real world): replay the **single path that actually
  happened** to see realised outcomes (autocall frequency, realised losses).

Conflating them is a classic blunder. You do **not** simulate a backtest; you replay history. And you
do **not** price with real-world drift. State both crisply.

## X.4 Survivorship bias

**Q: What does survivorship bias do to an autocall backtest?**

If your historical universe is *today's* surviving liquid names, you implicitly only ever traded names
that **didn't** blow up → backtested autocall frequency and returns are **inflated**, tail losses
understated. Fix: **point-in-time** index membership and liquidity universe — the names as they were on
each historical date.

## X.5 Bootstrapping the rate curves — and why two, never flat

**Q: Where do your discount/forward rates come from? Do you assume a flat rate?**

No — the rates are **bootstrapped** term structures, and there are **two** of them in every snapshot.

*Bootstrapping in one line:* the market quotes a handful of instruments (FBIL overnight/MIBOR, OIS swap
rates, T-bill yields), each a constraint saying "this package of cashflows is worth par today." You back
out the discount factors `D(T)` that make all quotes simultaneously consistent, solving
**shortest-maturity-first** so that at each step exactly one new discount factor is unknown (a 2Y swap's
par condition already knows `D(6M), D(1Y), D(18M)` from earlier steps → solve `D(2Y)`). Between the
instrument maturities (pillars) you **interpolate** — default log-linear on discount factors, or
monotone-convex on forwards if you care about clean forward rates (a bad scheme gives a smooth discount
curve but a sawtooth forward curve, which poisons the drift). Output is three views of one object:
discount factors `D(T)`, zero rates `z(T)=−ln D(T)/T`, and forwards `f(t₁,t₂)`.

*Why two curves:* they do different jobs. The **OIS / risk-free curve** (from FBIL OIS/T-bills) sets the
**risk-neutral drift** `(r−q)` in MC/PDE and discounts the **option leg**. The **issuer funding curve**
discounts the note's **zero-coupon-bond leg**, because the note is the issuer's *debt* (see XI.8). Cheaper
funding (wider spread) makes the ZCB leg cheaper, freeing budget for optionality — the economics behind
why banks issue notes.

*Direct bootstrap vs spread over OIS — and which I chose:* I model the funding curve as a **spread over
OIS** (ADR 0002), not a direct issuer bootstrap. I fully bootstrap OIS, then add a *small parametric*
spread term structure `s(T)` (2–3 knots, **not** flat) calibrated to whatever issuer reference exists
(issuance spread / benchmark bank-bond spread / CDS). Three reasons: (1) **data** — there's no dense,
liquid issuer bond curve in my sources, so a direct bootstrap from 2–3 stale points is unstable and
breaks snapshot reproducibility; (2) **coherent rate risk** — `funding = OIS + spread` moves both curves
together under a rate shock, avoiding spurious basis from two independent bootstraps; (3) **the spread
becomes a first-class, shockable factor**, exactly what the structuring economics and the stress layer
need. I'd switch to a **direct issuer bootstrap only given a liquid issuer bond/CDS curve** with reliable
EOD marks.

*Why not flat:* a flat rate gives the wrong drift at every tenor (mispricing forwards and skew-sensitive
payoffs) **and** collapses the two-curve distinction, destroying the funding-spread cost decomposition.
A flat *spread* is also wrong — credit has term structure, so `s(T)` is parametric, not a scalar.

---

# Part XI — Broad equity-structuring questions

Questions that aren't tied to a specific layer but *will* come up for a structuring/exotics seat.

## XI.1 "Who is long/short vol, gamma, skew, correlation in product X?"
Be able to answer instantly for autocallable, Phoenix, BRC, worst-of, capital-protected (see Part IV).
The reflexive skill: decompose → read off the Greeks' signs.

## XI.2 "An autocallable desk is structurally short vol — explain, and where do they lose money?"
Selling autocallables = selling optionality (the coupon is the premium). Net book vega < 0; net gamma
< 0 near barriers. They make money in calm, slightly-up/sideways markets (notes autocall, coupons
paid) and **lose** in (a) sharp sell-offs through the KI (short the put), (b) vol spikes (short vega),
(c) correlation spikes for worst-ofs. The P&L is "steady carry punctuated by sharp tails."

## XI.3 "Why does the equity skew slope down (puts richer than calls)?"
Leverage/crashophobia + hedging demand for downside protection + fat left tail (see II.2). Contrast
with FX (more symmetric smile) and commodities (sometimes upward skew). Knowing the *cross-asset*
contrast signals depth.

## XI.4 "What's the difference between local, stochastic, and local-stochastic vol — and when does it
*matter*?"
Marginals vs dynamics (VI). It matters whenever the payoff depends on the **forward smile** or the
**joint distribution across dates**: autocallables, cliquets, forward-starts, napoleons, lookbacks.
For a single-date vanilla it doesn't matter at all.

## XI.5 "Price a digital. Why is it hard to hedge near expiry/strike?"
A cash-or-nothing digital `= e^{−rT}N(d₂)` (call). Its delta `∝ n(d₂)/(Sσ√T)` **explodes** as `T→0`
near the strike — infinite gamma at the barrier. Desks **sub-replicate** with a tight **call spread**
(`[K−ε, K]`) to cap the gamma/pin risk; the spread width sets a bid-offer. Connect to barriers/KI
(same pin-risk pathology).

## XI.6 "What is dispersion trading?"
Sell index volatility, buy constituent volatility (or vice versa) — a bet on **implied correlation**
(III.1). Worst-of autocallables leave a desk with correlation exposure that dispersion-style hedges
can offset. Implied correlation ≈ the price of the correlation the desk is structurally short.

## XI.7 "What's a cliquet / forward-start, and why is it the hardest to price?"
A series of forward-starting options (ratchet). Its value lives *entirely* in the **forward smile**,
so LV (flat forward smile) badly misprices it and even SV/LSV calibration differences show up loudly —
the extreme case of the model-reserve point.

## XI.8 "How does issuer funding/credit enter the price?"
The note is the issuer's **debt** — its zero-coupon-bond leg discounts at the issuer's **funding
curve** (incl. credit spread), not the risk-free rate. Cheaper funding (wider issuer spread) lets the
desk offer a higher coupon — which is *why* banks issue structured notes (cheap funding) and why the
**funding/XVA** desk is a sibling of structuring (your XVA-engine connection).

## XI.9 "Greeks of an autocallable as it approaches an autocall barrier?"
Near an upper autocall barrier the note behaves like a digital/knock-out: **delta and gamma spike and
can flip sign**; vega can change sign (short-vol away from the barrier, but the redemption
optionality can flip it locally). This is the "pin risk" region — quote it.

## XI.10 "Why do low rates hurt capital-protected notes?"
The principal guarantee is a zero-coupon bond; in low rates that bond costs nearly par, leaving little
premium to buy upside participation → unattractive terms. Rising rates revive them.

## XI.11 Quick-fire identities/relationships to have cold
- Put-call parity (I.4). Forward `F=Se^{(r−q)T}`.
- BS PDE and the `Θ + (r−q)SΔ + ½σ²S²Γ = rV` relation.
- `Vega = Se^{−qT}n(d₁)√T`, same for call/put; gamma same for call/put.
- Breeden-Litzenberger `p = e^{rT}∂²C/∂K²`.
- MC error `∝1/√N`; AAD gradient cost `O(price)`.
- Dupire and the LSV identity `L² = σ²_Dupire/E[v|S]`.

---

# Part XII — Project-level questions

## XII.1 "What's REAL vs FAITHFUL vs STUBBED in your project?"
Have the **scope contract** memorised. The strongest signal is knowing your system's edges:
*"SVI/SSVI with arbitrage repair, autocallable MC, bump/pathwise/AAD Greeks cross-checked, P&L
attribution — REAL. AAD-over-the-graph, LSV calibration, the DSL, historical replay — FAITHFUL,
scoped to single-machine/coarse-grid. C++/GPU kernels, the message bus — STUBBED behind clean
interfaces. Real-time connectivity, FRTB capital, quanto-at-scale — SKIPPED, declared."*

## XII.2 "What was the hardest part / what would you do differently?"
LSV leverage calibration (the conditional-expectation fixed point) — highest risk; you'd budget more
time, parallelise the particle method, validate the vanilla repricing tightly before trusting exotic
prices. Honesty here reads as senior.

## XII.3 "How did you validate it?"
Layered tests: MC → closed-form **convergence** tests; **AAD vs bump vs pathwise agreement** (the
headline Greek test); **arbitrage-free** property-based tests (hypothesis); LSV **reprices the vanilla
surface** to tolerance; P&L attribution **residual** demonstrably small over a replay window. Validation
*is* the credibility.

## XII.4 "Why Indian/NSE data? Isn't it a limitation?"
It's free and the **bhavcopy→IV reconstruction** (inverting F&O settlement prices to a historical
surface) is a genuine engineering story most students skip. The methodology is market-agnostic — point
it at any options market with the same pipeline. Limitation declared (EOD, scoped universe), strength
emphasised (real historical surface on free data).

## XII.5 "How is this different from a pricing library?"
*"It's a desk, not a pricer."* It simulates the **workflow** — structurer → trader → risk → model
validation → hedging — with historical replay, a virtual book, daily P&L explain, and reserves. The
integration and the desk-realism (P&L attribution residual, model reserve) are the differentiator, not
any single pricer.

---

## Final advice (from the spec)

> Build a **one-page derivation card** for each item above and rehearse them **out loud**. The honest
> risk on a project this broad is being able to *run* it but not *derive* it. Knowing these cold is
> worth more than any extra feature. The five to protect: **arbitrage-free surface · autocallable MC ·
> cross-checked Greeks · P&L attribution residual · LSV−LV reserve.**

*Companion to `SPDT_Layer_Walkthrough.md` and `SPDT_Design_and_Build.md`. This file is the answer key.*
