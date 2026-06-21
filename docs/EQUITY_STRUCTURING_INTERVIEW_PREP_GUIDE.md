# Equity Structuring Interview Prep Guide

Target roles: equity structuring, equity derivatives structuring, exotics structuring, structured products, cross-asset structuring with equity focus.

Target firms: Tier-1 investment banks such as J.P. Morgan, Nomura, Morgan Stanley, Goldman Sachs, Barclays, Citi, BNP Paribas, Societe Generale, UBS, HSBC, Deutsche Bank, Bank of America, and similar regional/global derivatives desks.

Project anchor: Structured Products Digital Twin (SPDT), an equity structured products desk simulator covering market data, vol surface, correlation, payoff DSL, pricing, Greeks, structuring, backtesting, book risk, hedging, P&L explain, model reserves, stress, term sheets, dashboard, and XVA/CCR integration.

Use this as your interview war book. You do not need to memorize every sentence. You do need to be able to derive the core ideas on paper, explain the project honestly, and answer follow-ups without hiding behind code.

---

## 0. The Senior Structurer Mindset

An equity structurer is not just a quant, not just a salesperson, and not just a trader. The role sits between:

- Client objective: yield, protection, leverage, participation, financing, monetization, hedging.
- Market inputs: spot, forwards, rates, dividends, vol surface, skew, correlation, funding, borrow, liquidity.
- Product design: payoff, barriers, coupons, autocalls, memory, caps, floors, participation, worst-of features.
- Trading reality: hedgeability, Greeks, gap risk, liquidity, model risk, P&L explain.
- Bank economics: margin, issuer funding, XVA, capital, balance sheet, counterparty limits.
- Regulation and suitability: who should buy it, what risks must be disclosed, what can go wrong.

In interviews, answer like someone who can sit near a trading desk:

- Start from the economic intuition.
- Then give the mathematical representation.
- Then discuss hedging and risks.
- Then discuss client suitability and bank economics.
- Then name model limitations honestly.

Bad answer style: "I used Monte Carlo because exotics are complex."

Good answer style: "The autocallable has path-dependent early redemption and barrier-linked terminal loss, so closed-form replication is not practical. I simulated risk-neutral paths on the product's observation grid, evaluated cashflows path by path, discounted funding and option legs appropriately, then cross-checked Greeks with bump/pathwise/AAD. I also used common random numbers because otherwise MC noise would dominate finite-difference sensitivities."

---

## 1. Your 90-Second Project Pitch

Use this when asked "Tell me about your project."

"I built a Structured Products Digital Twin: a simulation of an equity structured-products desk. The project starts with market snapshots from Indian market data, calibrates an arbitrage-aware vol surface using SVI/SSVI, builds products like autocallables, Phoenix notes, barrier reverse convertibles, reverse convertibles, capital-protected notes, and worst-of baskets through a payoff DSL, then prices them using Monte Carlo, local vol, Heston/LSV-style models, and analytic checks where possible.

The important part is that it is not just a pricer. It has Greeks, AAD cross-checks, structuring solvers to solve coupon or barrier to par, a virtual trading book, hedging simulation, P&L attribution, model-risk reserves, stress testing, term-sheet generation, and a dashboard. I also integrated it with an XVA/CCR engine through a clean exposure seam: SPDT produces path-by-time NPV exposure cubes, and the XVA stack computes CVA, FVA, KVA, MVA, DVA, PFE, EAD, RAROC, and governance decisions.

The design principle was 'faithful, not fake': I tried to build the same conceptual workflow a real equity exotics desk would use, while being honest about simplifications such as data depth, calibration scale, and production hardening."

Follow-up close:

"The deepest parts technically were the vol surface and arbitrage checks, path-dependent autocallable pricing, Greeks/AAD, P&L explain, and the XVA exposure seam, because those are exactly where desk interviews tend to test first-principles understanding."

---

## 2. Your 5-Minute Project Pitch

Use this if the interviewer is technical and gives you space.

1. Objective

"The aim was to build an end-to-end equity structured products platform, not only price one option. The flagship product is a NIFTY autocallable/Phoenix note, but the product catalog also includes BRCs, reverse convertibles, capital-protected notes, and worst-of baskets."

2. Data and snapshot architecture

"Every layer consumes an immutable MarketSnapshot. This matters because historical replay, P&L attribution, and backtesting require reproducibility. If the pricer pulls live data directly, yesterday's P&L explain becomes impossible to audit."

3. Vol and rates

"The vol layer calibrates total variance surfaces using SVI/SSVI and checks static arbitrage: butterfly arbitrage through non-negative density and calendar arbitrage through non-decreasing total variance. Rates are curves, not flat constants, and the project distinguishes OIS/risk-free discounting from issuer funding because a structured note is also issuer debt."

4. Products

"Products are represented as payoff graphs/cashflow generators. For example, a BRC is a zero-coupon note plus fixed coupons minus a down-and-in put. An autocallable is conditional coupons plus early redemption plus terminal knock-in downside. This decomposition is useful because structuring is really choosing which optionality the investor sells or buys."

5. Pricing

"The pricing engine is model-agnostic. It asks the product for monitoring times, asks the model to simulate paths, evaluates cashflows, and discounts them. That lets the same product be priced under BS, local vol, Heston, LSV-style models, or basket GBM with correlation."

6. Greeks and risk

"Greeks are computed by bump-and-revalue, pathwise, likelihood-ratio for discontinuities, and a small reverse-mode AAD tape to demonstrate the adjoint principle. I used common random numbers for finite differences. The book layer aggregates risk; the P&L layer explains daily moves through delta, gamma, theta, vega, volga, vanna, rho, and residual."

7. Model risk and stress

"LV and LSV can agree on vanilla prices but disagree on exotics because they imply different dynamics and forward smiles. That gap becomes a model reserve. Stress scenarios are coherent: crash, vol-up, skew steepening, correlation-up, funding spread widening, not isolated toy shocks."

8. XVA

"The integration with XVA happens at the exposure cube. SPDT generates mark-to-future NPVs; the XVA engine consumes them for CVA/FVA/KVA/MVA/DVA and governance metrics. This is realistic because pricing libraries and CCR engines often remain separate systems connected by exposure feeds."

9. Honest scope

"I would not claim it is production trading infrastructure. It is a faithful desk twin: real methodology, simplified scale."

---

## 3. Resume Bullet Defense

If your resume says something like:

"Built an equity structured products digital twin for autocallables, Phoenix notes, BRCs and worst-of baskets with SVI/SSVI volatility surface calibration, Monte Carlo pricing, AAD Greeks, P&L attribution, hedging, model reserves and XVA integration."

Expect these immediate questions:

