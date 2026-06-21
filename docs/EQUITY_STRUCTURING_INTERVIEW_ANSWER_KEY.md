# Equity Structuring Interview Answer Key

Companion to `EQUITY_STRUCTURING_INTERVIEW_PREP_GUIDE.md`.

Purpose: answer every question in the prep guide at interview depth, from first principles where needed, and in the language of an equity structuring desk.

How to use this:

- For derivations, close the file and reproduce the derivation on paper.
- For product questions, practice in three registers: retail client, institutional client, and trader/quant.
- For project questions, answer honestly: what is real, what is faithful, what is simplified, and why that design choice still shows desk understanding.
- For repeated questions, this answer key gives a detailed canonical answer once, then a concise answer in later question-bank sections.

---

## 1. Resume Bullet Defense: Full Answers

### 1. What is a structured product?

A structured product is a packaged investment whose payoff is engineered by combining a bond or deposit-like component with derivative components. In equity structuring, the derivative components are usually options on stocks, indices, baskets, volatility, or hybrids.

Simple decomposition:

```text
Structured product = funding/bond leg + option package + issuer margin/costs
```

Examples:

- Capital-protected note: zero-coupon bond + call option or call spread.
- Reverse convertible: bond + coupon - put sold by investor.
- Barrier reverse convertible: bond + coupon - down-and-in put sold by investor.
- Autocallable/Phoenix: conditional coupons + early redemption + downside knock-in exposure.
- Worst-of autocallable: autocallable whose conditions depend on the worst-performing asset in a basket.

Why clients buy them:

- To monetize a market view.
- To receive enhanced yield.
- To get conditional capital protection.
- To access payoff shapes not available through direct equity or bonds.
- To transform option risk into coupons, participation, leverage, or protection.

What the bank does:

- Designs terms that match the client objective.
- Prices the embedded options using market inputs.
- Adds issuer funding, XVA, capital, and margin.
- Hedges the resulting risk.
- Produces term sheets and risk disclosures.

Interview line:

"A structured product is a payoff transformation. The structurer's job is to turn a client view and constraints into option terms, then check whether the trade is priceable, hedgeable, suitable, and profitable after funding, XVA and capital."

### 2. Why would a client buy an autocallable?

A client buys an autocallable when they want enhanced yield and have a moderately bullish or range-bound view on the underlying. The client is usually not buying it because they expect a huge rally. They are buying it because they are willing to sell downside/tail risk and give up some upside in exchange for coupons.

Typical client view:

- "I do not think the index will crash."
- "I am comfortable earning coupon if the market stays flat or rises."
- "I accept principal risk if the market falls through the downside barrier."

Economic trade:

- Client receives coupon.
- Client gives the issuer the right to redeem early if conditions are met.
- Client takes downside exposure if the knock-in condition is breached.
- Client is implicitly selling volatility, skew, gap risk, and sometimes correlation risk.

Good answer:

"An autocallable converts equity downside and volatility risk into income. It is attractive when the client wants yield and believes the underlying will not fall sharply. But it is not a free yield product. The coupon exists because the client is selling optionality, especially downside crash risk."

### 3. What optionality is the investor selling?

The investor is typically selling:

- Downside put optionality: if the underlying falls below a barrier, principal becomes linked to equity losses.
- Digital/barrier optionality: coupon and autocall events are triggered by barrier observations.
- Callability: the note can redeem early when it is favorable for the issuer economics and when the client might otherwise like to keep earning coupon.
- Volatility/skew risk: because the value of downside barriers and knock-in puts rises with vol and skew.
- Correlation risk in worst-of notes: because payoff depends on the worst performer.

For a BRC:

```text
BRC = bond + fixed coupons - down-and-in put
```

The investor is short a down-and-in put.

For a reverse convertible:

```text
RC = bond + fixed coupons - vanilla put
```

The investor is short a vanilla put.

For an autocallable:

The exact decomposition is less clean than one vanilla option, but conceptually the investor is short a package of conditional coupons, early redemption optionality, and downside knock-in/tail exposure.

### 4. What optionality is the bank short/long after issuing the note?

Be careful: the sign depends on perspective and exact product.

The bank issues the note, so the bank owes the investor the note payoff. If the investor is short a put embedded in the note, the bank is economically long that put exposure before hedging. But the bank also owes coupons and redemption cashflows and must hedge path-dependent risks.

For a reverse convertible:

- Investor payoff: par + coupon - put loss.
- Investor is short put.
- Bank is long embedded put but owes coupon/bond cashflows.

For an autocallable:

- Bank owes coupons if conditions are met.
- Bank owes early redemption if autocall triggers.
- Bank benefits from investor taking downside if knock-in occurs.
- Net Greeks can vary by state. The bank's aggregate issuance book often has complex short/long gamma and vega regions depending on moneyness, barriers, and hedges.

Strong answer:

"I avoid saying the bank is simply long or short one option. The client is usually short downside optionality and callability; the issuer has the opposite embedded exposure but then dynamically hedges. The risk report matters more than a one-line sign because autocallables have state-dependent delta, gamma, vega, vanna and correlation exposure."

### 5. Why is an autocallable typically short volatility?

From the investor perspective, the product usually sells volatility. The coupon is funded by option premium from selling downside and barrier optionality. When implied volatility rises, the embedded downside/tail risk becomes more valuable, so the note is usually less valuable to the investor and can support a higher coupon at issuance.

Intuition:

- High vol increases probability of hitting downside barrier.
- High vol increases value of puts and knock-in puts.
- High vol can reduce certainty of benign autocall path.
- Equity skew makes downside optionality especially expensive.

Nuance:

The local vega of an autocallable can change sign depending on spot, time, observation schedule, and barriers. Near an autocall level, higher vol may reduce probability of immediate autocall and extend the life of coupons, which can create local positive effects for the investor. But structurally, autocallable yield is mostly compensation for selling volatility/skew/tail risk.

### 6. Why is a worst-of autocallable sensitive to correlation?

A worst-of note depends on the minimum return across several assets:

```text
WorstOf(t) = min_i S_i(t) / S_i(0)
```

The payoff is driven not only by each asset's volatility, but by the joint distribution. Correlation controls how likely one asset is to be much worse than the others.

Lower correlation:

- More dispersion.
- Higher chance that at least one asset performs badly.
- Bad for worst-of investors, especially for downside barrier and coupon conditions.

Higher correlation:

- Assets move together.
- Less single-name dispersion.
- Can help worst-of coupon/autocall probability in some regions.
- But in crash scenarios, correlations often rise and all names can fall together, so stress behavior remains severe.

Nuance:

The sign of correlation sensitivity can be state-dependent. For many worst-of yield notes, investors are effectively short dispersion and exposed to low-correlation underperformance of one name. But near autocall barriers and in stressed regions, the sign can be more subtle. A serious desk answer says: compute correlation delta and run correlation-up/down scenarios.

### 7. What is SVI? Why not interpolate implied vol directly?

SVI stands for Stochastic Volatility Inspired parameterization. It parameterizes total implied variance for one maturity slice as a smooth function of log-moneyness:

```text
w(k) = a + b [ rho (k - m) + sqrt((k - m)^2 + sigma^2) ]
```

where:

- `w(k) = implied_vol(k)^2 * T` is total variance.
- `k = ln(K/F)` is log-moneyness.
- `a` controls level.
- `b` controls wing slope.
- `rho` controls skew.
- `m` shifts the smile.
- `sigma` controls curvature/smoothness.

Why not interpolate implied vol directly?

- Raw implied vols are noisy, especially in wings.
- Direct interpolation can create arbitrage: negative density or calendar crossing.
- Local vol requires derivatives of the surface; differentiating noisy quotes is unstable.
- SVI gives smooth, interpretable, asymptotically reasonable wings.
- Total variance is the natural object for calendar conditions.

Interview line:

"I fit a smooth total-variance surface because exotics need a stable surface, not just exact interpolation through noisy marks. A surface that looks visually fine can still imply negative density or explosive local vol if it violates static arbitrage."

### 8. What does arbitrage-free vol surface mean?

An arbitrage-free implied vol surface is one whose option prices do not allow static arbitrage across strikes or maturities.

Main conditions:

1. Butterfly arbitrage-free across strikes:

Call price must be decreasing and convex in strike:

```text
partial C / partial K <= 0
partial^2 C / partial K^2 >= 0
```

By Breeden-Litzenberger:

```text
f_Q(K,T) = exp(rT) partial^2 C / partial K^2
```

So convexity means non-negative implied risk-neutral density.

2. Calendar arbitrage-free across maturities:

For a fixed moneyness, total variance should not decrease with maturity:

```text
partial w(k,T) / partial T >= 0
```

Otherwise longer-dated options can be too cheap relative to shorter-dated options.

Why it matters:

If the surface has arbitrage, a local-vol model can produce negative variance, barriers can be mispriced, Greeks can be nonsensical, and structured product prices become false precision.

### 9. How do you price a path-dependent note?

General risk-neutral MC method:

1. Define product cashflow rules.
2. Build simulation grid containing all observation, coupon, barrier, autocall and maturity dates.
3. Simulate risk-neutral paths under a calibrated model.
4. For each path, evaluate cashflows according to product rules.
5. Discount each cashflow using the correct curve.
6. Average discounted payoffs.
7. Report standard error.
8. Validate against analytic cases or simpler limiting products.

Formula:

```text
V_0 = E^Q[ sum_j DF(0,t_j) CF_j(path) ]
```

MC estimator:

```text
V_hat = (1/N) sum_i sum_j DF(0,t_j) CF_j(path_i)
```

In SPDT:

- Product supplies monitoring times.
- Model simulates paths.
- Product cashflows are evaluated path by path.
- Funding legs and option legs can be discounted differently.
- For exposure, the product is marked to future over a path-by-time cube.

### 10. How do you compute Greeks under Monte Carlo?

Main methods:

1. Bump-and-revalue:

```text
Delta approx [V(S+h) - V(S-h)] / (2h)
```

Pros: simple, robust, model-agnostic.
Cons: expensive and noisy.

Use common random numbers so both reprices use same random shocks.

2. Pathwise estimator:

Differentiate payoff along each path.

Pros: efficient, low variance for smooth payoffs.
Cons: fails for discontinuous payoffs like digitals/barriers.

3. Likelihood-ratio method:

Differentiate probability density instead of payoff:

```text
partial_theta E[f(X)] = E[f(X) partial_theta log p_theta(X)]
```

Pros: works for discontinuities.
Cons: higher variance.

4. AAD/reverse-mode AD:

Record computation graph and backpropagate adjoints.

Pros: many sensitivities at small multiple of one pricing run.
Cons: implementation complexity; discontinuities and MC branching require care.

### 11. What is AAD and why does a desk care?

AAD means adjoint algorithmic differentiation, usually reverse-mode automatic differentiation applied to pricing models.

A price is one output depending on many inputs:

```text
V = f(S_1, ..., S_n, vols, rates, dividends, correlations, credit spreads)
```

Bump-and-revalue cost scales with number of risk factors. If there are 10,000 risk factors, bumping them one by one is too slow.

Reverse-mode AD computes gradients of one scalar output with respect to many inputs at a small constant multiple of the cost of one valuation.

In a reverse tape:

1. Forward pass computes price and stores local derivatives.
2. Set output adjoint to 1.
3. Sweep backward:

```text
adjoint_parent += adjoint_child * local_derivative
```

Desk reason:

