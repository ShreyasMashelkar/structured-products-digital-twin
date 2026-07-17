# SPDT — The Complete User Guide

**Structured Products Digital Twin · every tab, every number, and the math behind it**

This guide walks through the whole desk, tab by tab, with a screenshot of each page captured from the live XTS-fed desk. For each tab it answers four questions: *what is this page*, *why does a desk need it*, *what is every element on it showing*, and *what math produces those numbers*. A deeper mathematical appendix sits at the end for the models themselves.

---

## Table of contents

1. [What SPDT is](#1-what-spdt-is)
2. [Reading the screen: masthead & KPI strip](#2-reading-the-screen-masthead--kpi-strip)
3. [How to use](#3-tab--how-to-use)
4. [Overview](#4-tab--overview)
5. [Originate](#5-tab--originate)
6. [Book & Risk](#6-tab--book--risk)
7. [Counterparty & XVA](#7-tab--counterparty--xva)
8. [Validate](#8-tab--validate)
9. [Semi-Static Hedging](#9-tab--semi-static-hedging)
10. [Hedge & Execute](#10-tab--hedge--execute)
11. [Payoff Explorer](#11-tab--payoff-explorer)
12. [Option Chain](#12-tab--option-chain)
13. [Broker](#13-tab--broker)
14. [Outcome Lab](#14-tab--outcome-lab)
15. [Math appendix](#15-math-appendix)
16. [Glossary](#16-glossary)

---

## 1. What SPDT is

SPDT is a digital twin of an equity structured-products trading desk, built on Indian (NSE/NIFTY) market data. It reproduces the full production loop a real desk runs every day:

```
client brief → structure & price a note → book it → mark the book →
explain P&L → hedge the greeks → attribute hedge P&L →
charge XVA / check counterparty limits → validate the model → archive evidence
```

Two engines share one seam:

- **The structuring/pricing engine** (`spdt/`): SSVI vol surfaces calibrated from real option chains, Local-Vol / Heston / LSV Monte-Carlo pricing, AAD greeks, P&L attribution, semi-static barrier replication, hedge recommendation and paper execution.
- **The counterparty-risk engine** (`xva/`): exposure cubes, CVA/FVA/KVA/MVA, SA-CCR regulatory EAD, economic capital, and RAROC gating.

They meet at the **exposure seam**: a booked note's simulated exposure paths flow into the XVA engine, so a note can be priced *all-in* — coupon net of its lifetime counterparty cost — and gated by limits.

### Data modes

The same app runs in two modes, and the masthead always tells you which one you're looking at:

| Mode | Where | Equity data | Chip in masthead |
|---|---|---|---|
| **Live** | your machine (`SPDT_LIVE=1`, `SPDT_SOURCE=xts`) | real NIFTY spot / futures / option chain from the broker (XTS API), FBIL rates | `LIVE` (teal) |
| **Synthetic** | public HF Space, or local without credentials | simulated NIFTY paths and surfaces with realistic dynamics | `SYNTHETIC` / `SIM` |

In live mode the desk re-marks fully every 60 seconds (stale-while-revalidate: you never wait for a rebuild), and a 2-second tick stream animates spot and ATM vol *between* re-marks through the book's own greeks.

---

## 2. Reading the screen: masthead & KPI strip

Every tab shares the same header. Learn to read it once and every page becomes legible.

### Masthead (top-right block)

- **`NIFTY · spot 24,318 ▼7bp · 2026-07-17 · LIVE`** — the underlying, its current spot, the basis-point move since the desk's last full mark, the data date, and the source chip. The `▲/▼bp` badge is driven by the live tick feed.
- **`ATM vol 11.9% · r 5.33% · q 1.30% · funding +120bp`** — the four numbers the whole desk prices off:
  - **ATM vol** — at-the-money implied volatility from the calibrated surface (live: re-ticked every 2s from an ATM-straddle inversion, see §15.9).
  - **r** — the risk-free zero rate bootstrapped from FBIL T-bill/MIBOR-OIS quotes.
  - **q** — the dividend yield *implied from the futures basis*: $q = r - \ln(F/S)/T$. Not an assumption — an observable.
  - **funding** — the issuer's funding spread over OIS. A structured note is unsecured issuer debt, so its bond leg discounts at OIS + spread.
- **`surface arb-free · overnight move +80bp spot / +0.3 vol`** — whether the calibrated surface passed the no-arbitrage checks (Durrleman butterfly + calendar monotonicity), and the market move being explained in today's P&L.
- **`equity: live NSE/XTS (AC Agarwal) · discount: FBIL/MIBOR-style live · funding: model spread assumption`** — the *data boundary line*: for every input, is it real or assumed? This line is the honest-labelling contract of the whole app.
- The **live/sim/paused chip** next to the title toggles the market tick. `live` (teal) = real broker ticks drive the header; `sim` = a mean-reverting random walk animates it; `paused` = frozen.

### KPI strip (six cards, always visible)

| Card | What it is | Math |
|---|---|---|
| **Book NAV** | Total value of the 15-note book (₹ crore) + executed hedge P&L. Sub-line shows note count and the live Δ-estimated drift since the last full mark. | Σ note PVs (each note booked at real face, ₹5cr default) + paper-hedge P&L. Between marks, NAV moves by the Taylor estimate $\Delta\cdot dS + \tfrac12\Gamma dS^2 + \nu\,d\sigma + \text{vanna}\,dS\,d\sigma$. |
| **Overnight P&L** | Yesterday-to-today book P&L. | Full reval difference, decomposed in the Overview waterfall. |
| **Net Δ** | Cash delta: how many ₹ the book gains for a +1% spot move. | $\sum_i \Delta_i \cdot S \cdot 1\%$, re-marked live per tick. |
| **Net Vega** | ₹ per +1 vol point. | $\sum_i \nu_i$, bump-and-revalue with common random numbers. |
| **Model reserve** | Valuation buffer held for model uncertainty. | $\lvert \text{LSV price} - \text{LV price} \rvert$ per note (§15.6) — the two models agree on vanillas but disagree on forward-smile-sensitive exotics; the gap is what we can't distinguish, so we reserve it. |
| **Worst stress** | The most damaging scenario on the book right now. | Min over the coherent stress set (equity crash, vol spike, rate shock, correlation breakdown…). |

Numbers **flash** when a live tick changes them.

---

## 3. Tab — How to use

![How to use](img/tab-how-to-use.png)

### Why it exists
A structured-products desk UI is dense; this tab is the guided tour. It's aimed at a first-time reviewer (a recruiter, a desk quant, your professor) who needs to know *where to click and what to check* without reading code.

### What's on it
- **Hero panel** with two buttons: `Start with Overview →` and `Jump to outcomes` — the two sensible entry points (current state vs. evidence).
- **Recommended review path** — a numbered 01–11 list of the other tabs in the order a reviewer should visit them. Every entry is a button that takes you there.
- **Eleven tour cards**, one per tab. Each card gives: what the tab does, a **"What to check"** bullet list (the load-bearing details a professional would probe), and a **"Good first click"** suggestion. The cards are buttons — click to navigate.
- **Data-boundary note** at the bottom: a reminder that hosted mode is synthetic unless a live feed is configured.

### How to use it
Genuinely: click through the review path in order. It's sequenced so concepts build — you see the book before its risk, its risk before its hedges, and the hedges before the evidence they work.

---

## 4. Tab — Overview

![Overview](img/tab-overview.png)

### Why it exists
This is the desk head's 30-second read: is the book okay, what moved P&L, where is risk concentrated, what would hurt most. Every panel answers one of those questions.

### Panels, top to bottom

**Realized vs implied vol** *(live feed only)* — the desk's carry gauge.
- Tiles: **Realized (session)**, **Realized (30m)**, **Implied ATM**, **IV − RV**, **Γ carry / day**.
- The chart plots trailing-30-minute realized vol (teal) against the live implied ATM (yellow), tick by tick.
- **The math:** realized vol is a quadratic-variation estimator over the tick stream, $rv^2 = \sum_i \left(\ln \tfrac{S_i}{S_{i-1}}\right)^2$, annualized on a **trading clock** (252 days × 6.25 trading hours — not wall-clock, otherwise overnight gaps poison the estimate). Gamma carry per day is
  $$\text{carry} = \tfrac12\,\Gamma S^2\,\frac{\sigma_{\text{impl}}^2 - \sigma_{\text{real}}^2}{252}$$
  — the classic result that a delta-hedged option position earns (pays) the spread between implied and realized variance, scaled by cash gamma.
- **How to read it:** in the screenshot, realized ≈ 7% vs implied ≈ 12%: the desk is *short* options that are pricing more movement than the market is delivering — positive carry (+₹6.99L/day here). If realized rises through implied, the same book bleeds.

**Desk replay · NAV** and **Desk replay · spot & net Δ** — intraday history from the archiver (a snapshot every 15 minutes of the session). Left: NAV including hedge P&L. Right: spot (yellow) vs net delta (teal). Use it to answer "when did the book's delta flip and what did that do to NAV?"

**Overnight P&L explain** — the headline waterfall. Bars: **Delta, Gamma, Theta, Vega, Vanna, Residual, Total**.
- **The math** (§15.6): full second-order Taylor attribution with all sensitivities computed at yesterday's close under *common random numbers*:
  $$\Delta PV \approx \Delta\,\delta S + \tfrac12\Gamma\,\delta S^2 + \Theta\,\delta t + \nu\,\delta\sigma + \tfrac12\text{volga}\,\delta\sigma^2 + \text{vanna}\,\delta S\,\delta\sigma + \rho\,\delta r + \text{residual}$$
- **Why the Residual bar is the most important one:** it's the difference between the greeks' story and the true full-revaluation P&L. Small residual (the caption prints it) ⇒ the greeks you're hedging with actually describe the book. A growing residual is the first symptom of a model that no longer explains its own P&L.

**Top movers** — the six notes with the largest absolute P&L contribution. Click one to jump into Book & Risk with it selected.

**Top gamma concentration · cash Γ /1%** — horizontal bars of $\Gamma S^2 \times 0.01$ per note. Cash gamma is the P&L convexity per 1% move; concentration here tells you which single note dominates your rebalancing needs (and your gap risk).

**Worst stress scenarios** — book P&L under each coherent scenario, sorted worst-first. "Coherent" means a crash also spikes vol and widens spreads — factors move *together*, as they do in real markets.

---

## 5. Tab — Originate

![Originate](img/tab-originate.png)

### Why it exists
This is where a client conversation becomes a booked trade. A salesperson hears "I want 12% income, I can stomach 30% downside, one year" — this tab turns that brief into a *priced, par-solved* structure and stages it into the book.

### The workflow (top strip: `client brief → recommended structure → solve to par → book`)

**1. Client objective** — segmented control: **Income** / **Yield +** / **Protection**, plus an **"Open to a basket (worst-of)"** toggle. The engine maps objective → product family (income ⇒ Phoenix autocallable or BRC; protection ⇒ capital-protected note; basket tolerance unlocks worst-of structures whose dispersion funds higher coupons).

**2. Five sliders** — target annual coupon, protection buffer (displayed as `30% → KI 70%`: a 30% buffer means the knock-in barrier sits at 70% of initial fixing), maturity, observations/year, placement fee.

**3. The recommendation card** — names the structure (here *Phoenix autocallable*, badged `RECOMMENDED`), explains the rationale in one sentence, and shows the **solve-to-par result**: the coupon at which the note's model PV equals 100 minus the fee. In the screenshot: **3.53% p.a.** against the client's 12% ask, with a red banner saying exactly what that means — *at this risk level the market only funds 3.5%; to get 12% the client must sell more downside (higher KI) or move to a basket*. That banner is the desk's honesty mechanism.
- **The math:** the solver walks the PV curve (right chart: model PV vs annual coupon — nearly linear, because a coupon strip's PV is linear in the coupon rate) and finds where it crosses par. Pricing is full Monte-Carlo per point (§15.5).

**4. `Add to book →`** stages the note: it's priced at real face (₹5cr/note), appears italic with a violet dot in the blotter, and immediately contributes to book NAV and greeks.

### Below the fold

**Alternatives ranked by fit** — the other three structures the desk *could* pitch, each with a fit score against the brief (here: BRC 72%, worst-of 55%, CPN 20%). Clicking one overrides the recommendation and re-solves.

**Income/protection catalog · two-curve discounting** — the same product menu priced two ways: `PV (OIS + funding)` vs `PV (OIS only)`. The difference (**Funding impact**, about −1.2 points here) is the dent the issuer's own funding cost puts in the note's value.
- **Why two curves:** a structured note is the issuer's unsecured debt. Discounting its bond-like legs at the risk-free curve would overstate its value; the funding leg belongs on OIS + issuer spread, the option leg on OIS. This split is enforced in the pricer itself, not just in this table.

**Implied-vol surface · SSVI (arb-free)** — the 3-D surface (implied vol × log-moneyness × tenor) that every price above is calibrated on. It's a **Gatheral–Jacquier SSVI** fit (§15.2): total variance
$$w(k,\theta) = \tfrac{\theta}{2}\left[1 + \rho\varphi(\theta)k + \sqrt{(\varphi(\theta)k + \rho)^2 + (1-\rho^2)}\right]$$
with power-law $\varphi(\theta)=\eta\,\theta^{-\gamma}$, and $\eta$ scaled down until the butterfly no-arb bounds hold at every pillar. Calendar arbitrage is impossible by construction (ATM total variance forced non-decreasing). The steep skew on the left (yellow ridge) is the put wing the smile appendix explains.

---

## 6. Tab — Book & Risk

![Book & Risk](img/tab-book-risk.png)

### Why it exists
The trader's main screen: the 15-note blotter with its live risk decomposition. Master-detail — click any note to drill in; click away for book-level aggregates.

### Left: the blotter
Columns: **Trade, Type, Mat, PV, Δ/1%, ν/pt, P&L**. Types are abbreviated (AC = autocallable, BRC = barrier reverse convertible, RC = reverse convertible, CPN = capital-protected note, WO = worst-of). Staged (not-yet-booked) notes render italic with a violet dot. Every row **re-marks on every live tick** through its own greeks — PV and P&L include the current live move.

### Right, with no selection: book aggregates

**Vega ladder by tenor** — net vega bucketed by maturity (1.0y/1.5y/2.0y/3.0y). Chips below filter the blotter by bucket.
- **The math:** bucketed vega comes from a term-vol model — bump *one* forward-vol knot at a time (with common random numbers) and reprice; each bar is $\partial PV/\partial\sigma_{\text{bucket}}$. This is what a real vol trader hedges against, not one flat vega number.

**Gamma concentration** — cash gamma per note (as on Overview but for the whole book).

**Correlation risk · worst-of sub-book** — for the three worst-of baskets: **corr Δ**, the value change per +5 correlation points. The chips print each basket's composition and its pairwise ρ.
- **Why:** a worst-of note is *short dispersion* — the desk sold protection on the worst name, so it gains when names move together and bleeds when they scatter. Correlation is a first-class risk factor here, shocked in stress (`corr_breakdown` aggregates the ρ→0.9 P&L).

**Net-greek chip row** — net Δ, net cash Γ/1%, net ν, net ρ, plus a **hedge-capacity chip** (`hedge <0.1d @ 20% ADV`): how many days of average futures volume it would take to flatten the book's delta at 20% participation. Turns an abstract delta into an executable-or-not statement.

### Right, with a note selected: trade detail
- PV ± Monte-Carlo standard error, term-sheet chips (coupon, KI, autocall, memory, basket ρ…).
- Four greek tiles (Δ/1%, cash Γ/1%, ν/pt, ρ — or corr Δ for baskets).
- **Scenario at maturity** table: terminal index level → knocked-in or safe → payment %.
- **Stress impact · this trade** — the same coherent scenarios applied to just this note.
- **Reserve footnote**: this note's LSV−LV model reserve, bid-offer reserve, and both model PVs.

### Bottom: Barrier radar
A continuously-monitored table of every note's distance to danger, re-fetched every 30s against live spot:

| Column | Meaning | Math |
|---|---|---|
| KI level / KI dist | the knock-in barrier in index points and % below spot | — |
| **σ away** | distance in *volatility units*: $\ln(S/B) / (\sigma\sqrt{\tau})$ | the right unit — 35% away means nothing without knowing vol and time |
| **P(touch KI)** | model-implied probability of touching the barrier before maturity | closed-form GBM first-passage (reflection principle): with $\nu = r - q - \tfrac12\sigma^2$, $m = \ln(B/S)$: $P = N\!\left(\tfrac{m-\nu\tau}{\sigma\sqrt\tau}\right) + e^{2\nu m/\sigma^2} N\!\left(\tfrac{m+\nu\tau}{\sigma\sqrt\tau}\right)$ |
| Next obs / P(autocall) | days to the next observation and the chance the note autocalls there | $P(S_t \ge L) = N\!\left(\tfrac{\ln(S/L)+\nu t}{\sigma\sqrt t}\right)$ |
| Severity | `CRITICAL` ≥50% touch-odds or <5% distance; `WARNING` ≥25% or <10%; else `INFO` | — |

**How to use it:** sort your attention by severity. A note drifting from INFO to WARNING is the desk's early signal to start building the gamma hedge *before* the barrier zone, where gamma explodes.

---

## 7. Tab — Counterparty & XVA

![Counterparty & XVA](img/tab-counterparty-xva.png)

### Why it exists
A note's fair value ignores *who* you're facing. This tab prices the counterparty: what does this client's default risk, funding usage, capital consumption and margin cost do to the note — and can we still offer an attractive coupon after charging for all of it? This is the governance layer that decides **Approved / Rejected / Manual review**.

### The controls
- **Note selector** — any single-asset note in the book (worst-of baskets aren't wired to XVA yet, and the tab says so).
- **Counterparty CDS** (25–800bp) and **Recovery rate** — define the credit curve.
- **XVA funding scenario** — the FVA spread (deliberately separate from the masthead's issuer-funding overlay; the note says so).
- **RAROC hurdle**, **Structuring margin**, **EAD limit**.
- **XVA depth row**: Own CDS → DVA, Cost of capital → KVA, Wrong-way β, and toggles for **Initial margin → MVA** and **Collateralise (CSA/MPoR)**.

### The outputs

**Decision banner** — the governance verdict with its reasons, plus chips for limit status, RAROC vs hurdle, and collateralisation.

**All-in coupon** — the tab's punchline: *base coupon (no XVA)* → *all-in coupon (net of XVA)*, with the drop in bp. This is literally the number sales can offer this counterparty: the par-solve is re-run with the XVA charge folded in.

**Charge breakdown** (six cards):
$$\text{Total XVA} = \underbrace{\text{CVA}}_{\text{their default}} + \underbrace{\text{FVA}}_{\text{funding the uncollateralised exposure}} + \underbrace{\text{KVA}}_{\text{capital held over the life}} + \underbrace{\text{MVA}}_{\text{initial margin funding}} - \underbrace{\text{DVA}}_{\text{our own default (a benefit)}}$$

- **CVA** $= \text{LGD}\sum_i EE(t_i)\,\Delta PD(t_i)\,DF(t_i)$ — expected exposure × marginal default probability × discount, summed over the exposure profile. The credit curve uses a flat hazard $h = s/(1-R)$ so survival $SP(t)=e^{-ht}$.
- **FVA** = funding cost on expected *positive* exposure minus benefit on expected *negative* exposure, weighted by joint survival of both parties.
- **KVA** = cost-of-capital rate × the economic-capital profile over time.
- **MVA** = funding spread applied to the initial-margin profile (when the IM toggle is on).

**Risk & capital row**: **CS01** (ΔCVA per +1bp CDS), **Jump-to-default** (instant-default loss net of CVA already held), **EAD** (α·EEPE, economic), **SA-CCR EAD** (the regulatory alternative: $\text{EAD} = 1.4\,(RC + \text{PFE addon})$), **Economic capital** (Basel ASRF at 99.9%, §15.8), **Regulatory capital** (BA-CVA).

**Expected-exposure profile EE(t)** — the area chart every XVA number integrates over. For an autocallable it *steps down* at each autocall date (paths that redeem stop being exposure) — the caption points this out. Collateralisation crushes the profile to the margin-period-of-risk stub.

**XVA vs counterparty spread** — CVA and total XVA as a function of CDS level, with a marker at the current slider value. The local slope *is* CS01.

**CVA stress ladder** — total charge under ±CDS shocks.

### How to use it
Pick the client's real CDS, set the hurdle to your desk's cost of equity, and read the decision. Then play: at what CDS does this note stop being offerable? Toggle collateralisation and watch CVA collapse — that's the argument for a CSA in one click.

---

## 8. Tab — Validate

![Validate](img/tab-validate.png)

### Why it exists
Every number on the other tabs comes from a model. This tab is where the model is put on trial: do the greeks explain full-reval P&L, how big is model risk, do the products behave sensibly under stress, and would the strategy have survived history?

### Panels

**Taylor vs full reval** (the residual monitor) — set a spot move and a vol move, press `Run full reval`. The engine reprices the *entire book* by Monte-Carlo at the shifted market (same seed as the base mark — common random numbers, so the difference is signal, not noise) and compares against the greeks' prediction:
$$\text{residual} = \underbrace{PV(S{+}\delta S,\sigma{+}\delta\sigma) - PV(S,\sigma)}_{\text{full reval}} - \underbrace{\left(\Delta\,\delta S + \tfrac12\Gamma\,\delta S^2 + \nu\,\delta\sigma\right)}_{\text{Taylor}}$$
Six tiles show each term. The residual tile turns green when it's under 10% of the actual move. **Why you care:** the entire live-ticking header — NAV drift, Δ-est — is a Taylor estimate. This panel measures exactly how much that estimate can be trusted, on demand.

**Model reserves · LSV − LV** (table + bars) — per-note price gap between Local Vol and Local-Stochastic Vol (§15.1). Both calibrate to the same vanilla surface — they *cannot* disagree on vanillas — but they imply different forward smiles, and barrier/autocall products are forward-smile-sensitive. The gap is genuine model uncertainty, so it's held as a reserve rather than recognised as P&L.

**Coherent stress** — the scenario bars, book-level or for the selected note.

**Hedge error vs gap risk** — the most instructive chart on the tab. X = number of rebalances (log scale); two lines:
- **diffusion error (std)** falls like $1/\sqrt{N}$ — textbook: hedge more often, tracking error shrinks.
- **gap-loss tail (5%)** stays *flat* — jumps happen **between** rebalances no matter how often you rebalance. The pre-gap delta can never catch a discontinuity.

That flat line is the mathematical reason barrier books hold reserves and buy semi-static protection (next tab) instead of just delta-hedging harder.

**Backtest row + histogram + 10y path** — the product strategy run over history: autocall rate, mean return, loss rate, mean loss when lost, worst-5% tail; the per-issuance return distribution; the underlying path it was run on.

---

## 9. Tab — Semi-Static Hedging

![Semi-Static Hedging](img/tab-semi-static-hedging.png)

### Why it exists
Delta-hedging a barrier is miserable: gamma explodes near the barrier and gap risk doesn't diminish with rebalancing (the Validate tab just proved it). The professional alternative is **semi-static replication**: build a strip of *listed* vanilla options once, whose payoff matches the barrier component, and only rebuild when tracking error drifts. This tab is that machinery, live.

### Panels

**Barrier Lifecycle Monitor** — the book's barrier positions re-marked on the live spot/vol. Columns: barrier level, distance % (red when <5%), **RN P(hit)** (risk-neutral touch probability), monitoring style, and a lifecycle **status/action** badge (`WATCH`, `ACTION_REQD`, `KNOCKED_IN`, `KNOCKED_OUT`). Click a row to load its strip.

**Barrier Hedge Strip** — the actual replication portfolio for the selected note: each line an instrument (strike/maturity), its weight, delta-equivalent notional, and its Δ/Γ/ν. The footer checks the strip against a *gross-notional policy limit* (≤5× face).

- **The math** (§15.7): project the down-and-in put's payoff onto a basis of listed-strike puts by ridge-regularised least squares over simulated terminal states:
  $$\min_w \lVert Bw - t\rVert^2 + \lambda\lVert w\rVert^2, \qquad B_{jk} = (K_k - S_T^{(j)})^+,\quad t_j = (K - S_T^{(j)})^+\,\mathbb{1}_{\text{hit}}^{(j)}$$
  with $\lambda$ escalated ×10 until the gross-inventory constraint is met. Strikes snap to the listed 50-point NIFTY grid and cluster around the barrier. In/out parity ($\text{down-out} = \text{vanilla} - \text{down-in}$) keeps the decomposition consistent.

**Barrier-Component Tracking** — target PV (green, the true barrier component) vs strip PV (teal dashed) across spot scenarios. The gap between the lines *is* the tracking error; when it exceeds threshold, the monitor calls for a rebuild — that's the "semi" in semi-static.

**Strike-Bucketed Residual Cash Risk** — target vs hedge, bucketed by strike: cash delta (per +1% spot) on the left axis, cash gamma (½Γ·(1%·S)², per 1%²) on the right. The two readouts at the top-right are the *net* residual delta and gamma after the strip — what's left for the futures desk to clean up dynamically.

---

## 10. Tab — Hedge & Execute

![Hedge & Execute](img/tab-hedge-execute.png)

### Why it exists
Risk numbers are theatre until an order crosses a spread. This tab closes the loop against the **real broker feed**: read the book's net greeks → get a lot-rounded hedge recommendation priced off the live quote → paper-execute it → watch the fill fold back into the book's NAV and greeks → attribute the P&L.

### Left column: recommend

- **Feed chip**: `LIVE` with the actual front-future instrument, expiry, and quote age (with a `Refresh quote` button) — or `MANUAL` with a `Try live` retry if the feed is down. When live, bid/ask/lot-size auto-fill from the broker quote (NIFTY lot = 65).
- **Book net Δ / net vega / spot** tiles — what needs hedging.
- **`Δ to hedge (0 = book's own)`** — a demo override: the book is often near delta-flat, so this lets you ask "how would I hedge 500 deltas?" without touching the book.
- **Option leg checkbox** — adds a vega hedge: prefills the nearest-ATM front-expiry call from the live chain; leg greeks are priced off the desk model.
- **`Recommend`** produces a **Recommendation card**: approval state chip, human-readable reason codes (e.g. *within tolerance*, *lot rounding*), the order list (BUY/SELL, qty), Δ before → Δ after, and estimated cost.
  - **The math:** futures qty $= -\text{net}\Delta / (\text{lot}\cdot S)$ rounded to whole lots; with an option leg, vega is neutralised first ($n_{\text{opt}} = -\nu_{\text{book}}/\nu_{\text{opt}}$) and futures clean the residual delta. **Cost estimate** $= \sum_{\text{orders}} |q| \cdot |\text{touch} - \text{mid}| + \text{fees}$ — you pay half the spread plus Indian F&O fees. Stale quotes or breached limits *reject* the recommendation.
- **Auto-hedger** — an approval-gated watcher: when armed, it monitors |Δ| against a threshold on an interval and *proposes* (never executes) a hedge; `Review` loads its proposal. The gate is deliberate — no code path executes without a human click.

### Right column: execute & account

- **Paper blotter** — positions (qty, average price, realized, fees) and the order history with statuses.
- **Hedge P&L attribution** — per instrument: **Realized / Unrealized / Spread / Fees / Net**. Marked at the live mid.
  - **Why this split matters:** it separates *execution cost* (spread + fees — the cost of trading) from *market P&L* (realized + unrealized — the quality of the hedge decision). On a real desk these are owned by different people.
- **Alerts** — greek-limit breaches, stale-data warnings, drawdowns; each with severity and an `Ack` button. Rules re-evaluate on every recommendation.

---

## 11. Tab — Payoff Explorer

![Payoff Explorer](img/tab-payoff-explorer.png)

### Why it exists
Everything else on the desk speaks trader. This tab speaks *investor*: what do I get paid, when do I get my money back, what are my chances of losing capital — in plain English, with the model-implied probabilities made explicit.

### Panels

- **Pick a product** — Autocallable (Phoenix) / Barrier Reverse Convertible / Capital-Protected Note, with sliders for coupon, barrier, maturity (participation instead of coupon/barrier for the CPN).
- **KPI row**:
  - **Fair value** per 100 notional (Monte-Carlo, 20k antithetic paths).
  - **Chance of early redemption** — share of simulated paths that autocall, with the median life.
  - **Chance of losing money** — share of paths whose total payments < notional (turns red above 15%).
  - **Worst 5% return** — the left tail, with the best-5% for symmetry.
- **Payment at maturity vs where the index ends** — the payoff diagram: X = terminal index level (% of start), Y = payment %. For a Phoenix you see par + coupons above the KI, then the cliff onto the 1:1 downside below it. *(The intermediate observations in this sweep are pinned just below the autocall trigger, so the terminal cliff is visible rather than everything autocalling at the first date.)*
- **When does it redeem?** — bar chart of redemption probability per observation date. Front-loaded bars = the note is really a short-dated instrument that occasionally goes long.
- **Coupon schedule** — the contractual coupon table.

### How to use it
This is the tab to screen-share with a non-quant. The two probability KPIs — *chance of early redemption* and *chance of losing money* — are the numbers every retail structured-product brochure hides; here they're computed and printed.

---

## 12. Tab — Option Chain

![Option Chain](img/tab-option-chain.png)

### Why it exists
The chain is the desk's raw calibration input. If a price on another tab looks odd, this is where you check what the market actually said.

### Panels

**Chain table** — per selected expiry (button row on top): Call px / **Call IV** / Strike / **Put IV** / Put px, CE and PE merged per strike, the ATM row highlighted (within 1% of spot). IVs show "—" where inversion isn't possible.

**Implied-vol smile** — one teal line per the selected expiry: **OTM options only** (puts below spot, calls above).
- **Why OTM-only:** ITM options on NSE print stale and often *below intrinsic value* — those prices are uninvertible (no positive vol reproduces them) or produce garbage IVs. The liquid information lives on the OTM side; using both sides of the chain doubles the noise, not the signal. The visible shape — puts steeper than calls — is the classic Indian index skew: crash protection costs more than rally participation.
- **The inversion math** (§15.2): Black-76 on the forward $F = Se^{(r-q)\tau}$; Newton's method on vega in the liquid belly, Brent bracketing on the wings where vega → 0.

---

## 13. Tab — Broker

![Broker](img/tab-broker.png)

### Why it exists
The paper desk and the real broker account must agree — this tab is the reconciliation. It's also the honest boundary of the current setup.

### States

**Not connected** (the current state, shown in the screenshot): the interactive (order-side) XTS API requires the broker to whitelist your IP, which is pending. The panel says exactly what's missing and which env vars (`SPDT_XTS_INTERACTIVE_APP_KEY` / `SECRET`) light it up. *Market data is unaffected — it uses a separate API that is already live.*

**Connected** (once whitelisted): cash/margin KPIs, a **paper vs broker position reconciliation** table (diff column green only at zero), and the broker's order list. The reconciliation is the desk's integrity check: if paper and broker drift, something executed that the model doesn't know about.

---

## 14. Tab — Outcome Lab

![Outcome Lab](img/tab-outcome-lab.png)

### Why it exists
Model values are claims; this tab is the evidence. Three fixed-seed, reproducible studies carry one real note from the blotter (`NOTE-003`) through issuance history, hedge implementation, and counterparty approval. The kicker says it: *evidence, not another feature*.

### Study 01 · Rolling issuance backtest
The booked note's terms (2Y NIFTY Phoenix, quarterly, 61% KI) issued **monthly for 15 years** across a synthetic regime ensemble (5 independent paths — the badge names the source honestly): 785 issuances.
- KPIs: autocall rate (84.5% — most Phoenixes die early), median life (0.25y!), annualised mean return, capital-loss frequency (2.3% of cohorts), and the 5% tail with the worst cohort (−55.2% — the tail is real).
- Charts: per-cohort total returns and the underlying regime path.
- The data-boundary note prints the robustness *ranges* across the ensemble (autocall 71–94%, loss 0–7.6%) — the honest error bars.

### Study 02 · Hedge comparison
The dealer-side question: how should the desk hedge the KI put it just sold? Four strategies — **Unhedged / Delta-only / Semi-static / Hybrid** — run over 16,000 out-of-sample weekly paths with 4bp execution cost and the strip capped at 5× face.
- Table: P&L σ, **ES95** (expected shortfall — the tail metric that decides), risk cut %, turnover, cost, and a PASS/FAIL against policy. The winner gets a `RECOMMENDED` tag (here delta-only, 65.5% risk cut at 0.018/100 cost).
- Policy line: *minimise ES95 + 1% of turnover, subject to 5× gross and 2% cost limits* — selection is a rule, not a vibe.

### Study 03 · Client-to-desk case study
The full loop on one trade, three columns:
- **Investor**: booked coupon 10.44% vs fair pre-XVA 5.98% vs offerable post-XVA 5.89% → target shortfall 6.11pt, with a **restructuring menu** (lower coupon / raise KI / extend tenor).
- **Trading desk**: the selected hedge and its risk cut/cost.
- **CCR/capital**: total XVA, EAD, economic capital, RAROC −0.17% vs hurdle → **MANUAL_REVIEW: restructure or reset client target**.

This is the page that shows the desk saying *no* for quantified reasons — arguably the most production-realistic behaviour in the app.

---

## 15. Math appendix

The full derivations live in the codebase (paths cited); this is the working summary.

### 15.1 The model zoo

| Model | Dynamics | Used for |
|---|---|---|
| **Black-Scholes** | exact lognormal steps, $dS = (r-q)S\,dt + \sigma S\,dW$ | MC benchmark: same inputs as closed form, so any gap is pure sampling error |
| **Term-vol BS** | piecewise-constant forward vol between knots | bucketed vega (the vega ladder) |
| **Local Vol (Dupire)** | $dS = (r-q)S\,dt + \sigma_{LV}(S,t)S\,dW$, log-Euler | smile-consistent pricing; $\sigma_{LV}$ from the SSVI surface via Dupire's formula in log-moneyness form |
| **Heston** | $dv = \kappa(\theta - v)dt + \xi\sqrt v\,dW_2$, $\langle dW_1,dW_2\rangle = \rho dt$ | stochastic-vol dynamics; three implementations that must agree: semi-analytic (characteristic function), Carr–Madan FFT (calibration), **Andersen QE** simulation (quadratic-exponential scheme with martingale correction) |
| **LSV** (production) | Heston variance × leverage $L(S,t)$ | the pricing standard: $L^2(S,t) = \sigma^2_{\text{Dupire}}(S,t)\,/\,\mathbb E[v_t \mid S_t{=}S]$ (Markovian projection), with $\mathbb E[v\|S]$ estimated on the fly by particle binning. Matches LV on vanillas *by construction*, disagrees on forward-smile exotics — that disagreement is the model reserve. |

Monte-Carlo: 100k paths default, antithetic variates, common random numbers across all bumps, optional scrambled Sobol. Correlated baskets via Cholesky on a **Higham-repaired** (PSD) correlation matrix. An optional C++ kernel accelerates the autocallable pricer with a NumPy reference implementation kept as the correctness baseline.

### 15.2 Vol surface

NSE chain → per-contract **Black-76 inversion** (Newton on vega, Brent fallback in the wings; no-arb bounds and liquidity filters: $|\ln(K/F)| \le \text{band}\cdot\sqrt\tau$) → SSVI calibration (formula in §5) → per-slice exact SVI for fast queries. Cross-tenor interpolation is **linear in total variance** at fixed log-moneyness. Every surface ships with an arbitrage report: Durrleman's $g(k)\ge0$ (butterfly) and calendar monotonicity of $w(k,T)$ in $T$. Dupire local vol differentiates the *smooth parameterisation*, never raw quotes.

### 15.3 Greeks — four estimators, cross-checked

1. **Bump + CRN** — central differences, shared seed so MC noise cancels.
2. **Pathwise** — $\partial_\theta \mathbb E[f] = \mathbb E[f'(S_T)\partial_\theta S_T]$; unbiased but fails on digitals/barriers (payoff not Lipschitz).
3. **Likelihood-ratio** — differentiates the density instead; handles the discontinuous payoffs pathwise can't.
4. **AAD** — hand-rolled reverse-mode tape; all first-order greeks of the autocallable from **one backward pass** over the MC graph.

Three-way agreement across estimators is a standing test. Vanna/volga come from cross-bumps in attribution and closed forms in the live re-marker (vanna $= -e^{-q\tau}\phi(d_1)\,d_2/\sigma$).

### 15.4 Rates & dividends

- FBIL T-bill and MIBOR-OIS quotes → discount factors bootstrapped pillar-by-pillar (Brent on the par condition; par OIS: $S\sum_i \tau_i D(t_i) = 1 - D(T)$), log-linear DF interpolation.
- Funding curve = OIS + a 2–3-knot parametric spread (issuer bond marks are too sparse in India to bootstrap directly — this is a deliberate, documented assumption).
- Dividend yield implied from futures: $q = r - \ln(F/S)/T$, bounded to $[-5\%, 10\%]$.

### 15.5 Products (all levels are fractions of initial fixing)

- **Phoenix autocallable**: conditional *memory* coupon if $S \ge$ coupon barrier (missed coupons accrue and pay on the next good observation); early redemption at par if $S \ge$ autocall level; at maturity, par unless the KI was breached, in which case $N\cdot S_T/S_0$.
- **BRC** = ZCB + fixed coupon − **down-and-in put** (discretely monitored). Bond leg discounts on funding, the short put on OIS.
- **CPN** = protected ZCB floor + participation × call spread.
- **Worst-of autocallable**: the inner autocallable runs on $\min_a S_a(t)/K_a$ — short dispersion; correlation shockable.
- Investor-facing probabilities (Payoff Explorer, radar): risk-neutral MC path statistics; closed-form single-date versions via the normal CDF.

### 15.6 P&L attribution & reserves

Second-order Taylor explain (formula in §4) with theta from *aging the product* at constant market, and **residual = full reval − explained** as the model-health metric. Model reserve = |LSV − LV| per note, plus parameter-uncertainty (half the price range over a calibration confidence region) and bid-offer (half the vol-spread price impact), held additively. Notes are booked at **real face** so note NAV and hedge P&L share units.

### 15.7 Hedging

- Dynamic delta hedge: error std $\propto 1/\sqrt{N_{\text{rebalances}}}$; with compound-Poisson jumps overlaid, the 5% tail is flat in $N$ — the chart on Validate.
- Recommendation: lot-rounded futures/options sizing, spread+fee cost, staleness/limit gates (formulas in §10).
- Semi-static: ridge-regularised projection onto the listed put grid (formula in §9), gross-capped, tracking-error-monitored, with in/out parity and survival-weighted autocall digitals.

### 15.8 XVA

Exposure cube (path × time × trade NPVs, netted *before* the positive-part) → $EE(t)$, PFE percentiles. CVA/FVA/KVA/MVA/DVA as in §7. Regulatory: SA-CCR $\text{EAD} = 1.4(RC + \text{addon})$; economic capital via Basel ASRF at 99.9%:
$$EC = EAD \cdot LGD \cdot \left[ N\!\left( \frac{N^{-1}(PD) + \sqrt{R}\,N^{-1}(0.999)}{\sqrt{1-R}} \right) - PD \right]$$
RAROC = (revenue − EL − expenses − XVA) / economic capital, gated against the hurdle.

### 15.9 Live-data layer

- **Tick stream**: 2s poll of index spot + front future + front-expiry ATM straddle over the broker REST API, pushed to the browser over SSE.
- **Live ATM vol**: Black-76 straddle inversion on the CE/PE mids at the ATM strike ($F = Se^{(r-q)\tau}$), averaged over invertible legs; the ATM strike re-picks itself when spot drifts >1%.
- **dvol** (the vol move fed to the Taylor re-mark): live straddle IV minus the straddle IV captured at the last full desk mark — resets ~0 on every re-mark, so the frontend never double-counts a vol move the mark already absorbed.
- **Frontend re-mark**: every tick maps to $\{dS, d\sigma\}$ and updates NAV/greeks via the same Taylor machinery the attribution uses — which is exactly why the Validate tab's residual monitor exists.

---

## 16. Glossary

| Term | Meaning |
|---|---|
| **ATM / OTM / ITM** | at/out-of/in-the-money — strike relative to spot (or forward) |
| **Autocall** | early redemption feature: the note repays at par early if the index is above a trigger on an observation date |
| **Knock-in (KI)** | barrier below which the investor's principal becomes exposed to the index |
| **Memory coupon** | missed conditional coupons accumulate and pay once the condition is next met |
| **Cash gamma** | ₹ P&L convexity per 1% spot move: $\tfrac12\Gamma(0.01\,S)^2$ scaled conventionally as $\Gamma S^2\cdot 1\%$ |
| **Vega / vanna / volga** | sensitivity to vol; of delta to vol; of vega to vol |
| **CRN** | common random numbers — same MC seed across revaluations so differences are signal |
| **SSVI** | Surface SVI — an arbitrage-free parameterisation of the whole vol surface |
| **Dupire local vol** | the unique state-dependent vol function consistent with all vanilla prices |
| **LSV** | local-stochastic vol — Heston dynamics leveraged to match the vanilla surface exactly |
| **ES95** | expected shortfall — the average of the worst 5% of outcomes |
| **EE / EAD / PFE** | expected exposure / exposure at default / potential future exposure |
| **CVA / DVA / FVA / KVA / MVA** | valuation adjustments: counterparty credit / own credit / funding / capital / initial margin |
| **RAROC** | risk-adjusted return on capital — net income over economic capital |
| **Semi-static hedge** | a portfolio of listed vanillas built once and rebuilt only on drift, vs continuous delta-hedging |
| **bp / pt / L / cr** | basis point (0.01%) / percentage point / lakh (10⁵) / crore (10⁷) |

---

*Screenshots captured 2026-07-17 from the live desk (NSE market hours, real XTS feed). Figures in the images are live marks from that session and will differ from what you see today — the structure of every page is what this guide documents.*