1. What is a structured product?
2. Why would a client buy an autocallable?
3. What optionality is the investor selling?
4. What optionality is the bank short/long after issuing the note?
5. Why is an autocallable typically short volatility?
6. Why is a worst-of autocallable sensitive to correlation?
7. What is SVI? Why not interpolate implied vol directly?
8. What does arbitrage-free vol surface mean?
9. How do you price a path-dependent note?
10. How do you compute Greeks under Monte Carlo?
11. What is AAD and why does a desk care?
12. What is P&L attribution?
13. What does a large residual mean?
14. Why do LV and LSV disagree on exotics?
15. What is CVA? Why should it reduce the coupon?
16. What is RAROC? Why can a trade be fair-value profitable but rejected?
17. What did you build yourself vs what did you simplify?
18. How would you improve it if you had six more months?

Your project will impress only if you can answer these without sounding scripted.

---

## 4. Core Derivations You Must Own

### 4.1 Risk-Neutral Pricing

Question: Why is derivative price a discounted expectation under the risk-neutral measure?

What they test: whether you understand no-arbitrage pricing vs forecasting.

Answer:

- In an arbitrage-free market there exists an equivalent martingale measure Q.
- Under Q, discounted tradable asset prices are martingales.
- If payoff H is replicable, its price is the replication cost:

```text
V_0 = E^Q[ exp(-integral_0^T r_t dt) H ]
```

- Real-world drift mu is irrelevant for pricing a hedgeable derivative. Volatility matters because it determines hedge cost.

Trap:

"We assume investors are risk neutral." That is not the right explanation. We change measure to encode replication prices.

### 4.2 Black-Scholes PDE

Question: Derive the Black-Scholes PDE.

Setup:

```text
dS = mu S dt + sigma S dW
V = V(S,t)
```

Ito:

```text
dV = (V_t + mu S V_S + 0.5 sigma^2 S^2 V_SS) dt + sigma S V_S dW
```

Portfolio:

```text
Pi = V - Delta S
```

Choose:

```text
Delta = V_S
```

Then stochastic term cancels:

```text
dPi = (V_t + 0.5 sigma^2 S^2 V_SS) dt
```

No arbitrage:

```text
dPi = r(V - S V_S) dt
```

Therefore:

```text
V_t + 0.5 sigma^2 S^2 V_SS + r S V_S - r V = 0
```

With continuous dividend yield q:

```text
V_t + 0.5 sigma^2 S^2 V_SS + (r - q) S V_S - r V = 0
```

Key line:

"The real drift mu disappears because the delta hedge removes instantaneous spot risk."

### 4.3 Black-Scholes Formula

Call:

```text
C = S exp(-qT) N(d1) - K exp(-rT) N(d2)
d1 = [ln(S/K) + (r - q + 0.5 sigma^2)T] / (sigma sqrt(T))
d2 = d1 - sigma sqrt(T)
```

Put:

```text
P = K exp(-rT) N(-d2) - S exp(-qT) N(-d1)
```

Important Greeks:

```text
Delta_call = exp(-qT) N(d1)
Gamma = exp(-qT) n(d1) / (S sigma sqrt(T))
Vega = S exp(-qT) n(d1) sqrt(T)
```

Interview trap:

Vega is positive for both calls and puts, and gamma is the same for a call and put with same strike/maturity.

### 4.4 Put-Call Parity

Question: Derive put-call parity.

```text
C - P = S exp(-qT) - K exp(-rT)
```

Reason:

Long call and short put equals a forward. It is model-free no-arbitrage, not a Black-Scholes result.

Follow-up:

If dividends rise, forward falls, calls fall, puts rise.

### 4.5 Digital Option

Cash-or-nothing digital call payoff:

```text
1_{S_T > K}
```

Price:

```text
exp(-rT) N(d2)
```

Why d2, not d1?

Because under the money-market numeraire, the probability of finishing ITM is N(d2). Under the stock numeraire, the share digital relates to N(d1).

Why digitals matter in structuring:

- Barriers and autocall triggers behave like digital discontinuities.
- Digitals have unstable Greeks near strike/barrier.
- Pathwise Greeks fail at discontinuities; likelihood-ratio or smoothing is needed.

### 4.6 Breeden-Litzenberger

Question: How do option prices imply risk-neutral density?

For calls:

```text
partial C / partial K = -exp(-rT) P(S_T > K)
partial^2 C / partial K^2 = exp(-rT) f_Q(K)
```

So:

```text
f_Q(K) = exp(rT) partial^2 C / partial K^2
```

Why it matters:

If the call price is not convex in strike, the implied density is negative somewhere. That is butterfly arbitrage.

### 4.7 Dupire Local Vol

Question: What is local volatility and why does it reprice vanillas?

Model:

```text
dS_t = (r - q) S_t dt + sigma_LV(S_t,t) S_t dW_t
```

Dupire finds sigma_LV(K,T) from the full surface of vanilla prices C(K,T). In total variance form w(k,T), local variance is a function of partial_T w, partial_k w, and partial_kk w.

Key intuition:

- Local vol is calibrated to match all vanilla marginal distributions.
- It does not necessarily match forward smile dynamics.
- Therefore it can price vanillas exactly but still misprice autocallables, cliquets, forward-starts, and barrier-heavy products.

Project link:

Your local vol module computes derivatives on the smooth calibrated surface, not raw quotes. That is essential because raw quote finite differences are noisy and can explode.

### 4.8 SVI and SSVI

Raw SVI slice:

```text
w(k) = a + b [ rho (k - m) + sqrt((k - m)^2 + sigma^2) ]
```

where w is total variance and k is log-moneyness.

Question: Why fit total variance instead of implied vol?

Answer:

- Total variance is natural across maturities.
- Static arbitrage conditions are cleaner.
- SVI gives smooth wings and skew with few parameters.

Question: SVI vs SSVI?

Answer:

- SVI fits one maturity slice at a time.
- SSVI parameterizes the whole surface using ATM total variance and shape functions.
- SSVI can enforce calendar-arbitrage constraints more naturally.

### 4.9 Heston

Model:

```text
dS_t = (r - q) S_t dt + sqrt(v_t) S_t dW_t^S
dv_t = kappa(theta - v_t) dt + xi sqrt(v_t) dW_t^v
dW_t^S dW_t^v = rho dt
```

What parameters mean:

- v0: initial variance.
- theta: long-run variance.
- kappa: mean reversion speed.
- xi: vol-of-vol.
- rho: spot-vol correlation, drives equity skew.

Feller condition:

```text
2 kappa theta >= xi^2
```

If violated, variance can hit zero more often; not fatal in practice but affects simulation scheme.

Question: Why not Euler variance naively?

Answer:

Euler can produce negative variance. Full truncation helps but introduces bias. Andersen QE scheme is commonly used because it better handles variance positivity and distributional behavior.

### 4.10 LSV Leverage Function

LSV model:

```text
dS_t = (r - q)S_t dt + L(S_t,t) sqrt(v_t) S_t dW_t
```

Calibration identity:

```text
L(K,T)^2 = sigma_LV(K,T)^2 / E[v_T | S_T = K]
```

Intuition:

- Local vol ensures vanilla fit.
- Stochastic variance gives realistic forward smile dynamics.
- Leverage function adjusts the stochastic vol model so the marginal vanilla surface is preserved.

Project defense:

"LV and LSV agree on vanilla prices by construction but differ on path-dependent exotics because they imply different conditional dynamics. The difference is a model-risk reserve."

### 4.11 Monte Carlo Pricing

Estimator:

```text
V_0_hat = (1/N) sum_i DF_i payoff_i
standard error = sample_std(discounted payoff) / sqrt(N)
```

Why use antithetic variates?

Use Z and -Z to reduce variance for monotone payoffs.

Why use common random numbers for Greeks?

When computing:

```text
Delta approx [V(S+h) - V(S-h)] / (2h)
```

using independent random numbers makes MC noise dominate the numerator. Common random numbers make the difference smoother.

### 4.12 Pathwise Greek Estimator

For payoff f(S_T):

```text
Delta = exp(-rT) E[ f'(S_T) partial S_T / partial S_0 ]
```

Under GBM:

```text
S_T = S_0 exp(...)
partial S_T / partial S_0 = S_T / S_0
```

So:

```text
Delta = exp(-rT) E[ f'(S_T) S_T / S_0 ]
```

When it fails:

- Digital payoff.
- Barrier discontinuity.
- Autocall trigger.

Reason:

Payoff derivative is not well-defined at the discontinuity. Need likelihood-ratio, smoothing, conditional MC, or bump-and-revalue with care.

### 4.13 Likelihood-Ratio Greek

Idea:

```text
partial_theta E[f(X)] = E[f(X) partial_theta log p_theta(X)]
```

Why useful:

- Does not require differentiating payoff.
- Works for discontinuous payoffs.

Downside:

- Often higher variance.
- Score function can be unstable in tails.

### 4.14 AAD / Reverse-Mode AD

Question: Why does AAD matter on a derivatives desk?

Answer:

If a price depends on many inputs, bumping each input requires O(n) reprices. Reverse-mode AD computes all first-order sensitivities at a small constant multiple of one valuation, largely independent of number of inputs.

Forward mode:

- Cheap for many outputs and few inputs.

Reverse mode:

- Cheap for one output, many inputs.
- Perfect for price -> many Greeks.

Project defense:

"I implemented a small reverse-mode tape to prove I understand the adjoint mechanics: each operation records local derivatives to parents, then a reverse sweep propagates adjoints from output price back to inputs."

### 4.15 P&L Attribution

Taylor explain:

```text
dPV approx Delta dS + 0.5 Gamma dS^2
          + Theta dt
          + Vega dVol + 0.5 Volga dVol^2
          + Vanna dS dVol
          + Rho dr
          + residual
```

Question: What does residual mean?

Answer:

Residual = full revaluation P&L - explained P&L.

Large residual can mean:

- Missing risk factor.
- Large nonlinear move.
- Barrier/autocall discontinuity.
- MC noise.
- Vol surface move not captured by flat vega.
- Model recalibration effect.
- Corporate action/dividend mismatch.

On a real desk, residual is not an afterthought. It is the first number risk managers ask about.

### 4.16 CVA/FVA/KVA/MVA/DVA

CVA:

```text
CVA approx LGD sum_i DF(t_i) EE(t_i) default_probability_i
```

FVA:

```text
FVA approx sum_i DF(t_i) EE(t_i) funding_spread(t_i) dt_i
```

DVA:

Benefit from own default on negative exposure. Enters as a reduction to total charge in bilateral valuation.

KVA:

Cost of capital held over the trade's life.

MVA:

Funding cost of initial margin.

All-in structuring idea:

```text
Fair PV target = par - fee - XVA
```

If counterparty spread widens, CVA rises. The all-in coupon you can offer falls.

---

## 5. Product Questions: Autocallables and Phoenix Notes

### 5.1 Basic Definition

Question: Explain an autocallable to a non-technical client.

Answer:

"You invest notional today. On scheduled observation dates, if the underlying is above an autocall level, the note redeems early and pays a coupon. If it does not autocall, coupons may still be paid if the underlying is above a coupon barrier. At maturity, if the underlying has not breached the downside condition, you get par; if the downside barrier is breached, your principal is exposed to equity loss."

### 5.2 What Optionality Is Embedded?

Investor typically:

- Long issuer credit/bond exposure.
- Receives enhanced coupon.
- Short downside put or knock-in put.
- Short issuer callability/autocall feature.
- Often short volatility and short gap/tail risk.

Issuer/bank:

- Has sold coupons and redemption promises.
- Is often long downside optionality from investor's embedded short put, but has complex net Greeks.
- Needs to hedge delta, vega, skew, correlation, dividends, rates, and funding.

Cleaner answer:

"The investor is selling crash insurance and early redemption optionality in exchange for coupon yield."

### 5.3 Why Is an Autocallable Short Vol?

Typical investor position:

- Receives high coupon.
- Gives up upside beyond autocall.
- Takes downside tail risk.
- Higher implied vol makes the embedded downside options more valuable to the bank, so the bank can offer a higher coupon for the same terms.

Issuer hedging perspective can be path-dependent, but as a broad desk statement autocallable issuance often creates short-vol/short-skew exposure for the investor and corresponding warehousing/hedging needs for dealer books.

### 5.4 What Happens If Spot Goes Up?

Depends on location:

- Far below barriers: value may be low and delta can be high/unstable.
- Near autocall level before observation: probability of early redemption jumps; digital-like behavior.
- Well above autocall: note likely redeems, duration shortens, future coupon optionality disappears.

Interview line:

"Autocallables have state-dependent Greeks. The same product can behave differently near coupon barrier, autocall barrier, and knock-in region."

### 5.5 What Happens If Vol Goes Up?

Investor value usually:

- Down because downside tail risk becomes more valuable.
- But near autocall regions, vol can reduce autocall probability and extend note life, which can have mixed effects depending on coupon structure.

Senior answer:

"The sign of vega can be region-dependent. But structurally, the high coupon is compensation for selling volatility/skew/tail risk, so the investor is usually short vol and short skew."

### 5.6 What Happens If Correlation Goes Up in a Worst-of Autocallable?

Worst-of payoff depends on the worst performer.

Correlation-up effects:

- Higher correlation means names move together.
- For worst-of downside, lower correlation can make it more likely at least one name underperforms badly.
- But for autocall probability, higher correlation can help all names be above autocall together.
- Net correlation sensitivity depends on product region, barriers, maturity, and spot levels.

Desk answer:

"Worst-of correlation risk is not a one-line sign everywhere. The correct answer is scenario-dependent. I would compute correlation delta and stress correlation-up/down, especially around barriers."

Common simplification:

Worst-of puts are often short correlation from the investor side: lower correlation worsens worst-of dispersion risk.

### 5.7 Memory Coupon

Question: Why does memory increase value?

Answer:

If a coupon is missed, it accrues and can be paid later when the coupon condition is met. That increases investor payoff relative to non-memory coupons. The issuer is more short optionality, so fair coupon or barrier must adjust.

### 5.8 Autocall Frequency

Question: Why are autocallables popular in low-rate markets?

Answer:

Clients want yield. By selling downside optionality and callability, they transform equity volatility/skew risk into coupon income.