Fast sensitivities are necessary for intraday risk, hedging, P&L explain, stress, and capital calculations.

### 12. What is P&L attribution?

P&L attribution explains the change in a trade or book's value over a period using risk-factor moves and Greeks.

Generic second-order explain:

```text
dPV approx Delta dS + 0.5 Gamma dS^2
          + Theta dt
          + Vega dVol + 0.5 Volga dVol^2
          + Vanna dS dVol
          + Rho dr
          + residual
```

Full revaluation P&L:

```text
PV(today market, aged trade) - PV(yesterday market, yesterday trade)
```

Explained P&L:

Taylor approximation using yesterday's risk sensitivities and observed market moves.

Residual:

```text
Residual = Full revaluation P&L - Explained P&L
```

Desk importance:

Risk managers care about residual because it tells whether the reported Greeks actually explain the book.

### 13. What does a large residual mean?

A large P&L residual means the reported risk factors and sensitivities did not explain the realized mark-to-market move.

Potential causes:

- Missing risk factor, such as dividends, borrow, skew, correlation, funding, or credit.
- Large nonlinear move beyond second-order approximation.
- Barrier/digital discontinuity.
- Product aged through observation/coupon date.
- Model recalibration effect.
- Vol surface shape move not captured by flat vega.
- MC noise.
- Data issue or stale mark.
- Trade booking/cashflow error.

Good answer:

"Residual is an investigation trigger. I would decompose by trade, risk factor, product type and market data change; rerun full revaluation; check realized cashflows and observations; check vol surface and correlation moves; then decide whether the residual is legitimate nonlinear P&L or a model/data issue."

### 14. Why do LV and LSV disagree on exotics?

Local vol and LSV can both match today's vanilla surface, which means they match today's risk-neutral marginal distribution at each maturity. But exotics depend on the path and conditional dynamics, not only terminal distributions.

Local vol:

- Deterministic volatility function `sigma(S,t)`.
- Calibrated to vanilla surface.
- Often implies unrealistic future smile dynamics.

LSV:

- Stochastic variance process plus leverage function.
- Matches vanilla surface while preserving stochastic vol dynamics.
- Better captures forward smile and vol-of-vol effects.

Autocallables depend on:

- Barrier hitting probabilities.
- Conditional distribution after surviving observation dates.
- Future smile behavior.
- Spot-vol correlation.
- Path of spot, not just final spot.

So LV and LSV may price vanillas identically but autocallables differently. That difference is a model-risk reserve candidate.

### 15. What is CVA? Why should it reduce the coupon?

CVA is credit valuation adjustment: the expected discounted loss due to counterparty default.

Approximate formula:

```text
CVA = LGD * sum_i DF(t_i) EE(t_i) dPD(t_i)
```

where:

- `LGD = 1 - recovery`.
- `EE(t)` is expected positive exposure.
- `dPD(t)` is default probability over interval.
- `DF(t)` discounts to today.

Why it reduces coupon:

If the bank bears counterparty credit risk, the trade has an additional lifetime cost. The all-in fair value target becomes:

```text
PV(note) = par - fee - XVA
```

Higher CVA means less value can be given to the client as coupon. So the all-in coupon falls as counterparty credit spread widens.

### 16. What is RAROC? Why can a trade be fair-value profitable but rejected?

RAROC means risk-adjusted return on capital:

```text
RAROC = risk-adjusted profit / economic capital
```

A trade can be profitable on fair value but still bad after capital usage.

Reasons for rejection:

- EAD/PFE limit breach.
- Counterparty concentration limit breach.
- Economic capital too high.
- RAROC below hurdle.
- Wrong-way risk.
- Liquidity/hedging constraints.
- Regulatory or suitability concerns.

Good answer:

"A structurer cannot stop at fair PV. The trade must pass economics after XVA, capital and limits. If a note consumes too much balance sheet for too little margin, it may be rejected even if the model price is positive."

### 17. What did you build yourself vs what did you simplify?

Strong SPDT answer:

"I built a faithful educational version of the desk workflow. The core product DSL, Monte Carlo pricing flow, vol-surface logic, Greeks methods, P&L attribution, model reserve logic, stress framework and XVA exposure seam are implemented in project form. Some pieces are production-shaped but simplified in scale: market data quality, calibration robustness, high-performance infrastructure, full regulatory capital stack, real-time connectivity, and exhaustive model validation."

Breakdown:

Built/owned:

- Market snapshot abstraction.
- Product catalog/payoff DSL.
- Monte Carlo pricing engine.
- Worst-of basket simulation.
- SVI/SSVI/local-vol concepts and checks.
- Bump/pathwise/LR/AAD Greeks concepts.
- P&L explain and residual.
- Model reserve framework.
- Exposure package to XVA.
- Governance-style metrics.

Simplified:

- Data depth and liquidity filtering.
- Production-level calibration.
- Full stochastic rates/dividends/borrow.
- Correlation smile and dynamic copulas.
- Full production AAD over every path.
- Real trade lifecycle operations.

### 18. How would you improve it if you had six more months?

Prioritized answer:

1. Market data and calibration:

- Better listed option cleaning.
- Bid/offer-aware vol calibration.
- Liquidity-weighted SVI/SSVI.
- Dividend and borrow curves.

2. Model realism:

- Production-quality LSV calibration.
- Stochastic dividends/rates for long-dated products.
- Correlation smile and t-copula stress.
- Brownian bridge barrier handling.

3. Greeks and risk:

- Full-vector AAD through MC paths.
- Barrier smoothing for stable Greeks.
- More granular vega/skew/correlation ladders.
- Better P&L explain by risk-factor bucket.

4. Desk workflow:

- Trade lifecycle with coupons, observations and settlements.
- Scenario term sheets.
- Client suitability flags.
- Approval workflow.

5. Validation:

- More analytic benchmarks.
- Backtesting against historical issued note behavior.
- Independent model validation pack.

---

## 2. Core Derivations: From Scratch

### 2.1 Risk-neutral pricing

Question: Why is derivative price a discounted expectation under a risk-neutral measure?

Start with the no-arbitrage idea. If a payoff can be replicated by trading underlying assets and a cash account, then its price must equal the cost of the replicating strategy. Otherwise, if the derivative is cheaper than replication, buy the derivative and sell the replicating portfolio. If it is more expensive, sell the derivative and buy the replicating portfolio. Either way, you lock in arbitrage.

In a frictionless arbitrage-free market, the First Fundamental Theorem of Asset Pricing says there exists an equivalent probability measure `Q` such that discounted tradable asset prices are martingales.

For a money-market account:

```text
B_t = exp(integral_0^t r_s ds)
```

The discounted asset price is:

```text
S_t / B_t
```

Under `Q`:

```text
S_t / B_t = E_t^Q[S_T / B_T]
```

For a derivative payoff `H` at maturity `T`, if it is attainable:

```text
V_t / B_t = E_t^Q[H / B_T]
```

Therefore:

```text
V_t = B_t E_t^Q[H / B_T]
```

If rates are deterministic:

```text
V_t = E_t^Q[ exp(-integral_t^T r_s ds) H ]
```

If rates are constant:

```text
V_0 = exp(-rT) E^Q[H]
```

Why the real-world drift disappears:

The real drift `mu` reflects risk premia and investor expectations. The derivative price is not the real-world expected payoff. It is the cost of hedging/replication. Under `Q`, all tradable assets earn the risk-free rate after risk adjustment, so drift becomes `r` or `r - q` for dividend-paying stocks.

Interview trap:

Do not say "we assume investors are risk-neutral." More precise: we use an equivalent martingale measure because no-arbitrage prices can be represented as discounted expectations under that measure.

### 2.2 Black-Scholes PDE

Assume stock follows GBM under the real-world measure:

```text
dS = mu S dt + sigma S dW
```

Let derivative value be:

```text
V = V(S,t)
```

Use Ito's lemma:

```text
dV = V_t dt + V_S dS + 0.5 V_SS (dS)^2
```

Since:

```text
(dW)^2 = dt
(dt)^2 = 0
dt dW = 0
```

and:

```text
(dS)^2 = sigma^2 S^2 dt
```

we get:

```text
dV = (V_t + mu S V_S + 0.5 sigma^2 S^2 V_SS) dt
     + sigma S V_S dW
```

Construct a portfolio:

```text
Pi = V - Delta S
```

Its change:

```text
dPi = dV - Delta dS
```

Substitute:

```text
dPi =
(V_t + mu S V_S + 0.5 sigma^2 S^2 V_SS) dt
+ sigma S V_S dW
- Delta(mu S dt + sigma S dW)
```

Choose:

```text
Delta = V_S
```

Then the `dW` term cancels:

```text
sigma S V_S dW - V_S sigma S dW = 0
```

The `mu` term also cancels:

```text
mu S V_S dt - V_S mu S dt = 0
```

So:

```text
dPi = (V_t + 0.5 sigma^2 S^2 V_SS) dt
```

The portfolio is locally riskless. By no arbitrage it must earn risk-free rate:

```text
dPi = r Pi dt = r(V - S V_S) dt
```

Equate:

```text
V_t + 0.5 sigma^2 S^2 V_SS = rV - rS V_S
```

Rearrange:

```text
V_t + 0.5 sigma^2 S^2 V_SS + rS V_S - rV = 0
```

With continuous dividend yield `q`, stock financing drift in the pricing PDE becomes `r - q`:

```text
V_t + 0.5 sigma^2 S^2 V_SS + (r-q)S V_S - rV = 0
```

Key insight:

The derivative price does not depend on real-world expected return `mu`. The hedge removed instantaneous stock direction risk.

### 2.3 Black-Scholes formula outline and Greeks

Under risk-neutral GBM with continuous dividend yield:

```text
dS = (r - q) S dt + sigma S dW^Q
```

Solution:

```text
S_T = S_0 exp((r - q - 0.5 sigma^2)T + sigma sqrt(T) Z)
```

European call payoff:

```text
(S_T - K)^+
```

Price:

```text
C = exp(-rT) E^Q[(S_T - K)^+]
```

Split expectation:

```text
C = exp(-rT) E[S_T 1_{S_T>K}] - K exp(-rT) Q(S_T>K)
```

The second probability:

```text
Q(S_T > K) = N(d2)
```

where:

```text
d2 = [ln(S/K) + (r - q - 0.5 sigma^2)T] / (sigma sqrt(T))
```

Define:

```text
d1 = d2 + sigma sqrt(T)
    = [ln(S/K) + (r - q + 0.5 sigma^2)T] / (sigma sqrt(T))
```

The first truncated expectation is:

```text
E[S_T 1_{S_T>K}] = S exp((r-q)T) N(d1)
```

So:

```text
C = S exp(-qT) N(d1) - K exp(-rT) N(d2)
```

Put:

```text
P = K exp(-rT) N(-d2) - S exp(-qT) N(-d1)
```

Greeks:

Call delta:

```text
Delta = partial C / partial S = exp(-qT) N(d1)
```

Gamma:

```text
Gamma = exp(-qT) n(d1) / (S sigma sqrt(T))
```

Vega:

```text
Vega = partial C / partial sigma = S exp(-qT) n(d1) sqrt(T)
```

Why vega formula simplifies:

When differentiating call price w.r.t. sigma:

```text
partial C/partial sigma =
S exp(-qT) n(d1) partial d1/partial sigma
- K exp(-rT) n(d2) partial d2/partial sigma
```

Use identity:

```text
S exp(-qT) n(d1) = K exp(-rT) n(d2)
```

and:

```text
partial d2/partial sigma = partial d1/partial sigma - sqrt(T)
```

Then terms cancel except:

```text
Vega = S exp(-qT) n(d1) sqrt(T)
```

Rho for call:

```text
Rho = K T exp(-rT) N(d2)
```

Theta follows from differentiating w.r.t. time, or from the PDE relation:

```text
Theta + (r-q)S Delta + 0.5 sigma^2 S^2 Gamma - rV = 0
```

### 2.4 Put-call parity

Construct two portfolios:

Portfolio A:

- Long call.
- Cash `K exp(-rT)`.

Payoff at T:

```text
max(S_T - K,0) + K = max(S_T,K)
```

Portfolio B:

- Long put.
- Long prepaid forward on stock, worth `S exp(-qT)` today.

Payoff at T:

```text
max(K - S_T,0) + S_T = max(S_T,K)
```

Same payoff means same price:

```text
C + K exp(-rT) = P + S exp(-qT)
```

Rearrange:

```text
C - P = S exp(-qT) - K exp(-rT)
```

This is model-free no-arbitrage.

### 2.5 Digital option price

Cash-or-nothing digital call pays 1 if `S_T > K`.

Risk-neutral price:

```text
D_call = exp(-rT) Q(S_T > K)
```

Under risk-neutral lognormal:

```text
ln(S_T/K) = ln(S/K) + (r-q-0.5 sigma^2)T + sigma sqrt(T) Z
```

Condition `S_T > K`:

```text
Z > [-ln(S/K) - (r-q-0.5 sigma^2)T] / (sigma sqrt(T))
```

Therefore:

```text
Q(S_T > K) = N(d2)
```

So:

```text
D_call = exp(-rT) N(d2)
```

Digital put:

```text
D_put = exp(-rT) N(-d2)
```

Why important:

Autocall and coupon triggers are digital-like. Around observation barriers, Greeks can become very large and unstable.

### 2.6 Breeden-Litzenberger derivation

Call price:

```text
C(K,T) = exp(-rT) E[(S_T - K)^+]
```

Write as integral:

```text
C(K,T) = exp(-rT) integral_K^infinity (s - K) f(s) ds
```

Differentiate w.r.t. strike:

Use Leibniz rule:

```text
partial C / partial K
= exp(-rT) [ - (K-K) f(K) + integral_K^infinity partial/partial K (s-K) f(s) ds ]
```

Since `partial(s-K)/partial K = -1`:

```text
partial C / partial K = -exp(-rT) integral_K^infinity f(s) ds
```

That is:

```text
partial C / partial K = -exp(-rT) Q(S_T > K)
```

Differentiate again:

```text
partial^2 C / partial K^2 = exp(-rT) f(K)
```

Therefore:

```text
f(K) = exp(rT) partial^2 C / partial K^2
```

Implication:

If call prices are not convex in strike, implied density is negative somewhere, which is impossible. That is butterfly arbitrage.

### 2.7 Dupire local volatility

Goal:

Find deterministic local volatility `sigma_LV(S,t)` such that the diffusion:

```text
dS_t = (r-q)S_t dt + sigma_LV(S_t,t) S_t dW_t
```

reproduces the full market surface of European call prices `C(K,T)`.

Forward equation idea:

The density `p(S,T)` of `S_T` under local vol satisfies Fokker-Planck:

```text
partial p / partial T
= - partial[(r-q)S p] / partial S
  + 0.5 partial^2[sigma_LV^2(S,T) S^2 p] / partial S^2
```

Call price:

```text
C(K,T) = exp(-rT) integral_K^infinity (S-K) p(S,T) dS
```

Using:

```text
partial^2 C / partial K^2 = exp(-rT) p(K,T)
```

and differentiating call price w.r.t. maturity, one obtains Dupire:

```text
sigma_LV^2(K,T)
= [partial C/partial T + q C + (r-q)K partial C/partial K]
   / [0.5 K^2 partial^2 C/partial K^2]
```

For zero dividends, common simplified form:

```text
sigma_LV^2(K,T)
= [partial C/partial T + r K partial C/partial K]
   / [0.5 K^2 partial^2 C/partial K^2]
```

In total variance coordinates, the formula is expressed using derivatives of `w(k,T)`.

Why use smooth parameterized surface:

Dupire needs first and second derivatives. Raw option quotes are noisy. Differentiating raw quotes creates unstable or negative local variance. Fitting SVI/SSVI first gives a smooth surface whose derivatives are meaningful.

What local vol buys:

- Reprices vanilla options by construction.

What it does not buy:

- Realistic forward smile dynamics.
- Stochastic vol-of-vol.
- Reliable pricing of all path-dependent exotics.

### 2.8 SVI and SSVI

Raw SVI one-slice total variance:

```text
w(k) = a + b [ rho(k-m) + sqrt((k-m)^2 + sigma^2) ]
```

Parameter intuition:

- `a`: vertical level.
- `b`: slope/wing scale.
- `rho`: skew direction and asymmetry.
- `m`: horizontal shift.
- `sigma`: curvature around center.

Why total variance:

```text
w = implied_vol^2 * T
```

Total variance behaves more naturally across maturities and is the right object for no-calendar-arbitrage constraints.

SSVI:

SSVI parameterizes a full surface using ATM total variance `theta_T` and a shape function:

```text
w(k,theta) =
theta/2 * [1 + rho phi(theta) k
 + sqrt((phi(theta) k + rho)^2 + 1 - rho^2)]
```

Why SSVI:

- It links maturities.
- It can enforce calendar no-arbitrage under parameter restrictions.
- It avoids independent SVI slices crossing each other.

### 2.9 Heston model

Heston dynamics:

```text
dS_t = (r-q)S_t dt + sqrt(v_t) S_t dW_t^S
dv_t = kappa(theta - v_t) dt + xi sqrt(v_t) dW_t^v
dW_t^S dW_t^v = rho dt
```

Parameters:

- `v0`: starting variance.
- `theta`: long-run variance.
- `kappa`: mean-reversion speed.
- `xi`: vol of variance, or vol-of-vol.
- `rho`: spot-vol correlation.

Why Heston creates skew:

If `rho < 0`, negative spot moves tend to coincide with variance increases. This creates higher value for downside puts, producing equity skew.

Feller condition:

```text
2 kappa theta >= xi^2
```

This condition keeps the variance process strictly positive. In market calibration it is often violated; simulation must handle near-zero variance robustly.

Why naive Euler is poor:

Euler step:

```text
v_{t+dt} = v_t + kappa(theta-v_t)dt + xi sqrt(v_t) sqrt(dt) Z
```

This can become negative. Taking square root of negative variance is impossible. Truncation helps but biases distribution. Andersen QE approximates the conditional variance distribution more accurately and preserves non-negativity behavior better.

### 2.10 LSV leverage function

LSV model:

```text
dS_t = (r-q)S_t dt + L(S_t,t) sqrt(v_t) S_t dW_t
```

The instantaneous variance conditional on `S_t = K` is:

```text
E[ L(S_t,t)^2 v_t | S_t = K ] = L(K,t)^2 E[v_t | S_t = K]
```

To match local volatility:

```text
L(K,t)^2 E[v_t | S_t = K] = sigma_LV(K,t)^2
```

Therefore:

```text
L(K,t)^2 = sigma_LV(K,t)^2 / E[v_t | S_t = K]
```

Interpretation:

- Local vol gives the marginal distribution needed to fit vanillas.
- Stochastic vol gives realistic dynamics.
- Leverage function rescales stochastic vol locally so vanilla prices remain matched.

### 2.11 Monte Carlo estimator and standard error

Derivative value:

```text
V = E^Q[X]
```

where:

```text
X = sum_j DF(t_j) CF_j(path)
```

Estimator:

```text
V_hat = (1/N) sum_{i=1}^N X_i
```

Unbiased if paths are sampled correctly:

```text
E[V_hat] = V
```

Variance:

```text
Var(V_hat) = Var(X) / N
```

Standard error estimate:

```text
SE = sample_std(X_i) / sqrt(N)
```

Convergence:

```text
Error = O(1/sqrt(N))
```

So reducing error by 10x requires 100x more paths.

### 2.12 Pathwise delta

Let price:

```text
V(S0) = exp(-rT) E[f(S_T)]
```

Under GBM:

```text
S_T = S0 exp((r-q-0.5 sigma^2)T + sigma sqrt(T)Z)
```

Differentiate pathwise:

```text
partial S_T / partial S0 = S_T / S0
```

If `f` is differentiable and regularity conditions allow swapping derivative and expectation:

```text
Delta = partial V / partial S0
= exp(-rT) E[f'(S_T) partial S_T/partial S0]
= exp(-rT) E[f'(S_T) S_T/S0]
```

For call payoff:

```text
f(S_T) = max(S_T - K,0)
f'(S_T) = 1_{S_T > K}
```

So:

```text
Delta = exp(-rT) E[1_{S_T>K} S_T/S0]
```

This equals Black-Scholes call delta.

Why it fails for digitals:

Digital payoff:

```text
f(S_T) = 1_{S_T>K}
```

Derivative is zero almost everywhere and undefined at `K`. Pathwise differentiation misses the moving probability mass at the strike, giving wrong result.

### 2.13 Likelihood-ratio estimator

Let:

```text
V(theta) = integral f(x) p(x;theta) dx
```

Differentiate:

```text
partial V/partial theta
= integral f(x) partial p(x;theta)/partial theta dx
```

Use:

```text
partial p / partial theta = p(x;theta) partial log p(x;theta)/partial theta
```

Therefore:

```text
partial V/partial theta
= E[ f(X) partial log p(X;theta)/partial theta ]
```

This is the likelihood-ratio or score-function estimator.

Why useful:

It differentiates the probability density, not the payoff. So it can handle discontinuous payoffs.

Why higher variance:

The score term can be large in tails and may amplify payoff noise.

### 2.14 AAD reverse-mode derivation

Suppose:

```text
y = f(x1, x2, ..., xn)
```

We want all:

```text
dy/dx_i
```

During forward pass, each intermediate variable is a node:

```text
v_k = g_k(parents)
```

For each parent `v_j`, store local derivative:

```text
partial v_k / partial v_j
```

Define adjoint:

```text
bar{v_k} = partial y / partial v_k
```

Initialize:

```text
bar{y} = 1
```

Backward chain rule:

```text
bar{v_j} += bar{v_k} * partial v_k / partial v_j
```

After reverse sweep:

```text
bar{x_i} = partial y / partial x_i
```

Cost logic:

For one scalar output and many inputs, reverse mode computes all input sensitivities in one backward pass. This is why it is desk-relevant for pricing: one price depends on many market inputs.

### 2.15 P&L attribution derivation

Let price depend on spot, vol, rates and time:

```text
V = V(S, sigma, r, t)
```

Second-order Taylor expansion:

```text
dV approx V_S dS + V_sigma dSigma + V_r dr + V_t dt
        + 0.5 V_SS dS^2
        + 0.5 V_sigmasigma dSigma^2
        + V_Ssigma dS dSigma
```

Map to Greeks:

```text
Delta = V_S
Gamma = V_SS
Vega = V_sigma
Volga = V_sigmasigma
Vanna = V_Ssigma
Rho = V_r
Theta = V_t
```

Then:

```text
dV approx Delta dS + 0.5 Gamma dS^2
          + Vega dSigma + 0.5 Volga dSigma^2
          + Vanna dS dSigma
          + Rho dr
          + Theta dt
```