Question: Why did autocallables become dangerous in crises?

Answer:

Because the product can stop autocalling, duration extends, spot falls toward barriers, vol and skew rise, and hedging becomes difficult exactly when liquidity worsens.

### 5.9 Knock-In Barrier

Question: Down-and-in vs down-and-out?

Down-and-in put becomes active if barrier is breached.

Down-and-out put dies if barrier is breached.

BRC/autocallable downside often resembles short down-and-in put exposure from investor's perspective.

Question: Continuous vs discrete monitoring?

Continuous monitoring has higher probability of barrier breach. Discrete monitoring is less likely to trigger. Broadie-Glasserman-Kou correction adjusts barrier levels to approximate continuous monitoring under discrete simulation.

### 5.10 Autocallable Question Bank

Answer these out loud:

1. Explain an autocallable to a retail investor.
2. Explain an autocallable to a hedge fund volatility PM.
3. Decompose an autocallable into simpler options.
4. What risk is the investor selling?
5. Why does a higher coupon require worse protection or more restrictive terms?
6. Why does the note often have negative vega?
7. Can vega ever be positive locally?
8. What is the gamma profile near autocall date?
9. What is the gamma profile near knock-in barrier?
10. What happens if the underlying rallies strongly after issuance?
11. What happens if it sells off 25% and vol doubles?
12. Why does skew matter?
13. Why do dividends matter for equity autocallables?
14. How do rates affect the coupon?
15. How does issuer funding affect the coupon?
16. What happens if observation frequency increases?
17. What happens if autocall trigger steps down over time?
18. What is a Phoenix autocallable?
19. What is memory coupon?
20. What is snowball coupon?
21. Why can autocallables create dealer hedging pressure near barriers?
22. How would you hedge the delta?
23. How would you hedge vega?
24. How would you hedge skew?
25. How would you hedge correlation in a worst-of?
26. Why is gap risk unhedgeable with delta hedging?
27. Why can an autocallable book have negative convexity?
28. What would you disclose in a term sheet?
29. What is the difference between fair coupon and offered coupon?
30. How would CVA reduce the client coupon?

---

## 6. Product Questions: BRC, Reverse Convertible, CPN, Worst-of

### 6.1 Barrier Reverse Convertible

Decomposition:

```text
BRC = zero-coupon bond + fixed coupons - down-and-in put
```

Investor receives coupon because they sell downside risk.

Questions:

1. Why is coupon fixed/unconditional in a BRC?
2. Why does adding a barrier reduce the coupon vs plain reverse convertible?
3. What happens as barrier moves lower?
4. What happens as strike moves higher?
5. What happens as vol rises?
6. How does discrete barrier monitoring affect fair coupon?
7. Who is long the down-and-in put?
8. Why is the product suitable or unsuitable for a conservative investor?

### 6.2 Reverse Convertible

Decomposition:

```text
RC = zero-coupon bond + fixed coupons - vanilla put
```

No barrier. The investor is short the put from day one.

Question:

Why is RC coupon generally higher than BRC coupon, all else equal?

Answer:

The investor sells a more valuable put because there is no knock-in condition. More option premium funds higher coupon.

### 6.3 Capital-Protected Note

Decomposition:

```text
CPN = zero-coupon bond + participation * call spread
```

Structuring logic:

- Use part of notional to buy a zero-coupon bond that grows to protected amount.
- Use remaining budget to buy equity upside.
- Lower rates make protection more expensive, leaving less option budget.
- Higher vol makes calls more expensive, reducing participation or adding cap.

Questions:

1. Why do high rates improve participation?
2. Why does high vol reduce participation?
3. What is the tradeoff between protection and upside?
4. Why cap the upside?
5. Why might a client prefer CPN to direct equity?
6. What risks remain despite capital protection?

### 6.4 Worst-of Basket

Question:

Why does worst-of give higher coupon?

Answer:

The investor takes exposure to the worst performer among several underlyings. That increases downside/tail risk and therefore option premium, which funds a higher coupon.

Correlation intuition:

- Lower correlation increases dispersion: one name can fall while others do not.
- Worst-of payoff is hurt by dispersion.
- Therefore worst-of products are highly sensitive to correlation and correlation skew.

Question:

How do you simulate a worst-of basket?

Answer:

Generate correlated normal shocks using Cholesky or PSD-repaired correlation matrix, simulate each asset path, compute each asset return relative to initial fixing, take min across assets at observation dates, then evaluate autocall/coupon/knock-in conditions on the worst performer.

Question:

What if correlation matrix is not PSD?

Answer:

Cholesky fails. Need repair, such as eigenvalue clipping or Higham nearest correlation matrix, then re-normalize diagonal to one.

---

## 7. Volatility Surface Interview Questions

### 7.1 Implied Vol

Question: What is implied volatility?

Answer:

The volatility input to Black-Scholes that reproduces the market option price. It is not a forecast; it is a quote representation.

Question: Why invert with Newton and fallback to Brent?

Answer:

Newton is fast because vega gives derivative. It can fail in wings where vega is tiny. Brent is slower but robust because it brackets the root.

### 7.2 Smile and Skew

Question: Why is equity skew usually negative?

Answer:

- Crash risk demand: investors buy downside protection.
- Leverage effect: equity falls increase leverage and volatility.
- Jump/tail risk: downside jumps are priced.
- Dealer inventory/risk premium.

### 7.3 Static Arbitrage

Question: What is butterfly arbitrage?

Answer:

Call prices must be convex in strike. If not, a butterfly portfolio with non-negative payoff can have negative cost. Equivalently implied density becomes negative.

Question: What is calendar arbitrage?

Answer:

Option total variance/prices must be ordered across maturities. A longer maturity option should not be cheaper than a shorter one in an arbitrage-inconsistent way after carry adjustments.

Question: Why is arbitrage-free surface important for exotics?

Answer:

Exotics rely on interpolation/extrapolation and path simulation. Arbitrage in the surface can create nonsensical local vol, negative densities, unstable Greeks, and fake P&L.

### 7.4 Sticky Strike vs Sticky Delta

Question:

What changes when spot moves?

Sticky strike:

- Implied vol at fixed strike remains unchanged.
- Common for marking listed options over small moves.

Sticky delta:

- Implied vol by moneyness/delta remains unchanged.
- Smile moves with spot.

Why it matters:

Delta and vega of structured products depend on smile dynamics assumption. Desk risk often distinguishes Black-Scholes delta, sticky-strike delta, sticky-delta delta, and model delta.

### 7.5 Forward Smile

Question:

Why does local vol misprice forward-starting products?

Answer:

Local vol is calibrated to today's marginal distributions but implies deterministic future smile dynamics. Products sensitive to future smile or conditional distribution can be mispriced.

### 7.6 Vol Surface Question Bank