In practice:

```text
Residual = full_revaluation_PnL - Taylor_explained_PnL
```

### 2.16 XVA derivations

CVA:

At time `t`, if counterparty defaults, loss is approximately:

```text
LGD * positive exposure
```

Expected discounted loss over default intervals:

```text
CVA = sum_i DF(t_i) LGD EE(t_i) PD(default in interval i)
```

Continuous version:

```text
CVA = LGD integral_0^T DF(t) EE(t) dPD(t)
```

If hazard rate is `lambda(t)` and survival is `S(t)`:

```text
dPD(t) = S(t) lambda(t) dt
```

So:

```text
CVA = LGD integral_0^T DF(t) EE(t) S(t) lambda(t) dt
```

FVA:

Funding cost of positive exposure:

```text
FVA approx integral_0^T DF(t) EE(t) funding_spread(t) dt
```

DVA:

Expected benefit from own default on negative exposure:

```text
DVA = own_LGD integral DF(t) ENE(t) dPD_own(t)
```

KVA:

Cost of capital:

```text
KVA = integral DF(t) cost_of_capital * capital(t) dt
```

MVA:

Funding cost of initial margin:

```text
MVA = integral DF(t) funding_spread(t) IM(t) dt
```

All-in charge:

```text
Total XVA = CVA + FVA + KVA + MVA - DVA
```

All-in structuring:

```text
PV_target = par - fee - Total_XVA
```

---

## 3. Autocallable and Phoenix Questions: Full Answers

### 3.1 Explain an autocallable to a non-technical client

"You invest a notional amount linked to an equity index or basket. On scheduled observation dates, if the underlying is at or above a specified level, the note redeems early and pays you your principal plus coupon. If it does not redeem, you may still receive coupons if the underlying is above a coupon barrier. At maturity, if the underlying has not fallen too far, you receive principal back. But if it has breached the downside condition, your principal can fall with the underlying."

Client-safe line:

"The coupon is high because you are taking conditional equity downside risk and issuer credit risk. It is not a guaranteed high-yield deposit."

### 3.2 Explain an autocallable to a hedge fund volatility PM

"It is a path-dependent short-skew/short-vol yield product with digital coupon and autocall triggers, barrier-linked terminal downside and strong state-dependent Greeks. It monetizes downside skew and often creates short convexity around barriers. The key risks are spot-vol dynamics, barrier gap, skew, forward/dividend assumptions, autocall probability, and in baskets, correlation/dispersion."

### 3.3 Decompose an autocallable into simpler options

No exact universal static decomposition exists for all autocallables because of path-dependent callability and conditional coupons, but conceptually:

- Bond/funding leg: redemption of principal if conditions allow.
- Coupon digitals: cash coupons conditional on spot above coupon barrier at observation dates.
- Autocall digitals: early redemption conditional on spot above autocall barrier.
- Downside knock-in put exposure: investor bears losses if barrier condition is hit or terminal level is below threshold.

Approximate intuition:

```text
Autocallable = bond + coupon digitals - investor-sold downside option package - issuer callability
```

### 3.4 What risk is the investor selling?

The investor sells:

- Downside crash risk.
- Volatility and skew risk.
- Gap risk around barrier.
- Conditional callability risk.
- Correlation/dispersion risk for baskets.
- Liquidity risk if exiting before maturity.
- Issuer credit risk by holding the note.

### 3.5 Why does a higher coupon require worse protection or more restrictive terms?

The note must satisfy fair value:

```text
PV(cashflows) = par - fee - XVA
```

Higher coupon increases investor value. To keep PV fixed, the investor must give something back:

- Higher knock-in barrier, so downside protection is weaker.
- Higher coupon barrier, so coupons are harder to receive.
- More volatile or worse underlying.
- Longer tenor.
- Worse autocall terms.
- Lower protection.
- More names in worst-of basket.

There is no free coupon. Coupon is paid for risk.

### 3.6 Why does the note often have negative vega?

For the investor, higher vol increases downside barrier/put value and makes bad tail outcomes more likely. Since the investor has sold that optionality, the note value generally falls as vol rises. Thus investor vega is often negative.

Nuance:

Near autocall dates, local vega may flip because higher vol can reduce autocall probability and extend coupon opportunity. But the broad structural exposure is short volatility/skew.

### 3.7 Can vega ever be positive locally?

Yes. Example: spot is above the coupon barrier but close to autocall level shortly before observation. Higher vol might reduce probability of immediate autocall, allowing the investor to remain in the note and potentially receive more future coupons. Depending on coupon richness and downside barrier distance, local vega can become positive.

Interview line:

"I would not claim a universal vega sign. I would compute vega by state and supplement with vol-up/down scenario tables."

### 3.8 Gamma profile near autocall date

Near an autocall observation level, payoff changes discontinuously or nearly discontinuously with spot. Small spot moves can materially change probability of early redemption. This creates digital-like delta and gamma behavior:

- Delta can jump.
- Gamma can spike.
- Hedging becomes unstable.
- Discrete hedging error rises.

If the bank is short digital convexity around the barrier, hedging pressure can become large as spot pins near autocall level.

### 3.9 Gamma profile near knock-in barrier

Near knock-in barrier, small spot moves can change the probability or state of downside principal loss. This creates large negative convexity for the investor and large hedging difficulty for the dealer.

Key risk:

Gap through barrier cannot be hedged with continuous delta assumptions. Liquidity usually worsens exactly when barrier risk increases.

### 3.10 What happens if underlying rallies strongly after issuance?

Likely outcomes:

- Note may autocall at first observation.
- Duration shortens.
- Future coupon optionality disappears.
- Investor receives principal plus coupon but gives up further upside.
- Dealer unwinds hedges and releases risk.

Client explanation:

"A strong rally is not like owning the stock. You may get called away and stop participating."

### 3.11 What happens if underlying sells off 25% and vol doubles?

Likely:

- Autocall probability collapses.
- Note extends in maturity.
- Mark-to-market falls.
- Downside barrier probability increases.
- Vega/skew losses occur.
- Gamma and gap risk increase near knock-in.
- Secondary liquidity worsens.
- Dealer hedging becomes more difficult.

This is the bad path: spot down, vol up, skew steepens, correlation up for baskets, funding and credit spreads may widen.

### 3.12 Why does skew matter?

Autocallables contain downside optionality. Equity skew makes downside puts more expensive than upside calls at the same absolute moneyness. A steeper put skew increases the value of the downside protection sold by the investor and affects fair coupon, barrier value, and hedging.

### 3.13 Why do dividends matter?

Equity derivatives price off forwards:

```text
F = S exp((r-q)T)
```

Higher dividend yield lowers forward. For long-dated equity structures, dividend assumptions affect:

- Autocall probability.
- Barrier hitting probability.
- Option values.
- Delta.
- Fair coupon.

Discrete dividends can matter around observation dates and barriers.

### 3.14 How do rates affect coupon?

Rates affect:

- Discounting of future coupons/principal.
- Forward levels through `r - q`.
- Zero-coupon funding cost.
- Capital-protected participation budget.
- Issuer funding curves.

For yield notes, higher rates can make bond funding components cheaper/more attractive, but exact coupon impact depends on payoff and discounting conventions.

### 3.15 How does issuer funding affect coupon?

A structured note is issuer debt. If issuer funding spread widens, the issuer's cost of promising future cashflows changes. Depending on pricing convention, higher funding cost reduces the value available for investor coupon and affects secondary marks.

In SPDT, funding legs are separated from option legs, so issuer funding directly affects note economics.

### 3.16 What happens if observation frequency increases?

More frequent observations can:

- Increase chance of autocall.
- Increase chance coupons are paid if coupon observations are frequent.
- Change average note life.
- Increase digital event risk.
- Affect value depending on coupon accrual and autocall schedule.

There is no universal sign; solve to par and compare.

### 3.17 What happens if autocall trigger steps down?

Step-down autocall levels make autocall more likely later in the trade. This usually benefits the issuer by shortening exposure in lower spot states and can make the note more attractive to clients because it increases redemption probability. It changes coupon economics and can reduce expected maturity.

### 3.18 What is a Phoenix autocallable?

A Phoenix note is an autocallable with conditional coupons, often with memory. If the underlying is above the coupon barrier on an observation date, coupon pays. If below, coupon may be missed or stored as memory. Autocall occurs if the underlying is above the autocall barrier.

### 3.19 What is memory coupon?

If a coupon is missed because the underlying is below coupon barrier, it accrues. At a future observation date, if the coupon condition is met, the note pays current coupon plus missed coupons.

Memory increases investor value and increases issuer optionality cost.

### 3.20 What is snowball coupon?

A snowball coupon increases over time or accumulates based on missed coupon periods or note survival. It makes payoff more path-dependent and can increase extension risk and coupon convexity.

### 3.21 Why can autocallables create dealer hedging pressure near barriers?

Near barriers:

- Delta changes rapidly.
- Gamma spikes.
- Autocall or knock-in probability changes sharply.
- Dealers may need to buy into rallies or sell into selloffs depending on book sign.
- Liquidity can be thin.

This creates feedback risk, especially if many dealers have similar exposure.

### 3.22 How would you hedge delta?

Use:

- Underlying stock.
- Index futures.
- ETFs.
- Delta-equivalent baskets.

Process:

- Compute model delta.
- Aggregate book delta.
- Hedge net exposure.
- Rebalance dynamically.
- Watch barrier regions where delta changes quickly.

### 3.23 How would you hedge vega?

Use:

- Listed options by tenor/strike.
- OTC options.
- Variance swaps where liquid.
- Proxy hedges if direct instruments unavailable.

Important:

Vega must be bucketed by expiry and strike/skew, not treated as one flat number.

### 3.24 How would you hedge skew?

Use options with strikes around downside barriers or skew-sensitive structures:

- Put spreads.
- Risk reversals.
- Downside puts.
- Option portfolios matching vanna/skew exposure.

Skew hedging is imperfect because liquidity is concentrated in listed maturities/strikes while structured products are long-dated and path-dependent.

### 3.25 How would you hedge correlation in a worst-of?

Possible hedges:

- Dispersion trades: index options vs single-name options.
- Basket options.
- Correlation swaps, if available.
- Proxy hedges using index and constituents.
- Reduce concentration through product limits.

Residual risks:

- Correlation skew.
- Tail dependence.
- Single-name gap risk.
- Liquidity.
- Basis between hedge basket and note basket.

### 3.26 Why is gap risk unhedgeable with delta hedging?

Delta hedging assumes continuous trading and continuous price paths. In reality:

- Markets jump.
- Trading is discrete.
- Liquidity can vanish.
- Barriers can be crossed overnight.

If spot gaps through a barrier, the hedge cannot be adjusted at intermediate prices. The loss is not captured by local delta alone.

### 3.27 Why can an autocallable book have negative convexity?

Negative convexity means the position loses from large moves in either direction or has unfavorable gamma. Autocallables can have negative convexity because:

- Downside barrier creates large losses in selloffs.
- Upside autocall caps continuation value.
- The investor gives up strong upside but retains downside.
- Dealer hedging may involve short gamma regions near triggers.

### 3.28 What would you disclose in a term sheet?

Disclose:

- Underlying(s), initial fixing, observation dates.
- Coupon rate, coupon barrier, memory feature.
- Autocall trigger and redemption mechanics.
- Knock-in/barrier and principal loss formula.
- Maximum gain and maximum loss.
- Issuer credit risk.
- Secondary market liquidity risk.
- Fees/margin if required.
- Tax/regulatory disclaimers.
- Scenario table.
- Risk factors: market, volatility, correlation, dividends, FX/quanto if relevant.

### 3.29 Fair coupon vs offered coupon

Fair coupon is the model-implied coupon that makes PV equal par before commercial adjustments.

Offered coupon is what the client receives after:

- Bank margin.
- Bid/offer.
- Hedging costs.
- Funding.
- XVA.
- Capital.
- Distribution costs.
- Rounding and commercial constraints.

### 3.30 How would CVA reduce client coupon?

CVA is a cost to the bank. If target equation is:

```text
PV = par - fee
```

then after CVA:

```text
PV = par - fee - CVA
```

To reduce PV, the coupon must be lower or terms must be less favorable. Wider counterparty spread increases CVA and reduces all-in coupon.

---

## 4. BRC, Reverse Convertible, CPN, Worst-of: Full Answers

### 4.1 Why is coupon fixed/unconditional in a BRC?

In a barrier reverse convertible, the investor sells downside option risk in exchange for a fixed coupon. The coupon is compensation for selling the down-and-in put. It does not depend on interim spot conditions like a Phoenix coupon. The downside barrier affects principal repayment at maturity, not coupon entitlement.

### 4.2 Why does adding a barrier reduce coupon vs plain reverse convertible?

Plain reverse convertible:

```text
RC = bond + coupon - vanilla put
```

BRC:

```text
BRC = bond + coupon - down-and-in put
```

A down-and-in put is less valuable than a vanilla put because it only activates if the barrier is breached. Since the investor sells a less valuable option, they receive less premium, so fair coupon is lower.

### 4.3 What happens as BRC barrier moves lower?

Lower barrier means knock-in is less likely. The down-and-in put becomes less valuable. Investor sells less risk, so fair coupon decreases.

### 4.4 What happens as strike moves higher?

Higher put strike increases potential put payoff:

```text
max(K - S_T,0)
```

The embedded down-and-in put becomes more valuable. Investor sells more downside risk, so fair coupon increases.

### 4.5 What happens as vol rises in a BRC?

Higher vol increases probability of hitting the barrier and increases put value. The down-and-in put becomes more valuable. Since the investor is short that option, they require higher coupon at issuance and suffer mark-to-market loss after issuance.

### 4.6 How does discrete barrier monitoring affect fair coupon?

Discrete monitoring reduces knock-in probability relative to continuous monitoring. A less likely knock-in makes the down-and-in put less valuable, reducing fair coupon. If a model checks barriers only at coarse simulation dates when actual terms are continuous, it underprices knock-in risk.

### 4.7 Who is long the down-and-in put in a BRC?

The investor is short the down-and-in put. The issuer is economically long the embedded down-and-in put, but also owes bond and coupon cashflows. After hedging, the bank's residual exposure depends on hedge execution and model dynamics.

### 4.8 Is BRC suitable for a conservative investor?

Usually not if "conservative" means cannot tolerate equity principal loss. A BRC has bond-like coupons but equity downside risk. It can be suitable only for a client who understands and accepts downside exposure, issuer credit risk and liquidity risk.

### 4.9 Why is RC coupon generally higher than BRC coupon?

The RC investor sells a vanilla put that is always live. The BRC investor sells a down-and-in put that only activates if the barrier is breached. Vanilla put is more valuable, so RC coupon is higher.

### 4.10 Why do high rates improve CPN participation?

In a capital-protected note, part of notional buys a zero-coupon bond that returns protected principal at maturity:

```text
ZCB cost = protection * notional * exp(-rT)
```

Higher rates lower the present cost of the ZCB, leaving more money to buy calls. More option budget means higher participation or higher cap.

### 4.11 Why does high vol reduce CPN participation?

The upside option becomes more expensive when implied vol rises. With fixed option budget, the note can buy fewer calls, so participation decreases or cap is lowered.

### 4.12 Tradeoff between protection and upside

Higher protection requires more budget for the bond component. Less budget remains for options, reducing participation or cap. Lower protection frees option budget but exposes investor to more downside.

### 4.13 Why cap upside?

A cap turns a call into a call spread:

```text
long call at K1 - short call at K2
```

The short call funds more participation or better protection. Client gives up extreme upside to improve coupon/participation economics.

### 4.14 Why prefer CPN to direct equity?

A client may want equity upside but cannot tolerate principal loss at maturity. CPN offers defined downside protection subject to issuer credit risk and holding to maturity. Tradeoff: capped/partial upside, issuer credit, liquidity, fees.

### 4.15 What risks remain despite capital protection?

- Issuer credit risk.
- Mark-to-market loss before maturity.
- Liquidity risk.
- Opportunity cost if equity rallies beyond cap.
- Inflation/rate risk.
- Tax treatment.
- Protection may apply only at maturity, not during life.

### 4.16 Why does worst-of give higher coupon?

Worst-of notes expose the investor to the weakest asset. More underlyings and lower correlation increase probability that at least one name performs poorly. The investor sells more downside/dispersion risk, so coupon is higher.

### 4.17 How do you simulate a worst-of basket?

1. Choose initial spots `S_i(0)`, vols, dividends, rates.
2. Build correlation matrix.
3. Repair to PSD if needed.
4. Cholesky decompose:

```text
L L^T = Corr
```

5. Generate independent normals `Z`.
6. Correlate shocks:

```text
epsilon = L Z
```

7. Simulate each asset under risk-neutral dynamics.
8. Compute returns:

```text
R_i(t) = S_i(t) / S_i(0)
```

9. Worst-of level:

```text
W(t) = min_i R_i(t)
```

10. Apply coupon/autocall/barrier rules to `W(t)`.

### 4.18 What if correlation matrix is not PSD?

Cholesky fails because a non-PSD matrix is not a valid covariance/correlation matrix. Fix by:

- Eigenvalue clipping.
- Higham nearest correlation matrix.
- Shrinkage toward identity.
- Re-estimation with robust method.

Then re-normalize diagonal to 1.

---

## 5. Volatility Surface Answers

### 5.1 What is implied vol?

Implied volatility is the volatility input that makes Black-Scholes price equal the market option price:

```text
BS(S,K,T,r,q,sigma_imp) = market price
```

It is a quote convention, not a direct forecast. It includes risk premia, supply/demand, crash risk and liquidity.

### 5.2 Why is implied vol not realized vol?

Realized vol is historical or future actual movement of the underlying. Implied vol is the market price of option risk converted into a Black-Scholes volatility. Implied usually includes volatility risk premium and crash insurance demand.

### 5.3 Why does skew exist?

Equity skew exists because:

- Investors demand downside protection.
- Equity selloffs are associated with higher volatility.
- Crash jumps are more likely/priced than Black-Scholes assumes.
- Dealers charge premium for warehousing downside risk.

### 5.4 What is total variance?

```text
w(K,T) = sigma_imp(K,T)^2 * T
```

It is cumulative variance to maturity. It is smoother and more natural for surface modeling than raw volatility.

### 5.5 Why fit in log-moneyness?

Log-moneyness:

```text
k = ln(K/F)
```

It centers the smile around the forward, adjusts for rates/dividends, and gives more stable cross-maturity comparison.

### 5.6 What are SVI parameters?

In:

```text
w(k) = a + b [rho(k-m) + sqrt((k-m)^2 + sigma^2)]
```

- `a`: base variance level.
- `b`: wing slope scale.
- `rho`: skew/asymmetry.
- `m`: horizontal shift.
- `sigma`: curvature.

### 5.7 How check butterfly arbitrage?

Convert vol surface to call prices and check convexity in strike:

```text
partial^2 C / partial K^2 >= 0
```

In SVI total variance, use Durrleman condition `g(k) >= 0` across a dense grid. Negative density means arbitrage.

### 5.8 How check calendar arbitrage?

At fixed log-moneyness:

```text
partial w(k,T) / partial T >= 0
```

Total variance should not decrease with maturity. Also check option prices across tenors with carry adjustments.

### 5.9 Why does Dupire need smooth derivatives?

Dupire uses `partial C/partial T`, `partial C/partial K`, and `partial^2 C/partial K^2`, or equivalent total-variance derivatives. Differentiating noisy quotes magnifies noise and can produce negative local variance. Smooth arbitrage-aware parameterization is essential.

### 5.10 Why can local vol explode?

Local variance formula has a denominator linked to implied density and surface curvature. If density is near zero, surface is noisy, calendar derivative is wrong, or butterfly arbitrage exists, denominator can be tiny/negative and local vol explodes.

### 5.11 Sticky strike vs sticky delta

Sticky strike:

- Vol at fixed strike stays constant when spot moves.
- Useful for small moves and listed option marks.

Sticky delta:

- Vol at fixed delta/moneyness stays constant.
- Smile moves with spot.

Difference matters because delta includes smile response. Structured products with skew exposure can have materially different hedges under each assumption.

### 5.12 How does skew affect autocallable coupons?

Steeper downside skew increases value of downside puts/barriers sold by investor, so fair coupon for yield notes can rise. But it also worsens mark-to-market for existing investors who are short that skew.

### 5.13 Why do wings matter even if strikes are near ATM?

Path-dependent products can visit wing states. Barrier probabilities, tail losses, stress scenarios and MC paths depend on the whole distribution, not just current ATM. Extrapolated wings can dominate tail valuation.

### 5.14 How do dividends affect equity vol calibration?

Dividends determine forwards:

```text
F = S exp((r-q)T)
```

Wrong dividends shift log-moneyness and distort implied vol/skew. For single stocks, discrete dividends around ex-div dates matter.

### 5.15 What is forward variance?

Forward variance between `T1` and `T2`:

```text
fvar(T1,T2) = [w(T2) - w(T1)] / (T2 - T1)
```

where `w(T)=sigma_ATM(T)^2 T`.

It is the market-implied variance over a future interval.

### 5.16 What is variance swap fair strike?

The fair variance strike is the risk-neutral expected realized variance. It can be replicated by a strip of OTM options:

```text
K_var approx (2/T) integral_0^F P(K)/K^2 dK
             + (2/T) integral_F^infinity C(K)/K^2 dK
```

plus discrete/forward adjustments.

### 5.17 How interpolate/extrapolate sparse surface?

- Clean quotes first.
- Use forward moneyness.
- Fit smooth parameterization like SVI/SSVI.
- Weight by liquidity/bid-offer.
- Enforce no-arbitrage constraints.
- Extrapolate wings with controlled slopes.
- Validate by density and local-vol stability.

### 5.18 How handle illiquid quotes?

- Remove stale/zero-volume quotes.
- Use bid/offer mids carefully.
- Down-weight wide spreads.
- Prefer liquid strikes.
- Mark reserves for uncertain wings.
- Compare broker marks and historical behavior.

### 5.19 Bid/offer vol marks

Option markets have bid and offer implied vols. Mid is not executable. Desk marks may use mid, bid, offer or prudent valuation depending on accounting/risk. Bid/offer creates reserve/unwind cost.

### 5.20 What is vol reserve?

A reserve held for uncertainty in vol marks, model calibration or bid/offer costs. For example:

```text
reserve = 0.5 * |PV(vol_offer) - PV(vol_bid)|
```

---

## 6. Correlation and Basket Answers

1. Correlation measures linear co-movement:

```text
rho_ij = Cov(X_i,X_j)/(sigma_i sigma_j)
```

2. Covariance has units and measures joint variation. Correlation is normalized covariance between -1 and 1.

3. Correlation matrix must be PSD because portfolio variance must be non-negative:

```text
w^T Corr w >= 0
```

4. If Cholesky fails, the matrix is not valid for simulation. Repair it before generating correlated paths.

5. Repair methods: eigenvalue clipping, Higham nearest correlation, shrinkage to identity, or robust re-estimation.

6. Higham PSD repair finds the nearest valid correlation matrix under a matrix norm while preserving unit diagonal as much as possible.

7. Historical correlation is backward-looking, regime-dependent and may not reflect implied or stressed correlation.

8. Implied correlation is the correlation level inferred from prices of index and constituent options or basket derivatives.

9. Since index variance depends on constituent variances and correlations:

```text
Var(index) = sum_i w_i^2 Var_i + 2 sum_{i<j} w_i w_j rho_ij sigma_i sigma_j
```

index options plus single-name options imply average correlation.

10. Dispersion trading trades index volatility against single-name volatility, often expressing a view on correlation.

11. Worst-of is correlation-sensitive because payoff depends on the minimum asset return, which is driven by joint distribution and dispersion.

12. Worst-of autocallable correlation sign is state-dependent. Investors are often short dispersion/low-correlation risk, but near autocall barriers the sign can change.

13. Sign can change because correlation affects both downside worst-name probability and probability all names are above autocall/coupon barriers.

14. Tail dependence is the tendency of assets to crash together in extremes.

15. Gaussian copula has zero tail dependence, so it can understate joint crash clustering.

16. Correlation stress should be coherent: equity down, vol up, skew steeper, correlations up for systemic crash; also test correlation down for worst-of dispersion risk.

17. Correlation rises in selloffs because macro/systemic factors dominate idiosyncratic factors and investors de-risk together.

18. Correlation skew means implied correlation varies by strike/maturity, often higher in downside states.

19. Hedge correlation with dispersion, basket options, index vs single-name option packages, or limits/proxy hedges.

20. Residual risks after single-name delta hedging: correlation, vol, skew, gap, dividends, borrow, liquidity, basis and tail dependence.

---

## 7. Pricing and Numerical Methods Answers

1. MC for autocallables because payoff is path-dependent, has observation dates, early redemption, barriers, coupons and possibly multiple underlyings.

2. Choose time grid to include all observation/coupon/barrier dates plus enough substeps for model dynamics and barrier monitoring.

3. Include observation dates exactly because coupon/autocall decisions happen on those dates. Missing them misprices the payoff.

4. Antithetic sampling uses `Z` and `-Z` pairs to reduce variance.

5. Control variate prices a related payoff with known value and uses its simulation error to reduce target estimator variance.

6. Quasi-MC uses low-discrepancy sequences to improve convergence for smooth integrands.

7. Common random numbers reduce noise in differences such as finite-difference Greeks.

8. Standard error:

```text
SE = sample_std(discounted payoff) / sqrt(N)
```

9. Enough paths means MC standard error is small relative to bid/offer, materiality threshold, and sensitivity needs. Exotics may need more paths for Greeks than price.

10. Model error often matters more than MC error once standard error is controlled. A precisely wrong model is still wrong.

11. Price barriers with fine grids, Brownian bridge corrections, BGK correction or analytic benchmarks where available.

12. Brownian bridge correction estimates probability of barrier crossing between simulated time steps conditional on endpoints.

13. BGK correction shifts barrier to approximate continuous monitoring under discrete simulation.

14. Crank-Nicolson is an implicit/explicit finite-difference scheme, second-order in time for PDEs, commonly used for option pricing.

15. PDE oscillates near discontinuities because payoff/barrier conditions are not smooth; numerical schemes can create ringing.

16. Rannacher smoothing uses initial implicit Euler steps to damp oscillations before Crank-Nicolson.

17. Euler is poor for Heston variance because variance can become negative and distribution is biased.

18. QE scheme approximates conditional distribution of variance in Heston with a quadratic-exponential form, improving positivity and accuracy.

19. Calibration error is difference between model prices and market prices of calibration instruments.

20. Validate pricer with analytic benchmarks, convergence tests, put-call parity, MC standard error, regression tests, Greeks consistency and limiting cases.

21. Benchmark MC against Black-Scholes for vanillas, analytic barrier formulas, PDE for low-dimensional products, and independent implementation.

22. Pathwise delta fails for digitals because payoff derivative is zero almost everywhere and undefined at the trigger.

23. LR is higher variance because it multiplies payoff by score function, which can be noisy in tails.

24. AAD is reverse-mode differentiation of pricing computation to get many sensitivities efficiently.

25. Test AAD by comparing to bump-and-revalue, analytic Greeks, pathwise estimators where valid, and convergence under bump size/paths.

---

## 8. Greeks, Hedging and P&L Answers

### 8.1 What is delta hedging?

Delta hedging offsets first-order spot sensitivity by trading underlying:

```text
portfolio_delta + hedge_units = 0
```

It is local and must be rebalanced as spot and time change.

### 8.2 What is discrete hedging error?

Continuous Black-Scholes hedging assumes continuous trading. In reality, hedge is rebalanced discretely. Between rehedges, delta changes and spot moves, producing hedging P&L error.

### 8.3 What is gap risk?

Loss from jumps or discontinuous market moves across barriers or through hedge levels. It cannot be eliminated by delta hedging.

### 8.4 Vega hedging

Vega hedging offsets sensitivity to implied volatility using options or variance products. It should be bucketed by expiry and strike because vol surface moves are not parallel.

### 8.5 Skew hedging

Skew hedging offsets changes in relative downside vs upside implied vol. Use risk reversals, put spreads or strike-bucketed option hedges.

### 8.6 Correlation hedging

Use dispersion trades, index vs single-name options, basket options or correlation swaps. In practice, correlation hedging is proxy-heavy and imperfect.

### 8.7 Dividend risk

Risk that actual or implied dividends differ from assumptions. Dividends change forwards and option values. Important for long-dated single-stock products.

### 8.8 Funding risk

Risk that issuer or desk funding spreads change, affecting note valuation and hedge financing.

### 8.9 Liquidity risk

Risk that hedges cannot be executed at model prices or client exits cannot be priced near theoretical value.

### 8.10 Model risk

Risk that chosen model misprices the product because assumptions about volatility, correlation, rates, dividends or dynamics are wrong.

### 8.11 Why compute explain using yesterday's Greeks?

P&L explain asks: given the risk we had yesterday, how much P&L should today's market moves have produced? Using today's Greeks would contaminate explain with post-move risk.

### 8.12 Full revaluation P&L

Actual model mark change:

```text
PV(today market, aged trade) - PV(yesterday market, yesterday trade)
```

### 8.13 Taylor P&L

Approximation using Greeks and factor moves:

```text
Delta dS + 0.5 Gamma dS^2 + Vega dVol + ...
```

### 8.14 Why bucketed vega?

A structured note may be sensitive to different tenors/strikes. A single flat vega cannot explain a surface twist or skew steepening. Bucketed vega identifies which maturity/strike drove P&L.

### 8.15 Vanna P&L

Vanna is cross sensitivity:

```text
Vanna = partial^2 V / partial S partial sigma
```

Vanna P&L:

```text
Vanna * dS * dSigma
```

Important when spot and vol move together, as in equity selloffs.

### 8.16 Volga P&L

Volga is convexity to vol:

```text
Volga = partial^2 V / partial sigma^2
```

P&L:

```text
0.5 * Volga * dSigma^2
```

### 8.17 How does skew move create P&L?

If downside implied vols rise more than ATM, products short downside skew lose. Flat vega may miss this; strike-bucketed vega/skew risk is needed.

### 8.18 Dividends and P&L

Dividend marks change forwards. For equity structures, this affects autocall probability, option moneyness, delta and PV. Unexpected dividend changes can create residual if not in explain.

### 8.19 Model recalibration P&L

When model parameters are recalibrated to new market quotes, PV can change even if simple risk factors appear unchanged. This can show up as residual or model P&L.

### 8.20 Risk questions after large residual

Risk manager asks:

- Which trades caused it?
- Which risk factor missing?
- Did market data change?
- Did product hit observation/coupon date?
- Is MC noise controlled?
- Did model recalibrate?
- Are cashflows booked correctly?
- Is hedge P&L aligned with theoretical P&L?

### 8.21 How reduce residual?

- Add missing risk factors.
- Use bucketed surface risk.
- Use full revaluation explain by factor.
- Improve model/Greek accuracy.
- Increase MC paths/use CRN.
- Separate realized cashflows.
- Improve data controls.

---

## 9. Structuring and Client Scenario Answers

### 9.1 How choose product for yield-seeking client?

Start with client view and risk tolerance. If they are moderately bullish/range-bound and accept downside risk, consider autocallable/Phoenix or BRC. If they cannot tolerate principal risk, consider capital-protected note but yield will be lower.

### 9.2 How choose underlyings?

Prefer liquid, transparent underlyings with available hedges:

- Indices for diversified exposure and liquidity.
- Single stocks only if client understands idiosyncratic risk.
- Worst-of baskets only for sophisticated clients accepting correlation/dispersion risk.

### 9.3 How choose barrier?

Barrier reflects protection vs coupon tradeoff. Lower barrier gives more protection and lower coupon. Choose based on client drawdown tolerance, historical stress, implied skew and fair value.

### 9.4 How choose tenor?

Longer tenor can support higher coupon but adds more uncertainty, issuer credit risk and liquidity risk. Match tenor to client horizon and hedge liquidity.

### 9.5 Observation frequency

More frequent observations can increase coupon/autocall event probability and path-dependence. Use client income preference, operational simplicity and fair-value impact.

### 9.6 Memory vs non-memory

Memory is better for clients but costs more. It suits clients who want income recovery if market temporarily dips. Non-memory offers higher headline coupon for same economics or cheaper issuer cost.

### 9.7 Maximize coupon without hiding risk

Show tradeoffs explicitly:

- Higher barrier.
- More names.
- Longer tenor.
- Higher coupon barrier.
- Less protection.

Then disclose scenario losses. Do not optimize coupon by making risk opaque.

### 9.8 Improve protection while keeping coupon

Possible levers:

- Lower participation/coupon.
- Add cap.
- Use less volatile underlying.
- Shorten tenor.
- Reduce memory.
- Accept lower issuer margin.
- Use call spread/collar features.

There is no free improvement.

### 9.9 Monthly income

Use monthly coupon observations, but price higher path dependence and operational complexity. Monthly coupons may have lower per-period coupon or higher barriers.

### 9.10 Bullish client

Use participation note, call spread note, capital-protected upside note, or leveraged upside note. Autocallable may cap upside and is not pure bullish exposure.

### 9.11 Bearish client

Use put spread, bear note, capital-protected bearish note, or collar. Do not sell them downside-risk yield product if they expect a crash.

### 9.12 Capital protection

Use zero-coupon bond plus calls/call spreads. Explain issuer credit risk and maturity-only protection.

### 9.13 If rates rise

CPNs improve because ZCB protection costs less. For yield products, discounting/funding/forwards change; solve model rather than rely on one sign.

### 9.14 If vol rises

Yield notes can offer higher coupons at issuance because investor sells richer optionality. Existing investors usually lose MTM. CPN participation worsens because calls cost more.

### 9.15 If skew steepens