1. What is implied vol?
2. Why is implied vol not realized vol?
3. Why does skew exist?
4. What is total variance?
5. Why fit in log-moneyness?
6. What is SVI?
7. What are SVI parameters?
8. What is SSVI?
9. How do you check butterfly arbitrage?
10. How do you check calendar arbitrage?
11. What is Breeden-Litzenberger?
12. What is Dupire local vol?
13. Why does Dupire need smooth derivatives?
14. Why can local vol explode?
15. What is sticky strike?
16. What is sticky delta?
17. How does skew affect autocallable coupons?
18. Why do wings matter even if product strikes are near ATM?
19. How do dividends affect equity vol calibration?
20. What is forward variance?
21. What is variance swap fair strike?
22. How would you interpolate/extrapolate a sparse surface?
23. How do you handle illiquid quotes?
24. What are bid/offer vol marks?
25. What is a vol reserve?

---

## 8. Correlation and Basket Questions

Core concepts:

- Correlation matrix must be symmetric PSD with unit diagonal.
- Basket products require joint distribution, not only marginal vol surfaces.
- Gaussian copula has no tail dependence.
- t-copula has tail dependence, often more conservative for joint crashes.
- Worst-of products are sensitive to dispersion and correlation skew.

Questions:

1. What is correlation?
2. What is covariance vs correlation?
3. Why must a correlation matrix be PSD?
4. What happens if Cholesky fails?
5. How do you repair correlation?
6. What is Higham PSD repair?
7. Why is historical correlation not enough?
8. What is implied correlation?
9. How do index options imply average correlation?
10. What is dispersion trading?
11. Why is worst-of sensitive to correlation?
12. Is a worst-of autocallable long or short correlation?
13. Why can the sign change near autocall barriers?
14. What is tail dependence?
15. Why does Gaussian copula underestimate joint crashes?
16. How would correlation stress be designed?
17. Why does correlation go up in equity selloffs?
18. What is correlation skew?
19. How do you hedge correlation?
20. What residual risks remain after hedging single-name deltas?

---

## 9. Pricing and Numerical Methods Questions

### 9.1 Why Monte Carlo?

Use MC when:

- Payoff is path-dependent.
- Multiple underlyings.
- Early redemption/conditional coupons.
- Complex state variables.
- Need exposure profiles over paths.

Limitations:

- Convergence is slow: O(1/sqrt(N)).
- Greeks can be noisy.
- Discontinuities create estimator issues.
- Calibration/model error can dominate MC error.

### 9.2 PDE vs MC

PDE:

- Good for low-dimensional problems.
- Gives smooth Greeks.
- Curse of dimensionality for baskets.

MC:

- Handles high dimension better.
- Natural for exposure simulation.
- Harder for early exercise and Greeks.

### 9.3 Longstaff-Schwartz

Question:

Why use regression for exposure or early exercise?

Answer:

At future time t, exposure should be conditional expected NPV given information at t, not simply realized future payoff. Regression approximates continuation value:

```text
E[V_t | state variables]
```

Basis examples:

- Spot moneyness.
- Squared moneyness.
- Running minimum for barrier status.
- Worst-of level for basket notes.

Trap:

Using realized future payoff directly and then taking positive exposure can introduce Jensen bias.

### 9.4 Barrier Correction

Question:

Why does discrete simulation misprice continuously monitored barriers?

Answer:

If you only check the grid, you miss barrier crossings between time steps. For down barriers, this underestimates knock-in probability and overestimates knock-out survival.

BGK idea:

Adjust barrier by an exponential correction depending on volatility and time step.

### 9.5 Numerical Question Bank

1. Why MC for autocallables?
2. How do you choose time grid?
3. Why include observation dates exactly?
4. What is antithetic sampling?
5. What is control variate?
6. What is quasi-Monte Carlo?
7. Why use common random numbers?
8. How do you estimate standard error?
9. How many paths are enough?
10. What matters more: MC error or model error?
11. How do you price barriers?
12. What is Brownian bridge correction?
13. What is BGK correction?
14. What is Crank-Nicolson?
15. Why can PDE oscillate near discontinuities?
16. What is smoothing/Rannacher time stepping?
17. Why is Euler poor for Heston variance?
18. What is QE scheme?
19. What is calibration error?
20. How do you validate a pricer?
21. How do you benchmark MC?
22. Why does pathwise delta fail for digitals?
23. Why is LR higher variance?
24. What is AAD?
25. How do you test AAD output?

---

## 10. Greeks, Hedging and P&L Questions

### 10.1 Greeks

Delta:

Sensitivity to spot. Hedge with underlying/futures.

Gamma:

Sensitivity of delta. Short gamma loses on realized volatility after delta hedging.

Vega:

Sensitivity to implied vol. Hedge with listed options/variance products/proxy instruments.

Vanna:

Sensitivity of delta to vol or vega to spot. Important in skewed equity products.

Volga:

Sensitivity of vega to vol. Important for large vol moves.

Theta:

Time decay. For short gamma positions, theta often compensates expected hedging loss in normal markets.

### 10.2 Gamma-Theta Tradeoff

Under Black-Scholes PDE:

```text
Theta + (r-q)S Delta + 0.5 sigma^2 S^2 Gamma - rV = 0
```

For delta-hedged option ignoring carry:

```text
Theta approx -0.5 sigma^2 S^2 Gamma
```

Long gamma tends to pay theta. Short gamma earns theta but loses on large realized moves.

### 10.3 Discrete Hedging

Question:

Why can you not perfectly hedge continuously?

Answer:

Trading is discrete, costly, and liquidity-limited. Jumps and gaps cannot be delta-hedged away. Model Greeks are local approximations.

### 10.4 Autocallable Hedging

Risks:

- Delta and gamma near autocall/knock-in levels.
- Vega/skew exposure.
- Forward/dividend risk.
- Correlation for baskets.
- Gap risk across barriers.
- Liquidity risk during selloff.
- Model-risk around path dependence and smile dynamics.

Possible hedges:

- Futures for delta.
- Listed options for vega/skew.
- Variance/vol swaps where available.
- Dispersion/correlation proxies for basket exposure.
- Dynamic rebalancing plus stress limits.

### 10.5 P&L Questions

1. What is P&L attribution?
2. Why compute explain using yesterday's Greeks?
3. What is full revaluation P&L?
4. What is Taylor P&L?
5. What is residual?
6. What creates residual in autocallables?
7. Why use bucketed vega?
8. Why is a flat-vol vega insufficient?
9. What is vanna P&L?
10. What is volga P&L?
11. How does skew move create P&L?
12. How do dividends create P&L?
13. How can model recalibration create P&L?
14. What would risk management ask after a large residual?
15. How would you reduce residual?

---

## 11. Structuring and Client Scenario Questions

### 11.1 Price to Par

Question:

What does "solve to par" mean?

Answer:

Choose a free term such as coupon, barrier, participation, cap, or autocall trigger so that:

```text
PV(note cashflows) = par - issuer fee - XVA/capital/funding charges
```

If the note is worth less than par to the investor, increase coupon or improve terms. If worth more, reduce coupon or worsen terms.

### 11.2 Coupon Direction Questions

All else equal:

- Higher vol -> higher coupon for yield-enhancement notes, because investor sells richer optionality.
- Lower knock-in barrier -> lower coupon, because investor has more protection.
- Higher coupon barrier -> higher coupon, because coupon is harder to receive.
- Higher autocall level -> can increase coupon because autocall is less likely, but effect depends on structure.
- More frequent observations -> often higher chance of autocall/coupon; value impact depends on payoff.
- Higher rates -> affects discounting and zero-coupon budget; product-dependent.
- Higher issuer funding spread -> worsens note economics for issuer/investor.
- Higher counterparty credit spread -> higher CVA, lower all-in coupon.

### 11.3 Client Wants 12% Yield

Question:

A client wants 12% annual yield on NIFTY with 70% protection. How do you structure?

Answer framework:

1. Clarify client view: moderately bullish/range-bound, comfortable with downside tail.
2. Choose product: autocallable/Phoenix or BRC.
3. Set underlyings: liquid index vs single stock vs basket.
4. Choose tenor and observation frequency.
5. Solve coupon/barrier to par using market vol, rates, dividends, funding.
6. Check Greeks and hedgeability.
7. Check scenarios: -10%, -30%, vol-up, delayed autocall.
8. Add bank margin/XVA/capital.
9. Discuss suitability and disclosures.

### 11.4 Client Wants Upside With Capital Protection

Use CPN:

- Buy zero-coupon bond for principal protection.
- Use remaining option budget to buy call/call spread.
- Adjust participation/cap/tenor based on rates and vol.

### 11.5 Client Owns Concentrated Stock and Wants Yield

Possible:

- Covered call / call overwrite.
- Collar.
- Prepaid forward.
- Reverse convertible only if willing to add downside risk, usually not ideal if already concentrated.

Senior answer:

"I would avoid giving a product that increases the same downside concentration unless the client explicitly wants yield enhancement and understands the risk."

### 11.6 Client Has Bearish View

Possible:

- Put spread.
- Bear note.
- Capital-protected bearish participation.
- Put-spread collar.
- Autocallable may not be suitable if client expects sharp selloff.

### 11.7 Structuring Question Bank

1. How do you choose product for a yield-seeking client?
2. How do you choose underlyings?
3. How do you choose barrier?
4. How do you choose tenor?
5. How do you choose observation frequency?
6. How do you decide memory vs non-memory?
7. How do you maximize coupon without hiding risk?
8. How do you improve protection while keeping coupon?
9. What changes if client wants monthly income?
10. What changes if client is bullish?
11. What changes if client is bearish?
12. What changes if client wants capital protection?
13. What changes if rates rise?
14. What changes if vol rises?
15. What changes if skew steepens?
16. What changes if correlation rises?
17. What product benefits from low vol?
18. What product benefits from high vol?
19. What product benefits from high rates?
20. How do you include issuer fee?
21. How do you include XVA?
22. How do you explain worst-case loss?
23. How do you show scenario table?
24. How do you compare to direct equity?
25. How do you compare to a bond?

---

## 12. XVA, CCR and Governance Questions

### 12.1 Exposure Profiles

Definitions:

```text
Exposure(t) = max(NPV(t), 0)
EE(t) = E[max(NPV(t),0)]
ENE(t) = E[max(-NPV(t),0)]
PFE_q(t) = q-quantile of positive exposure at t
EPE = average EE over time
EEPE = effective expected positive exposure, often one-year capped/regulatory style
EAD = alpha * EEPE
```

### 12.2 CVA

Question:

What is CVA?

Answer:

Credit valuation adjustment: expected discounted loss from counterparty default.

```text
CVA = LGD * integral DF(t) EE(t) dPD(t)
```

### 12.3 Wrong-Way Risk

Question:

What is wrong-way risk?

Answer:

Exposure increases when counterparty credit quality worsens. Example: selling equity downside protection to a counterparty whose credit spreads widen when equities fall.

### 12.4 Collateral and MPoR

Collateral reduces current exposure but does not eliminate exposure because:

- Thresholds.
- Minimum transfer amounts.
- Dispute periods.
- Margin period of risk.
- Gap moves between last collateral call and closeout.

### 12.5 RAROC

```text
RAROC = risk-adjusted return / economic capital
```

A trade can have positive fair value but fail approval if it consumes too much capital or breaches exposure limits.

### 12.6 XVA Question Bank

1. What is CVA?
2. What is DVA?
3. What is FVA?
4. What is KVA?
5. What is MVA?
6. Why is XVA not just a pricing add-on?
7. Why does CVA reduce coupon?
8. How do you compute exposure for an autocallable?
9. Why use mark-to-future NPV cube?
10. Why does EE collapse after autocall dates?
11. What is PFE?
12. What is EAD?
13. What is EEPE?
14. What is wrong-way risk?
15. What is netting?
16. Why net before taking positive exposure?
17. What is collateral threshold?
18. What is MTA?
19. What is MPoR?
20. What is initial margin?
21. What is SA-CCR?
22. What is economic capital?
23. What is RAROC?
24. Why can a trade be rejected despite fair pricing?
25. How would counterparty credit spread affect offered terms?

---

## 13. Project-Specific Attack Questions

These are the questions most likely to come directly from SPDT.

### 13.1 Architecture

Question:

Why build a "digital twin" instead of a pricer?

Answer:

Because a real desk workflow includes market data, vol calibration, product definition, pricing, Greeks, structuring, backtesting, booking, hedging, P&L explain, reserves, stress, reporting, dashboard, and XVA. A pricer alone does not show how the trade lives after issuance.

Question:

Why "snapshot in, report out"?

Answer:

Reproducibility. Every price, Greek, P&L explain, and backtest must be tied to a market state. Without immutable snapshots, you cannot audit historical results.

### 13.2 Product DSL

Question:

Why represent products as cashflow generators/payoff graph?

Answer:

It separates product economics from pricing model. The same product can be evaluated under BS, local vol, Heston, LSV, or basket simulation. It also makes decomposition and term-sheet generation easier.

Question:

Why split funding leg and option leg?

Answer:

The note's bond-like issuer liabilities discount on issuer funding curve, while hedgeable option components are closer to OIS/risk-neutral discounting. This is more realistic than a single flat discount rate.

### 13.3 Pricing Engine

Question:

How does your pricing engine work?

Answer:

1. Product provides monitoring times.
2. Engine builds grid including observation dates.
3. Model simulates spot paths on grid.
4. Product evaluates path cashflows.
5. Cashflows are discounted by model curve or leg-aware discounter.
6. Average gives price and standard error.

### 13.4 Greeks

Question:

Why implement AAD if you already have bump Greeks?

Answer:

Bump Greeks are easy to validate but scale poorly. AAD demonstrates desk-scale sensitivity computation. In production, thousands of risk factors make bump-and-revalue expensive; AAD gives all first-order Greeks at small multiple of one valuation.

### 13.5 P&L Attribution

Question:

What is the headline number in your P&L explain?

Answer:

Residual. It tells whether the Greeks and model explain the actual full revaluation. A small residual means risk reports are consistent. A large residual is an investigation.