Downside protection becomes more expensive. Yield note coupons may rise for new issuance, but existing investors short skew lose.

### 9.16 If correlation rises

Worst-of effect depends on state. It can improve dispersion-driven worst-of risk but worsen systemic crash stress. Always run correlation scenarios.

### 9.17 Product benefiting from low vol

Capital-protected upside notes and call participation notes benefit because options are cheaper, increasing participation. Yield products offer lower coupon in low vol.

### 9.18 Product benefiting from high vol

Yield-enhancement products at issuance can offer higher coupons because investor sells expensive optionality. But they are riskier.

### 9.19 Product benefiting from high rates

Capital-protected notes benefit because protection ZCB is cheaper. Some coupon notes also benefit through discounting/funding but product-specific.

### 9.20 Include issuer fee

Target:

```text
PV = par - fee
```

Fee reduces value available to client, lowering coupon or worsening terms relative to fair mid.

### 9.21 Include XVA

Target:

```text
PV = par - fee - XVA
```

XVA lowers all-in coupon or changes terms.

### 9.22 Explain worst-case loss

Use cash numbers:

"If the index falls 50% and the knock-in condition is met, you may receive only 50% of notional at maturity, plus any coupons already paid, subject to issuer credit."

### 9.23 Scenario table

Show:

- Large rally.
- Mild rally.
- Flat.
- Moderate fall above barrier.
- Fall below barrier.
- Severe crash.
- Early autocall.
- No autocall.

Include coupon, principal, total return and issuer credit caveat.

### 9.24 Compare to direct equity

Autocallable:

- Higher income if range-bound.
- Gives up upside after autocall.
- Has downside barrier risk.
- Has issuer credit risk.
- Less liquidity.

Direct equity:

- Full upside/downside.
- No issuer credit.
- More liquid.

### 9.25 Compare to bond

Structured note:

- Higher coupon potential.
- Equity-linked principal risk.
- Issuer credit risk.
- Complex liquidity.

Bond:

- Contractual coupons.
- Credit/rate risk.
- No equity barrier risk.

---

## 10. XVA, CCR and Governance Answers

1. CVA: expected discounted counterparty default loss.

2. DVA: expected discounted benefit from own default on negative exposure.

3. FVA: funding valuation adjustment, cost/benefit of funding uncollateralized exposure.

4. KVA: cost of capital held against the trade.

5. MVA: cost of funding initial margin.

6. XVA is not just an add-on because it changes trade economics, approval, limits, hedging and client terms.

7. CVA reduces coupon because it consumes value that otherwise could be paid to client.

8. Autocallable exposure: simulate paths, mark remaining note value at each future time conditional on state, take positive exposure distribution.

9. Mark-to-future NPV cube is needed because XVA depends on exposure profile over time and paths, not just today's PV.

10. EE collapses after autocall dates because redeemed paths leave the book and future exposure becomes zero for those paths.

11. PFE is potential future exposure: a high quantile of exposure distribution at future time.

12. EAD is exposure at default, often regulatory/capital exposure measure such as alpha times EEPE.

13. EEPE is effective expected positive exposure, a time-averaged/nondecreasing regulatory-style exposure measure.

14. Wrong-way risk: exposure increases when counterparty credit quality worsens.

15. Netting: offsetting positive and negative NPVs within a legal netting set before exposure is measured.

16. Net before positive exposure because default closeout is on net portfolio value, not trade-by-trade positives.

17. Collateral threshold: exposure amount allowed before collateral must be posted.

18. MTA: minimum transfer amount below which collateral is not moved.

19. MPoR: margin period of risk, time between last collateral exchange and closeout/rehedging after default.

20. Initial margin: collateral posted to cover potential future exposure over closeout period.

21. SA-CCR: standardized approach for counterparty credit risk exposure measurement.

22. Economic capital: internal capital needed to absorb unexpected loss.

23. RAROC: risk-adjusted return on capital.

24. A trade can be rejected if it breaches limits, has low RAROC, high wrong-way risk, insufficient margin, or suitability concerns.

25. Wider counterparty credit spread increases default probability/CVA, reducing all-in coupon or requiring better collateral/terms.

---

## 11. Project-Specific Attack Answers

### 11.1 Why build a digital twin instead of a pricer?

A pricer answers "what is this trade worth today?" A desk twin answers "how does this trade get originated, priced, hedged, explained, reserved, stressed, reported and approved?" Equity structuring interviews care about the whole lifecycle. The project shows product design, model selection, Greeks, P&L, reserves and XVA, not just a one-off option price.

### 11.2 Why "snapshot in, report out"?

Every result must be reproducible. If a layer fetches live data directly, yesterday's P&L explain can change when market data changes. A versioned snapshot freezes spot, rates, dividends, vol, correlation and metadata, allowing backtests, P&L explains and model validation to be audited.

### 11.3 Why product DSL/cashflow graph?

It separates product economics from pricing model. The same cashflow rules can be priced under BS, local vol, Heston, LSV or basket simulation. It also makes decomposition and term-sheet rendering clearer.

### 11.4 Why split funding and option legs?

A structured note has issuer debt cashflows and option hedge cashflows. Discounting everything on one flat curve hides issuer funding economics. Splitting legs lets bond-like liabilities use funding curve and hedgeable option legs use OIS/risk-neutral discounting convention.

### 11.5 How does pricing engine work?

1. Product declares monitoring times.
2. Engine builds grid.
3. Model simulates paths.
4. Product evaluates cashflows.
5. Discounting is applied.
6. Average discounted cashflows gives price and standard error.

### 11.6 Why AAD if bump Greeks exist?

Bump is simple and useful for validation, but scales poorly. AAD is the desk-scale method for many sensitivities. The project includes AAD to show the adjoint principle and cross-checks.

### 11.7 Headline number in P&L explain?

Residual. It tells whether risk sensitivities explain the actual move. Large residual means investigate.

### 11.8 Why compare LV and LSV?

Same vanilla surface, different dynamics. Exotics care about dynamics. Difference indicates model uncertainty and reserve.

### 11.9 Why XVA exposure seam?

Real banks often separate front-office pricing libraries and CCR/XVA systems. The clean interface is exposure cube plus curves/counterparty data. That avoids merging all product models into the XVA engine.

### 11.10 What is not production-grade?

- Market data controls.
- Calibration robustness.
- Performance.
- Full model validation.
- Live connectivity.
- Complete trade lifecycle.
- Regulatory capital completeness.
- Operational controls.
- Enterprise permissioning/audit.

### 11.11 What build next?

Build a trade casebook, improve calibration/data, full AAD, barrier smoothing, stochastic dividends/rates, correlation smile, lifecycle events and model validation pack.

---

## 12. Bank-Style Technical Question Bank: Concise Answers

### Foundations

1. Arbitrage: zero-cost/riskless profit or positive profit with no downside.
2. First FTAP: no arbitrage iff equivalent martingale measure exists.
3. Second FTAP: market is complete iff martingale measure is unique.
4. Completeness: every contingent claim can be replicated.
5. Risk-neutral drift differs because pricing uses replication/no-arbitrage, not real expected return.
6. Numeraire: asset used as unit of account for pricing.
7. Martingale: conditional expected future value equals current value.
8. Girsanov changes measure by shifting Brownian drift.
9. Volatility is quadratic variation and invariant under equivalent measure changes.
10. Forward with dividends: `F = S exp((r-q)T)`.
11. Put-call parity: `C-P = S exp(-qT)-K exp(-rT)`.
12. BS PDE: derived by delta hedging to remove `dW`.
13. BS formula: discounted expectation of lognormal payoff.
14. Call delta: `exp(-qT)N(d1)`.
15. Vega: `S exp(-qT)n(d1)sqrt(T)`.
16. Call and put gamma same by put-call parity; bond/forward terms have zero gamma.
17. Theta: sensitivity to passage of time.
18. Gamma-theta: long gamma pays theta; short gamma earns theta but loses on realized moves.
19. Digital call: `exp(-rT)N(d2)`.
20. Barrier option: payoff depends on whether underlying crosses barrier.

### Volatility

21. Implied vol: BS vol matching market option price.
22. Smile not flat due to fat tails, skew, jumps, supply/demand.
23. Equity skew negative due to crash protection demand and leverage effect.
24. Term structure: implied vol varies by maturity.
25. Forward vol: implied volatility/variance over future interval.
26. Local vol: deterministic `sigma(S,t)` calibrated to vanilla surface.
27. Stochastic vol: volatility follows random process.
28. Heston has stochastic variance; local vol is deterministic and fits marginals.
29. LSV combines vanilla fit of local vol with dynamics of stochastic vol.
30. Vol-of-vol: volatility of variance/volatility process.
31. Vanna: cross sensitivity to spot and vol.
32. Volga: second derivative with respect to vol.
33. Skew risk: risk that relative vol by strike changes.
34. Smile dynamics: how implied vol surface moves as spot/time changes.
35. Sticky strike fixes vol by strike; sticky delta fixes vol by delta/moneyness.
36. SVI: parametric total-variance smile.
37. SSVI: surface-wide SVI formulation.
38. Butterfly arbitrage: negative implied density/non-convex call prices.
39. Calendar arbitrage: longer maturity too cheap or total variance decreasing.
40. Risk-neutral density: distribution implied by option prices under Q.

### Products

41. Autocallable: conditional coupon note with early redemption and downside barrier risk.
42. Phoenix: autocallable with conditional coupons, often memory.
43. Reverse convertible: bond + coupon - put.
44. BRC: bond + coupon - down-and-in put.
45. CPN: zero-coupon bond + call/call spread.
46. Worst-of basket: payoff depends on worst-performing asset.
47. Memory coupon: missed coupon accrues and pays later if condition met.
48. Knock-in: option/barrier feature activates after barrier breach.
49. Knock-out: option terminates after barrier breach.
50. Call spread note: upside exposure between lower and upper strike.
51. Participation note: pays a fraction/multiple of underlying upside.
52. Range accrual: coupon accrues while underlying stays in range.
53. Cliquet: locks in periodic returns with caps/floors.
54. Variance swap: pays realized variance minus fixed variance strike.
55. Corridor variance: realized variance only counted in price corridor.
56. Dispersion: trade index vol vs component vol/correlation.
57. Equity-linked note: debt instrument with payoff linked to equity.
58. Principal protection: contractual repayment of principal at maturity, subject to issuer credit.
59. Leveraged note: payoff magnifies underlying move.
60. Quanto equity note: equity payoff converted at fixed FX rate, adding FX-equity correlation risk.

### Pricing

61. MC handles path dependence and high dimension.
62. MC convergence: `O(1/sqrt(N))`.
63. Reduce variance with antithetic, control variates, importance sampling, quasi-MC.
64. Antithetic: use `Z` and `-Z`.
65. Control variate: use known-price correlated payoff to reduce error.
66. Importance sampling: sample more from important regions and reweight.
67. Quasi-MC: low-discrepancy deterministic sequences.
68. Early exercise: dynamic programming, tree/PDE, Longstaff-Schwartz MC.
69. Longstaff-Schwartz: regress continuation value on basis functions.
70. Basis: choose state variables driving payoff, e.g. spot, running min, basket worst.
71. PDE method: solve pricing PDE on grid.
72. Finite difference: discretize derivatives in PDE.
73. Crank-Nicolson: stable second-order time-stepping scheme.
74. Tree: discrete recombining/non-recombining process approximation.
75. Calibration: choose model parameters to fit market instruments.
76. Model validation: independent testing of model assumptions, implementation and limits.
77. Validate MC with analytic benchmarks, convergence, SE and independent models.
78. CRN reduces finite-difference noise.
79. FD Greeks noisy because price differences are small relative to MC error.
80. Barriers: use fine grid, Brownian bridge/BGK, analytic/PDE checks.