### 13.6 Model Risk

Question:

Why compare LV and LSV?

Answer:

They can be calibrated to the same vanilla surface, but path-dependent products care about dynamics, not only terminal marginals. The price gap estimates model uncertainty and can be held as reserve.

### 13.7 XVA Seam

Question:

Why integrate XVA at exposure package seam?

Answer:

It mirrors bank architecture. The equity exotics pricer and CCR/XVA engine can stay separate. The common contract is a path-by-time NPV cube plus curves and counterparty metadata.

### 13.8 Honest Scope Questions

Question:

What is not production-grade?

Answer:

Data quality/liquidity depth, calibration scale, market connectivity, robust operational controls, independent model validation, performance, full regulatory capital coverage, broad product coverage, and live trade lifecycle integration.

Question:

What would you improve next?

Answer:

- Better market data and listed option chain cleaning.
- More robust surface calibration with bid/offer and liquidity weighting.
- Production AAD/JAX integration over full MC graph.
- Brownian bridge/barrier smoothing for Greeks.
- More realistic stochastic rates/dividends/borrow.
- Better basket local vol/correlation smile.
- Trade lifecycle events and realized cashflow handling.
- More extensive model validation and benchmarking.

---

## 14. Bank-Style Technical Question Bank

### Foundations

1. What is arbitrage?
2. State the first fundamental theorem of asset pricing.
3. State the second fundamental theorem.
4. What is market completeness?
5. Why does risk-neutral drift differ from real-world drift?
6. What is a numeraire?
7. What is a martingale?
8. What is Girsanov theorem used for?
9. Why is volatility measure-invariant?
10. Derive the forward price with dividends.
11. Derive put-call parity.
12. Derive Black-Scholes PDE.
13. Derive Black-Scholes formula outline.
14. Derive call delta.
15. Derive vega.
16. Why are call and put gamma same?
17. What is theta?
18. Explain gamma-theta relation.
19. Price a digital option.
20. What is a barrier option?

### Volatility

21. What is implied vol?
22. Why is smile not flat?
23. Why is equity skew negative?
24. What is term structure of vol?
25. What is forward vol?
26. What is local vol?
27. What is stochastic vol?
28. Heston vs local vol?
29. Why LSV?
30. What is vol-of-vol?
31. What is vanna?
32. What is volga?
33. What is skew risk?
34. What is smile dynamics?
35. Sticky strike vs sticky delta?
36. What is SVI?
37. What is SSVI?
38. What is butterfly arbitrage?
39. What is calendar arbitrage?
40. What is risk-neutral density?

### Products

41. Explain autocallable.
42. Explain Phoenix note.
43. Explain reverse convertible.
44. Explain BRC.
45. Explain capital-protected note.
46. Explain worst-of basket.
47. Explain memory coupon.
48. Explain knock-in.
49. Explain knock-out.
50. Explain call spread note.
51. Explain participation note.
52. Explain range accrual.
53. Explain cliquet.
54. Explain variance swap.
55. Explain corridor variance.
56. Explain dispersion.
57. Explain equity-linked note.
58. Explain principal protection.
59. Explain leveraged note.
60. Explain quanto equity note.

### Pricing

61. Why MC for exotics?
62. MC convergence rate?
63. How reduce variance?
64. What is antithetic?
65. What is control variate?
66. What is importance sampling?
67. What is quasi-MC?
68. How price early exercise?
69. What is Longstaff-Schwartz?
70. How choose regression basis?
71. What is PDE method?
72. What is finite difference?
73. What is Crank-Nicolson?
74. What is tree method?
75. What is calibration?
76. What is model validation?
77. How validate MC pricer?
78. Why use common random numbers?
79. Why can finite-difference Greeks be noisy?
80. How price barriers accurately?

### Risk

81. What is delta hedging?
82. What is discrete hedging error?
83. What is gap risk?
84. What is vega hedging?
85. What is skew hedging?
86. What is correlation hedging?
87. What is dividend risk?
88. What is funding risk?
89. What is liquidity risk?
90. What is model risk?
91. What is P&L explain?
92. What is residual?
93. Why stress test?
94. What is coherent scenario?
95. What is VaR?
96. What is expected shortfall?
97. What is wrong-way risk?
98. What is concentration risk?
99. What is basis risk?
100. What is hedge slippage?

### XVA and Capital

101. What is CVA?
102. What is DVA?
103. What is FVA?
104. What is KVA?
105. What is MVA?
106. What is PFE?
107. What is EPE?
108. What is EEPE?
109. What is EAD?
110. What is netting?
111. What is collateral?
112. What is MPoR?
113. What is SA-CCR?
114. What is RAROC?
115. Why can XVA change offered coupon?

---

## 15. Commercial and Market Questions

### 15.1 Market Views

Question:

If you expect range-bound equity markets and elevated skew, what structure is attractive?

Possible answer:

Autocallable/Phoenix can monetize skew and vol for yield, but must be suitable because client sells downside tail.

Question:

If you expect a sharp crash, should client buy autocallable?

Answer:

Usually no. They are short downside/tail risk. A put spread, collar, or capital-protected bearish note may be better.

Question:

If rates rise, what happens to capital-protected notes?

Answer:

Zero-coupon bond becomes cheaper, freeing more option budget, improving participation or protection economics.

Question:

If vol rises, what happens to capital-protected note participation?

Answer:

Calls become more expensive, so participation falls or cap becomes lower.

### 15.2 Client Suitability

Questions:

1. Who should buy an autocallable?
2. Who should not buy one?
3. What risks must be disclosed?
4. How do you explain mark-to-market loss?
5. Why is principal at risk despite coupon?
6. What is issuer credit risk?
7. What happens if client needs liquidity before maturity?
8. How is secondary market made?
9. Why can secondary bid be far below theoretical value?
10. What is suitability vs sophistication?

### 15.3 Bank Economics

Question:

How does the bank make money?

Answer:

- Structuring margin/fee embedded in note terms.
- Bid/offer on options/hedges.
- Funding spread economics.
- Potential inventory/risk warehousing within limits.

But:

The bank also bears hedging costs, model reserves, XVA, capital, liquidity, operational and legal costs.

Question:

Why not offer the highest possible coupon?

Answer:

Because the coupon must be fair after hedging cost, margin, XVA, capital, suitability and risk limits. Offering unsustainably high coupon means either hidden risk to client or bad economics for bank.

---

## 16. Behavioral Questions for Equity Structuring

### 16.1 Why Equity Structuring?

Strong answer:

"I like the intersection of markets, quantitative modeling and client problem-solving. Equity structuring is attractive because a product is not just an equation: it reflects a client view, a vol surface, funding, constraints, suitability and hedgeability. My project was designed around that full workflow."

### 16.2 Why This Bank?

Template:

"I am interested in your equity derivatives franchise because it is strong in structured notes/exotics, has real client flow, and sits close to trading. I want a seat where I can learn product design, market pricing, and risk management together."

Customize by bank, desk, region, and interviewer background.

### 16.3 Tell Me About a Difficult Technical Problem

Use:

- Vol surface arbitrage.
- AAD vs bump Greeks.
- P&L residual.
- XVA exposure seam.

Structure:

1. Problem.
2. Why it mattered.
3. What you tried.
4. What failed.
5. Final solution.
6. What you learned.

### 16.4 What Is Your Weakness?

Good version:

"I initially tended to build the pricing layer before fully specifying validation. In this project I corrected that by adding tests, analytic benchmarks, P&L residual checks, and explicit scope labels: real, faithful, stubbed, skipped."

### 16.5 Ethical/Suitability Question

Question:

Sales wants you to structure a very high coupon note for a conservative client. What do you do?

Answer:

You do not hide risk to meet a coupon target. Explain tradeoffs, show worst-case scenarios, propose more suitable alternatives, and escalate if needed. Long-term franchise and suitability matter more than one trade.

---

## 17. Mock Interview Rounds

### Round 1: HR / Motivation

1. Walk me through your resume.
2. Why equity structuring?
3. Why not trading?
4. Why not quant research?
5. Why our bank?
6. Explain your project simply.
7. Tell me about a time you learned something hard.
8. Tell me about a time you handled ambiguity.
9. What markets do you follow?
10. What is one structured product you find interesting?

### Round 2: Structuring Associate

1. Explain an autocallable.
2. What makes coupon go up/down?
3. What is the embedded option?
4. What if spot falls 20%?
5. What if vol rises?
6. What if rates rise?
7. What client would buy this?
8. What client should not buy this?
9. Design a product for bullish client.
10. Design a product for yield client.

### Round 3: Trader / Exotics Quant

1. Derive Black-Scholes PDE.
2. Explain risk-neutral pricing.
3. What is vega?
4. What is vanna?
5. Why use MC?
6. How compute Greeks?
7. Why pathwise fails for digitals?
8. What is local vol?
9. Why LSV?
10. Explain P&L attribution residual.

### Round 4: Senior Structurer

1. Pitch your project in five minutes.
2. What is genuinely realistic in it?
3. What is simplified?
4. How would you price a worst-of autocallable?
5. How would you hedge it?
6. What risks are hardest to hedge?
7. How would XVA change terms?
8. What would model validation challenge?
9. What would you build next?
10. Why should I trust your results?

### Round 5: Stress Round

1. Your vol surface has arbitrage. What breaks?
2. Your MC price changes by 50 bps with seed. What do you do?
3. Your AAD delta disagrees with bump delta. Why?
4. Your P&L residual is huge. What do you check?
5. Your worst-of correlation matrix is not PSD. What do you do?
6. Client wants impossible coupon. What do you say?
7. Sales disagrees with your suitability concern. What do you do?
8. Trader says your model is too slow. What do you do?
9. Model validation rejects your local vol extrapolation. What do you do?
10. The trade is profitable but fails RAROC. What do you do?

---

## 18. Answers to the Most Dangerous Follow-Ups

Question:

Did you really build all of this?

Answer:

"I built a faithful educational/desk-simulation version. Some components are production-shaped and mathematically real, like the payoff DSL, MC pricing, surface checks, Greeks, P&L explain and XVA exposure package. Others are deliberately scoped or simplified. I documented that distinction because overstating a financial model is dangerous."

Question:

Why should this project help you as a structurer, not just a quant?

Answer:

"Because structuring is about translating client objectives into payoff terms and then checking price, risk, hedgeability, capital and suitability. The project forces that full chain: solve coupon/barrier to par, generate term sheet, show scenario behavior, compute Greeks, explain P&L, and include XVA."

Question:

What is your biggest model limitation?

Answer:

"The joint dynamics: equity smile dynamics, stochastic dividends/borrow, and correlation skew are simplified. For vanilla pricing the surface calibration matters most; for exotics the dynamics matter. That is why I included LV vs LSV model reserves and stress tests."

Question:

What is one thing you would not trust in production?

Answer:

"I would not trust raw settlement-price wing IVs without liquidity filtering, bid/offer treatment, and broker/market validation. Wing quotes drive barrier and tail pricing, so garbage in would create false precision."

Question:

If you had one week to improve the project before joining a desk, what would you do?

Answer:

"I would build a clean trade casebook: one autocallable, one BRC, one CPN, one worst-of. For each I would show terms, payoff diagram, decomposition, fair coupon, Greeks, stress table, P&L explain and XVA impact. That would make the project easier to discuss commercially."

---

## 19. Study Plan

### Day 1: Derivatives Foundations

- Risk-neutral pricing.
- Black-Scholes PDE.
- Greeks.
- Put-call parity.
- Digital/barrier basics.

Deliverable:

Derive BS PDE and Greeks on blank paper.

### Day 2: Vol Surface

- Implied vol.
- SVI/SSVI.
- Arbitrage checks.
- Dupire.
- Sticky strike/delta.

Deliverable:

Explain why local vol can match vanillas and miss autocallables.

### Day 3: Products

- Autocallable.
- Phoenix.
- BRC.
- RC.
- CPN.
- Worst-of.

Deliverable:

For each product: client use case, decomposition, risk, hedge.

### Day 4: Pricing/Greeks

- MC pricing.
- Variance reduction.
- Pathwise/LR/bump/AAD.
- Heston/LSV.

Deliverable:

Explain why AAD matters and why pathwise fails for digitals.

### Day 5: Desk Risk

- Hedging.
- P&L explain.
- Residual.
- Model reserves.
- Stress.

Deliverable:

Walk through a bad day for an autocallable book.

### Day 6: XVA/Capital

- Exposure cube.
- CVA/FVA/KVA/MVA/DVA.
- PFE/EAD/RAROC.
- Wrong-way risk.

Deliverable:

Explain why a fair-value trade can be rejected.

### Day 7: Mock Interviews

- 90-second pitch.
- 5-minute pitch.
- 50 technical questions.
- 5 client structuring cases.

Deliverable:

Record yourself answering: "Tell me about your project" and "Design a note for a client seeking yield."

---

## 20. Final Checklist Before Interview

You are ready when you can do all of this without notes:

- Explain the project in 90 seconds and 5 minutes.
- Derive Black-Scholes PDE.
- Derive put-call parity.
- Explain SVI/SSVI and static arbitrage.
- Explain Dupire and local vol limitations.
- Explain Heston and LSV.
- Explain autocallable economics to a client.
- Decompose BRC, RC and CPN.
- Explain worst-of correlation risk.
- Price an autocallable conceptually with MC.
- Explain bump/pathwise/LR/AAD Greeks.
- Explain why CRN matters.
- Explain P&L attribution and residual.
- Explain model reserve.
- Explain CVA/FVA/KVA/MVA/DVA.
- Explain how XVA reduces coupon.
- Answer what is real, faithful, stubbed and out of scope in SPDT.
- Discuss suitability and worst-case risk honestly.

If you can do that, your project is not just a resume line. It becomes a credible signal that you understand how an equity structuring desk thinks.