### Risk

81. Delta hedging: offset first-order spot risk.
82. Discrete hedging error: P&L from rebalancing at discrete times.
83. Gap risk: jump risk not hedgeable continuously.
84. Vega hedging: offset implied vol exposure.
85. Skew hedging: hedge strike-relative vol moves.
86. Correlation hedging: hedge joint-move exposure using dispersion/basket instruments.
87. Dividend risk: risk from dividend assumption changes.
88. Funding risk: risk from funding spread/cost changes.
89. Liquidity risk: risk hedge/exit prices differ from model.
90. Model risk: model assumptions wrong.
91. P&L explain: attribute value change to risk factors.
92. Residual: unexplained P&L after attribution.
93. Stress test: measure losses under extreme coherent scenarios.
94. Coherent scenario: economically consistent joint factor move.
95. VaR: quantile loss over horizon.
96. Expected shortfall: average loss beyond VaR.
97. Wrong-way risk: exposure rises as credit worsens.
98. Concentration risk: too much exposure to one name/factor/client.
99. Basis risk: hedge and exposure do not move identically.
100. Hedge slippage: execution/rebalancing loss vs theoretical hedge.

### XVA and Capital

101. CVA: counterparty default loss adjustment.
102. DVA: own default benefit adjustment.
103. FVA: funding valuation adjustment.
104. KVA: capital valuation adjustment.
105. MVA: margin valuation adjustment.
106. PFE: high-quantile future exposure.
107. EPE: average expected positive exposure.
108. EEPE: effective expected positive exposure for capital/regulatory use.
109. EAD: exposure at default.
110. Netting: legally offset trades before exposure.
111. Collateral: assets posted to reduce exposure.
112. MPoR: closeout period after default.
113. SA-CCR: standardized counterparty credit exposure framework.
114. RAROC: risk-adjusted return over capital.
115. XVA changes coupon because it changes all-in economics.

---

## 13. Commercial, Behavioral and Mock Round Answers

### 13.1 Range-bound markets and elevated skew: what structure?

Autocallable/Phoenix can be attractive for a yield-seeking client because it monetizes implied vol/skew through coupons. But it must be sold with clear downside risk disclosure. For conservative clients, consider capital-protected or lower-risk alternatives.

### 13.2 If expecting sharp crash, should client buy autocallable?

Usually no. Autocallables are short downside tail risk. A bearish client should consider put spreads, collars, bearish participation notes or capital-protected downside structures.

### 13.3 If rates rise, CPN?

Higher rates reduce zero-coupon bond cost, leaving more option budget. Participation improves.

### 13.4 If vol rises, CPN?

Calls become more expensive, so participation falls or cap tightens.

### 13.5 Who should buy autocallable?

Sophisticated client with moderate bullish/range-bound view, ability to bear principal loss, no need for daily liquidity, and understanding of issuer credit risk.

### 13.6 Who should not buy autocallable?

Client needing guaranteed principal, high liquidity, full upside, or unable to tolerate equity drawdown.

### 13.7 Risks disclosed

Market loss, barrier risk, coupon risk, early redemption, issuer credit, liquidity, volatility/skew/correlation, tax and fees.

### 13.8 Explain MTM loss

"Even if final payoff may still be okay, today's exit value reflects lower spot, higher vol/skew, longer expected maturity, funding and liquidity. If you sell early, you receive secondary bid, not maturity payoff."

### 13.9 Why principal at risk despite coupon?

Coupon compensates for taking downside risk. If barrier condition is triggered and underlying falls, principal repayment is reduced.

### 13.10 Issuer credit risk

Investor is exposed to bank's ability to pay. Even capital protection is only as good as issuer solvency.

### 13.11 If client needs liquidity before maturity

Secondary market may be limited. Dealer may bid below theoretical mid due to hedging cost, bid/offer, market stress and liquidity reserves.

### 13.12 Secondary market made

Issuer/dealer calculates unwind value using current market inputs, hedging costs, liquidity, funding, XVA and bid/offer.

### 13.13 Why secondary bid far below theoretical value?

Wide markets, illiquidity, model reserves, hedge unwind cost, stress, issuer funding, and embedded margin.

### 13.14 Suitability vs sophistication

Sophistication means client can understand product. Suitability means product is appropriate for client's objectives, risk tolerance and constraints. A sophisticated client can still be unsuitable.

### 13.15 How bank makes money

Structuring margin, bid/offer, hedging/inventory economics, funding spread, distribution economics. But must cover XVA, capital, reserves, hedging and operational costs.

### 13.16 Why not offer highest coupon?

Because high coupon means high client risk or bad bank economics. Suitability, fair disclosure, hedgeability, XVA, capital and franchise matter.

### 13.17 Why equity structuring?

"I like the mix of markets, quantitative modeling and client problem-solving. Equity structuring turns a market view into a precise payoff, then forces you to think about pricing, hedging, funding, XVA, suitability and risk. My SPDT project was built around that full chain."

### 13.18 Why not trading?

"I am interested in trading risk too, but structuring fits me because I enjoy designing payoff solutions and connecting client objectives to market pricing and desk risk. I want to be close enough to trading to understand hedgeability, but focused on product design."

### 13.19 Why not quant research?

"I enjoy the math, but I do not want to be only model-facing. I like the commercial translation: explaining why a model price becomes a coupon, why a term sheet has certain barriers, and how a client should think about the risk."

### 13.20 Walk me through resume

Use structure:

1. Education/finance interest.
2. Markets and derivatives preparation.
3. SPDT project as main technical proof.
4. Why it leads to equity structuring.
5. Close with what you want to learn on a real desk.

### 13.21 Explain project simply

"I built a simulated equity structured-products desk. It designs notes like autocallables, prices them using market data and volatility surfaces, computes Greeks, explains P&L, runs stress tests, and includes counterparty/XVA costs."

### 13.22 Difficult technical problem

Use vol surface or XVA seam:

"The hard part was making the project more than a pricer. For XVA, I had to decide where the equity pricer should connect to the CCR engine. I chose the exposure cube because that mirrors real bank architecture: front-office models produce mark-to-future exposure, XVA consumes it. That kept product pricing and counterparty risk separate but connected."

### 13.23 Weakness

"Earlier I focused on adding features quickly. I realized for finance models, validation and scope honesty matter more. I changed my approach by adding tests, analytic benchmarks, P&L residual checks and explicit labels for what is real, faithful, stubbed or skipped."

### 13.24 Ethical/suitability

If sales wants unsuitable high coupon:

"I would explain the risk tradeoff and propose safer alternatives. If the product remains unsuitable, I would escalate. A high coupon is not a justification for hiding downside risk."

---

## 14. Stress Round: Best Answers

### 14.1 Vol surface has arbitrage. What breaks?

Negative density, invalid local vol, unstable Greeks, fake barrier prices, model validation failure. Fix calibration, constraints, data and arbitrage checks before pricing exotics.

### 14.2 MC price changes by 50 bps with seed. What do you do?

Increase paths, use variance reduction, check standard error, use common random numbers, control variates, quasi-MC, and ensure payoff discontinuities are handled. Do not quote false precision.

### 14.3 AAD delta disagrees with bump delta. Why?

Possible causes:

- Discontinuous payoff.
- Different random numbers.
- Bump size too large/small.
- Tape missing operation.
- Branching not differentiable.
- Pathwise/AAD differentiating smoothed payoff while bump sees discontinuity.
- MC noise.

Debug against analytic payoff first.

### 14.4 P&L residual huge. What check?

Check trade-level attribution, market data changes, observation/cashflow events, vol surface moves, dividends, rates, correlation, model recalibration, MC noise, booking errors and hedge P&L.

### 14.5 Correlation matrix not PSD. What do you do?

Repair using Higham/eigenvalue clipping/shrinkage, validate changes, explain impact, and avoid using invalid Cholesky.

### 14.6 Client wants impossible coupon. What say?

"That coupon requires taking more risk than your stated constraints allow. We can show what terms would be needed, but I recommend either lower coupon, lower risk structure, different underlying, or capital-protected alternative."

### 14.7 Sales disagrees with suitability concern

Escalate through suitability/compliance/risk governance. Document concerns. Do not approve unsuitable product.

### 14.8 Trader says model too slow

Profile bottlenecks, add analytic shortcuts, vectorize, reduce dimensions, use AAD, C++/GPU kernels, caching, variance reduction and approximations validated against full model.

### 14.9 Model validation rejects local vol extrapolation

Review data, add wing constraints, use alternative parameterization, hold reserves, limit product usage, and document model limitations.

### 14.10 Profitable trade fails RAROC

Do not execute as-is. Increase margin, reduce notional, improve collateral/netting, change counterparty, restructure payoff, or reject.

---

## 15. Dangerous Follow-Ups: Polished Answers

### Did you really build all of this?

"I built a faithful desk-simulation version, not a production bank platform. The product DSL, MC pricing, Greeks logic, P&L explain, reserve framework and XVA exposure seam are implemented. Production-grade data, calibration, infrastructure and independent validation are deliberately out of scope. I documented that distinction because overstating models is dangerous."

### Why should this help you as a structurer?

"Because structuring is not only solving a PDE. It is designing payoff terms from a client objective, solving coupon/barrier to par, checking Greeks and hedgeability, producing scenario tables, including XVA/capital and explaining risks. The project follows that full workflow."

### Biggest model limitation?

"Joint dynamics: forward smile, stochastic dividends/borrow and correlation skew are simplified. These matter for exotics, so I would treat LV/LSV gaps and correlation stress as model-risk reserves rather than exact truth."

### One thing you would not trust in production?

"Wing implied vols from settlement or illiquid quotes without bid/offer and liquidity treatment. Barrier products are sensitive to tails, so bad wing marks can create fake precision."

### One-week improvement?

"Create a polished trade casebook: one autocallable, one BRC, one CPN and one worst-of, each with terms, payoff diagram, fair coupon, Greeks, stress table, P&L explain and XVA impact."

---

## 16. Final Oral Exam Checklist With Answers

If asked "derive BS PDE", reproduce section 2.2.

If asked "derive put-call parity", reproduce section 2.4.

If asked "derive digital price", reproduce section 2.5.

If asked "derive risk-neutral density", reproduce section 2.6.

If asked "derive Dupire idea", reproduce section 2.7.

If asked "derive pathwise delta", reproduce section 2.12.

If asked "derive LR estimator", reproduce section 2.13.

If asked "derive AAD reverse sweep", reproduce section 2.14.

If asked "derive P&L explain", reproduce section 2.15.

If asked "derive CVA", reproduce section 2.16.

If asked "explain your project", use:

"SPDT is a faithful simulation of an equity structured-products desk: snapshot data, vol surface, product DSL, MC pricing, Greeks/AAD, structuring solve, book risk, hedging, P&L attribution, reserves, stress, term sheets, dashboard and XVA integration through exposure cubes."

If asked "why should we hire you for equity structuring", use:

"Because I have prepared for the role in the way the role actually works: client objective to payoff design to pricing to Greeks to hedging to P&L to XVA and suitability. I can discuss both the math and the commercial tradeoffs."

