# SPDT — Layer-by-Layer Walkthrough (Plain-English Companion)

> This is the **teaching companion** to `SPDT_Design_and_Build.md`. The design doc is the
> *spec* (what to build, the roadmap, the scope contract). This document is the *explainer*:
> it walks through the whole system from the ground up, in plain English, at full depth —
> what each layer does, the intuition behind the math, how it actually works, and the points
> you must be able to defend.
>
> Read this to *understand* the project. Read the spec to *build* it.

---

## Table of contents

- [How to study this document](#how-to-study-this-document)
- [Part 0 — The mental model](#part-0--the-mental-model)
- [Part 1 — How a single trade flows through the system](#part-1--how-a-single-trade-flows-through-the-system)
- [Part 2 — The foundation: data & the Market Snapshot](#part-2--the-foundation)
- [L1 — Market Data Service](#l1--market-data-service)
- [L2 — Volatility Analytics](#l2--volatility-analytics)
- [Correlation framework](#correlation-framework)
- [L3 — Product Definition DSL](#l3--product-definition-dsl)
- [L4 — Pricing Engine](#l4--pricing-engine)
- [L5 — Greeks Engine](#l5--greeks-engine)
- [L6 — Structurer Workstation](#l6--structurer-workstation)
- [L7 — Historical Backtesting](#l7--historical-backtesting)
- [L8 — Virtual Trading Book](#l8--virtual-trading-book)
- [L9 — Hedging Engine](#l9--hedging-engine)
- [L10 — P&L Attribution](#l10--pl-attribution)
- [L11 — Model Risk Engine](#l11--model-risk-engine)
- [L12 — Stress Testing](#l12--stress-testing)
- [L13 — Documentation Engine](#l13--documentation-engine)
- [L14 — Executive Dashboard](#l14--executive-dashboard)
- [Appendix A — Do you need live data?](#appendix-a--do-you-need-live-data)
- [Appendix B — Glossary](#appendix-b--glossary)

---

# How to study this document

This is broad. Don't read it front-to-back once and call it done — that's how you end up able to
*run* the system but not *derive* it (the exact failure the spec warns about). Use this order.

## The dependency order (what builds on what)

```
   L1 Data ──► L2 Vol Surface ──► L4 Pricing ──► L5 Greeks
      │             │                 ▲   │           │
      │             └── Correlation ──┘   │           │
      │                                   │           ▼
      └────────── L3 Product DSL ─────────┘    L6 Structurer
                                                     │
   Everything above feeds ► L8 Book ► { L9 Hedging, L10 P&L, L11 Model Risk, L12 Stress }
                                                     │
                                            L7 Backtest · L13 Docs · L14 Dashboard
```

You cannot understand L4 (pricing) without L1+L2+L3. You cannot understand L10/L11 without L4+L5.
So study bottom-up.

## A 5-pass reading plan

1. **Pass 1 — orientation (30 min).** Read *Part 0* and *Part 1* only. Get the mental model and watch
   one trade flow end-to-end. Don't worry about the math yet.
2. **Pass 2 — the foundation (deep).** L1 → L2 → Correlation → L3. These are *weeks 1–8* of the build
   and everything rests on them. Make sure you can explain a vol surface and the payoff-as-graph idea
   out loud.
3. **Pass 3 — the engine (deep).** L4 → L5. The Monte Carlo loop and the four Greek methods. This is
   the quant core. Re-read the AAD and pathwise/LR parts until they click.
4. **Pass 4 — the desk (deep).** L6 → L7 → L8 → L9 → L10 → L11 → L12. The simulation around the
   pricer. L10 (P&L attribution) and L11 (model reserve) are the two highest-signal layers — spend
   the most time there.
5. **Pass 5 — defend it.** Ignore the prose; read *only* the "Defend it" boxes (collected in
   `interview_defense.md`). For each, write a one-page derivation **from scratch, out loud.** If you
   can't, go back to that layer. This pass is the real deliverable.

## If you only have limited time

The five things to understand cold, in priority order (these are what get discussed in interviews):
**(1)** arbitrage-free surface (L2), **(2)** the autocallable Monte Carlo price (L4), **(3)** Greeks
cross-checked across AAD/bump/pathwise (L5), **(4)** P&L attribution with its residual (L10),
**(5)** the LSV−LV model reserve (L11).

## A note on notation

`S` = spot (underlying level). `K` = strike. `T` = time to maturity. `σ` (sigma) = volatility.
`r` = risk-free rate. `q` = dividend yield. `ρ` (rho) = correlation. `Z` = a standard-normal random
draw. `PV` = present value (price). `Δ Γ ν Θ` = delta, gamma, vega, theta. Full terms in
[Appendix B](#appendix-b--glossary).

---

# Part 0 — The mental model

## What you're building, in one sentence

A **software simulation of an entire equity structured-products trading desk** — every role,
every step — running on **free Indian market data**. Not a calculator that prices one product,
but the whole machine: how a product gets invented, priced, sold, hedged, risk-managed, and
validated. That's why it's a **"digital twin"** — a faithful working replica of the real thing.

## What is a "structured product"?

A structured product is a custom investment a bank sells to a client, built by gluing together
options. The flagship example — an **autocallable**:

> *"You give me ₹100. Every 6 months we check NIFTY. If it's above its starting level, I pay you
> back your ₹100 plus a fat coupon (say 12%) and we're done early. If NIFTY is down but not
> catastrophically, you keep getting coupons. But if NIFTY crashes below a 'knock-in' barrier
> (say −30%), you eat the full loss."*

The investor is essentially **selling insurance** (taking on crash risk) in exchange for a high
coupon. The bank's job is to figure out the *fair* coupon and then **hedge** the risk it just took
on. Other products: **Phoenix** (autocallable with "memory" coupons), **Barrier Reverse
Convertibles**, **worst-of baskets** (payoff depends on the *worst* of several stocks).

**The key mental model:** a structured note is a **portfolio of options in disguise.** The whole
system is built to expose that — to decompose any note into the optionality it contains.

## Why it's a *desk*, not just a pricer

This is the core insight. Most student projects stop at "I priced an option." This one simulates
the **workflow of the people on a real desk**, and a trade *flows through* those roles:

| Role | What they do | Layer |
|---|---|---|
| **Structurer** | Client says "I want 12% income" → designs a note that delivers it | L6 |
| **Trader** | Prices it, books it, manages the position | L4, L5, L8 |
| **Risk Manager** | Explains daily P&L, runs stress tests | L10, L12 |
| **Model Validation** | Checks the pricing models are trustworthy, holds reserves | L11 |
| **Hedging** | Continuously trades to neutralize risk | L9 |

## The architecture in one diagram

Each layer feeds the one above. Three **foundational services** at the bottom that everyone
consumes; the **desk simulation** in the middle; the **dashboard** on top.

```
                       EXECUTIVE DASHBOARD (L14)
                         ▲   ▲   ▲   ▲   ▲
  Hedging(L9) · P&L Attribution(L10) · Model Risk(L11) · Stress(L12) · Docs(L13)
                               │
                     VIRTUAL TRADING BOOK (L8)
                               │
        Structurer(L6) · Backtesting(L7) · Greeks Engine(L5)
                               │
                       PRICING ENGINE (L4)
                               │
      Product DSL(L3) · Vol Analytics(L2) · Market Data(L1) · Correlation
```

## The single most important design choice: "snapshot in, report out"

Every layer consumes an immutable, versioned **Market Snapshot** — a frozen photo of "the market
as of date D" — and never touches raw data. This one choice is what makes **historical replay,
deterministic backtesting, and reproducible P&L** possible. Keep this phrase in mind through the
whole document: *snapshot in, report out.*

## Two rules that govern everything

- **Faithful, not fake.** Every component is architecturally and methodologically faithful to a
  real desk, even where simplified. You never claim more than you built.
- **The math is the asset, not the code.** The danger isn't writing the code — it's being able to
  *run* the autocallable simulation but not *derive why it works*. Every layer below ends with a
  **"Defend it"** list. Those are the real deliverable.

---

# Part 1 — How a single trade flows through the system

Follow one concrete trade — **a NIFTY autocallable** — from a client phone call to its payout.
NIFTY is at **24,000** today (date D₀).

### Step 1 — Structuring (L6): "design a note that delivers 12%"

The structurer doesn't *pick* the coupon — the market decides what's fair. They fix everything the
client specified and **solve for the one free parameter**. Client gave: 12% coupon, can stomach
30% down. So hold the coupon at 12% and ask: *"What knock-in barrier makes this note worth exactly
₹100?"*

- Frame the product as a DSL composition (L3): `Autocall + Coupon + KnockIn`.
- Call the **Pricing Engine (L4)** repeatedly with different knock-in barriers.
- A 1-D root-finder (Brent) homes in: *"A knock-in at 70% (NIFTY 16,800) makes a 12% coupon fair."*

**Output:** a term sheet — *Autocallable on NIFTY, 12% coupon, autocall at 100%, knock-in at 70%,
3-year maturity, 6-month observations.*

> The deep point: a higher coupon would require a *higher* (riskier) knock-in. The coupon is
> literally the price the investor is paid for selling more crash risk.

### Step 2 — Pricing (L4): "what's it actually worth?"

To price it, simulate thousands of possible futures for NIFTY. It pulls raw material from the
foundation:

1. **Market Data (L1)** hands over the **Snapshot for D₀**: NIFTY = 24,000, vol surface, rates, divs.
2. **Vol Analytics (L2)** provides the calibrated **volatility surface**.
3. The engine runs **Monte Carlo**: ~50,000 random NIFTY paths over 3 years, consistent with the surface.
4. For each path, the **payoff DAG (L3)** is evaluated → that path's cashflows.
5. Average all paths, discount to today → **the price** (the issuer's expected hedging cost).

**Output:** PV ≈ ₹100. Fair. Add margin, sell it.

### Step 3 — Greeks (L5): "what are we now exposed to?"

The moment the desk sells this, it has *taken on risk*. The Greeks Engine quantifies it: **delta**
(spot move), **vega** (vol move — autocallable sellers are **short vol**), **gamma/vanna/volga**
(nastiest near the barrier). Computed by **AAD** (all sensitivities in one pass) and cross-checked
against bump-and-revalue.

### Step 4 — Booking (L8): "put it on the books"

Recorded in the **Virtual Trading Book** as a `Trade` alongside the desk's other ~100 notes. Now it
has a daily life: every trading day it's repriced and its risk recomputed.

### Step 5 — A day in the life (the replay loop)

Each day **D**, the system replays:

```
date D ──► L1 loads Market Snapshot(D)            [NIFTY moved to 23,500]
        ──► L2 recalibrates the vol surface on D
        ──► L8 reprices our trade on Snapshot(D) via L4
        ──► L5 recomputes its Greeks on Snapshot(D)
        ──► L10 explains yesterday→today P&L
        ──► L9 computes today's hedge rebalance
        ──► L11 recomputes the model reserve
        ──► L14 shows it all on the dashboard
```

### Step 6 — Hedging (L9): "neutralize the risk"

NIFTY dropped 500 points overnight; the note lost value, but the trader had **delta-hedged** with
NIFTY futures, so the hedge roughly offset it. The hedge is imperfect: daily (not continuous)
rebalancing leaves **error** (scales with √time), and overnight **gap risk** through the barrier
can't be hedged.

### Step 7 — P&L Attribution (L10): the morning "explain"

The note's value changed by, say, **−₹1.20**. Risk wants to know *exactly why*:

```
ΔValue (−1.20) =  Delta × (NIFTY move)   →  −0.95   (spot fell)
                + ½ Gamma × (move)²       →  −0.08
                + Theta × (1 day)         →  +0.05   (time decay earned)
                + Vega × (vol change)     →  −0.20   (vol rose)
                + Vanna, Volga, ...       →  −0.04
                + UNEXPLAINED RESIDUAL    →  +0.02
```

The **residual** is the headline diagnostic. Tiny residual = Greeks and repricing agree → model is
internally consistent. *A desk that can't explain its P&L can't trade.*

### Step 8 — Model Risk (L11): "do we even trust the price?"

Reprice the same note under **two models** (Local Vol vs LSV). Both match today's option prices
exactly, yet **disagree** on the autocallable. That gap is held as a **model reserve** — profit the
desk refuses to book because it doesn't trust any one model that far.

### Step 9 — Stress & Dashboard (L12, L14)

Periodically, **Stress (L12)** shocks the snapshot (*NIFTY −30%, vol +10, correlations spike — all
at once*) and reprices the book. Everything lands on the **Dashboard (L14)**: NAV, P&L with
attribution, Greeks, reserves, top risks.

### Step 10 — The trade ends

On some observation date either: **NIFTY ≥ 24,000** → autocalls (₹100 + coupons, terminates early);
or **never autocalled + knock-in breached** → investor absorbs the loss. **Backtesting (L7)** would
already have told you the historical distribution of these outcomes.

### The whole journey in one line

```
CLIENT → Structurer solves to par (L6) → Pricer values it (L4, using L1+L2+L3)
       → Greeks measure risk (L5) → booked (L8)
       → [daily: reprice → hedge (L9) → explain P&L (L10) → reserve (L11) → dashboard (L14)]
       → autocalls or pays out → Backtest (L7) contextualizes
```

---

# Part 2 — The foundation

The bottom three services — **Market Data**, **Volatility Analytics**, and the **Product DSL** —
plus the correlation framework, are what everything else stands on. We cover them in depth first.

---

# L1 — Market Data Service

**Does:** ingest, clean, version, snapshot, and replay market data. Produces the immutable Market
Snapshot every other layer consumes. *(Build weeks 1–2 — the foundation slice.)*

## The big picture: a 3-stage pipeline

Raw files come in messy; clean, frozen data goes out. Data only flows downhill.

```
   DOWNLOAD            CLEAN & TRANSFORM           FREEZE
┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Raw landing  │ ──► │  Curated store   │ ──► │ Market Snapshot │
│ (as-is files)│     │ (clean, typed)   │     │ (immutable/D)   │
└──────────────┘     └──────────────────┘     └─────────────────┘
   "ingest"            "curate"                  "snapshot"
```

## Stage 1 — Ingestion (download the raw files)

NSE publishes a **"bhavcopy"** every trading day — a ZIP/CSV archive of that day's official numbers:

- **F&O bhavcopy** — settlement price, open interest, volume for *every* option and future contract. **(Your backbone.)**
- **Cash bhavcopy** — OHLC for every stock and index.

The ingestion code: builds the dated URL for date D → downloads & unzips → saves it **untouched** to
a raw landing area partitioned by date → **append-only and immutable** (re-running gives identical
bytes). You also pull **FBIL/RBI** rate data, **yfinance** as a backup/cross-check, and **NSE
corporate actions** (dividends, splits).

**What bites you here (real engineering):**
- **Trading calendar** — markets close on weekends/Indian holidays; asking for a holiday's bhavcopy
  returns nothing. You need an NSE holiday calendar so you only request valid dates.
- **Format changes** — NSE changed its file format/URL scheme over the years; 2015 files differ
  from 2023 files.
- **Rate limiting** — download politely with retries or you get blocked.

## Stage 2 — Curation (clean it + the clever vol trick)

**2a. Clean the spot series.** Parse CSVs into typed tables. **Back-adjust for corporate actions:** a
1:1 split halves the price overnight, which isn't a real 50% crash — adjust the historical series so
it's continuous, or your volatility/returns calcs see a fake giant move.

**2b. The headline move — invert option prices to implied volatility.** This is the trick that makes
the whole project possible on free data:

- The F&O bhavcopy gives the **settlement price** of every option contract.
- Prices aren't comparable across strikes/expiries, but **implied volatility (IV)** is — it's the
  universal language of options.
- So for each contract, run **Black-Scholes backwards**: given the option's price, spot, strike,
  time-to-expiry, and rate → solve for *"what volatility makes BS produce this price?"*

**Two solving methods, and why:**
- **Newton's method** — fast, uses *vega* (∂price/∂vol) to converge in a few steps. Used for most contracts.
- **Brent's method** — robust fallback. For deep out-of-the-money options on the wings, vega → 0, so
  Newton divides by near-zero and blows up; Brent is slower but safe there.

Do this for every contract, every day → a **historical time-series of implied-vol points**
`(strike, expiry, date) → IV`. This is *"the single most valuable dataset for the whole project."*

**2c. Tag provenance (don't lie about your data).** Every point carries a label: `observed` (real),
`interpolated` (filled from nearby points), or `synthetic` (model-generated where no data existed).
**Never silently mix them** — this lets a later risk report say *"80% observed, 20% interpolated,"*
which is far more credible than hiding gaps.

**2d. Store it efficiently.** Everything lands in **Parquet** (compressed, columnar, free),
partitioned by date and underlying. **DuckDB** runs SQL directly over these files — no database
server, totally free.

```
curated/spot/underlying=RELIANCE/year=2023/*.parquet
curated/iv_points/underlying=NIFTY/date=2023-06-15/*.parquet
```

## Stage 3 — The Market Snapshot (freeze the day)

Assemble everything for date D into **one immutable object** — the central abstraction of the system:

```
MarketSnapshot(date = 2023-06-15)
  spots:        { NIFTY: 18300, RELIANCE: 2450, ... }
  surfaces:     { NIFTY: <calibrated vol surface>, ... }
  correlation:  <PSD-validated matrix>
  ois_curve:    <bootstrapped risk-free curve: drift + risk-free discount>
  funding_curve:<bootstrapped issuer funding curve: OIS + credit spread; discounts ZCB leg>
  dividends:    <schedule>
  provenance:   { each field → observed/interpolated/synthetic }
  content_hash: "a3f9c1..."   ← fingerprint of all inputs
```

Two properties make it special:
1. **Immutable** — once built, never changes. Every layer reads *this*, never raw files.
2. **Content-hashed** — fingerprint of all inputs; rebuild the same date → **byte-identical
   results**. This is "reproducible risk," a genuine bank requirement.

> Note: in week 2 the snapshot holds the cleaned *IV points*. The calibrated *surface* (fitting
> SVI/SSVI) is weeks 3–4 (L2). Week 2's job is just a frozen, reproducible snapshot existing.

> Note on rates: both curves are **bootstrapped** term structures, *not* a single flat rate.
> Bootstrapping = back out discount factors `D(T)` from traded instruments (FBIL OIS, T-bills,
> issuer levels), solved shortest-maturity-first so each step has one unknown, interpolating
> between pillars. We keep **two** because the **OIS curve** sets the risk-neutral drift `(r−q)`
> and discounts the option leg, while the **funding curve** (OIS + issuer credit spread) discounts
> the note's zero-coupon-bond leg — the note is the issuer's debt.

## Stage 4 — Replay

Once snapshots exist per date, historical replay is just an iterator:

```python
for date in business_days(2015, 2025):
    snapshot = load_snapshot(date)
    # hand it to pricing, greeks, hedging, ...
```

## Bank vs you

A bank has a tick database (kdb+), official close marks, golden-source curves, and a whole
market-data org. You have parquet + DuckDB and EOD bhavcopy. The *abstraction* (versioned snapshot,
official close) is identical; the scale and latency are not. Declare that.

## Defend it
- Why invert to IV per contract rather than store prices? → so the vol layer is model-agnostic to
  spot/rate moves; IV is the comparable, stable quantity.
- Newton vs Brent for inversion? → Newton fast via vega; Brent robust where vega→0 on the wings.
- Why are settlement-price IVs biased? → settlement ≠ a traded mid; wide bid-offer on the wings.
- What does survivorship bias do to a backtest? → inflates autocall frequency (you'd be holding
  only names that survived).

---

# L2 — Volatility Analytics

**Does:** turn the messy cloud of IV points into a clean, arbitrage-free, queryable surface, and
expose `vol(K,T)`, local vol, the forward smile, and stickiness regimes. *(Build weeks 3–4 — the
mathematical heart.)*

## Step 0 — What *is* a volatility surface?

From L1 you have a scatter: for each `(strike, expiry)`, an implied vol. Plot them → a bumpy 3-D
surface with two universal features:

- **Smile/skew** (across strikes): out-of-the-money puts trade at higher IV — the market charges
  extra for crash insurance.
- **Term structure** (across expiries): IV differs for 1-month vs 1-year.

The surface's job: answer **`vol(K, T)` for *any* strike and expiry**, including unquoted ones.

## Step 1 — Why you can't just use the raw points

1. **Gaps** — only a few strikes trade liquidly; you need IV where nobody quoted.
2. **Noise** — settlement-derived points jitter, especially on the wings.
3. **Arbitrage** — raw points can imply **free money** (impossible prices). A pricer fed an
   arbitrageable surface produces garbage (negative probabilities, nonsense Greeks).

So you fit a smooth, well-behaved function through the points: **SVI**.

## Step 2 — SVI: fitting one expiry slice

**SVI = Stochastic Volatility Inspired.** A 5-parameter formula for the shape of *one* expiry's
smile, in **total variance** `w = σ²·T` and **log-moneyness** `k = log(K/F)` (0 = ATM):

```
w(k) = a + b·( ρ·(k−m) + √((k−m)² + σ²) )
```

The 5 knobs (intuition matters more than the formula):

| Param | Controls | Plain meaning |
|---|---|---|
| `a` | level | how high the whole smile sits |
| `b` | wing slope | how fast IV rises away from ATM |
| `ρ` | tilt | the skew — left vs right wing asymmetry |
| `m` | shift | where the smile's bottom sits |
| `σ` | curvature | how rounded vs sharp the floor is |

**How you fit it:** per expiry, a least-squares optimizer (SciPy `least_squares`) picks the 5 params
minimizing the gap to observed points. One smooth curve per expiry.

## Step 3 — The two kinds of arbitrage you must kill

**(a) Butterfly arbitrage (within one expiry, "static").** The smile implies a probability
distribution for where the stock lands. If the smile is too curved/wiggly, this implied probability
goes **negative** somewhere — nonsense.
- *Test:* **Durrleman's condition** — a quantity `g(k)` derived from the surface must stay `≥ 0` on
  a grid of strikes.
- *Fix:* constrain SVI params so the smile can't curve into negative-density territory.

**(b) Calendar arbitrage (across expiries, "dynamic").** **Total variance must increase with time** —
a 1-year option must have more total variance than a 6-month one. If independently-fitted slices
cross, you can buy the cheap long-dated and sell the rich short-dated for free money. This is exactly
the failure mode of fitting slices independently → motivating SSVI.

## Step 4 — SSVI: fitting the whole surface at once

**SSVI = Surface SVI.** Instead of N independent smiles, tie them together around the ATM
total-variance term structure `θ(T)` and a shape function `φ(θ)`. The crucial property:

> **SSVI is calendar-arbitrage-free *by construction*.** Under simple parameter conditions, the
> slices *mathematically cannot cross.*

That's the whole reason to prefer SSVI over independent SVI. Workflow: fit SVI per slice (to
understand each smile and as a building block) → fit global SSVI (calendar-arb-free) → run Durrleman
butterfly check → repair any remaining static arbitrage.

## Step 5 — Dupire local volatility (a second, derived surface)

From the clean *implied*-vol surface you compute the **local volatility** surface via **Dupire**:

```
σ²_LV(K,T) =  ( ∂C/∂T + (r−q)K·∂C/∂K + qC )  /  ( ½·K²·∂²C/∂K² )
```

**What it's for:** implied vol is an *average* over an option's life; local vol is the *instantaneous*
vol "at price K, time T" — what the Local Vol pricing model (L4) simulates with.

**The critical trick (key defend-point):** that formula has derivatives. Finite-differencing the
**raw noisy quotes** makes the second derivative `∂²C/∂K²` **explode**. Instead, take the
derivatives **analytically off your smooth SVI/SSVI surface** (in total-variance space). The smooth
parametrization is what makes Dupire stable. *Local vol reprices every vanilla exactly by
construction* — remember this; it's why LV and LSV agree on vanillas.

## Step 6 — Forward smile (foreshadows the model reserve)

The surface also exposes the **forward smile** — the implied smile of a *future* return like
`S(T₂)/S(T₁)`, seen from today. This is the diagnostic exposing Local Vol's famous weakness: **LV
flattens the forward smile** (understates future uncertainty), while stochastic/LSV models keep it
alive. That flattening is the root cause of the LV-vs-LSV disagreement on autocallables — so this
little function *motivates Layer 11*.

## Step 7 — Stickiness regimes

How the surface *moves* when spot moves:
- **Sticky-strike:** IV at a fixed strike stays put as spot moves.
- **Sticky-delta (moneyness):** the smile shifts *with* spot.

This changes your **delta** — the same option has a different hedge ratio per regime. Know *which
regime your delta assumes.*

## Defend it
- SVI vs SSVI → slice vs surface; SSVI removes calendar arb by construction.
- The two arbitrage types → butterfly (negative density, Durrleman) and calendar (variance must rise with T).
- Why Dupire uses the parametrized surface → finite-differencing raw quotes blows up the 2nd derivative.
- Why LV reprices vanillas exactly → Dupire is constructed to, by definition.
- Sticky-strike vs sticky-delta → which regime your delta assumes.

---

# Correlation framework

**Does:** model how multiple underlyings move together — required for worst-of/basket products.
*(Feeds L4 pricing and L12 stress.)*

## The estimators
- **Historical:** sample correlation of log-returns over a window.
- **EWMA:** exponentially-weighted — recent data counts more (markets change regime).
- **Implied correlation:** back out the average pairwise ρ that makes a basket/index vol consistent
  with its constituents' vols, from `σ²_idx = Σ wᵢ²σᵢ² + Σ_{i≠j} wᵢwⱼσᵢσⱼρ`. This is what the index
  dispersion desk actually trades.

## PSD repair (Higham)
A correlation matrix must be **positive semi-definite (PSD)**. Estimated or *shocked* matrices often
aren't. Feed a non-PSD matrix to a Cholesky factorization and you get **imaginary "volatilities" and
negative variance** — the simulation breaks. **Higham's (2002) alternating-projections algorithm**
finds the nearest valid correlation matrix (in Frobenius norm). It's ~30 lines and a great signal.

## Copulas
The dependency structure for multi-asset paths:
- **Gaussian copula:** correlate via Cholesky of ρ. Simple, but **understates joint crashes**.
- **t-copula:** adds **tail dependence** (one extra chi-square mixing variable) — assets crash
  *together* more than Gaussian predicts. Matters a lot for worst-of products, whose payoff is
  driven by the worst performer.

## Defend it
- Why a shocked correlation matrix breaks PSD, and what that does to Cholesky/MC (imaginary vols).
- Gaussian vs t copula tail dependence, and why it matters for worst-of products.

---

# L3 — Product Definition DSL

**Does:** represent *any* structured note as a **composition of primitives**, not a hardcoded payoff
function. This is the layer that makes the project look like a *platform*. *(Build week 5.)*

## The idea: payoff as a graph of building blocks

A payoff is a **directed acyclic graph (DAG)** of typed nodes, evaluated against simulated paths.
The primitives:

`Underlying`, `Basket(weights)`, `WorstOf/BestOf`, `Barrier(level, type, monitoring)`,
`Digital(strike, payout)`, `Coupon(rate, schedule)`, `MemoryCoupon`, `Autocall(barrier, schedule)`,
`KnockIn(barrier)`, `Participation(rate, cap, floor)`, `CapitalProtection(level)`.

Each node implements `evaluate(paths, market) -> cashflows` and (for AAD) is differentiable.

## What the graph actually looks like

An autocallable isn't a formula — it's a tree of these nodes. The evaluator walks a simulated path
*up* the tree, each node transforming cashflows from the nodes below it:

```
                         ┌─────────────────────────┐
                         │   AUTOCALLABLE NOTE      │   ← final cashflows per path
                         │   (combine + discount)   │
                         └───────────▲─────────────┘
                 ┌───────────────────┼────────────────────┐
                 │                   │                     │
        ┌────────┴────────┐ ┌────────┴────────┐  ┌─────────┴─────────┐
        │  Autocall        │ │  Coupon          │  │  Maturity payoff  │
        │  (each obs date: │ │  (paid each obs  │  │  if never called: │
        │   S≥AC → redeem  │ │   if S≥CB)       │  │   KnockIn breached?│
        │   100%+cpns,stop)│ │                  │  │   → 100·S_T/S_0    │
        └────────▲────────┘ └────────▲─────────┘  └─────────▲─────────┘
                 │                   │                      │
                 └───────────────────┼──────────────────────┘
                                     │
                          ┌──────────┴──────────┐
                          │  Underlying (NIFTY)  │   ← the simulated path S(t)
                          └─────────────────────┘
```

Swap, add, or remove a node and you get a *different product* — no new pricing code. Add a
`MemoryCoupon` node in place of `Coupon` → it's now a Phoenix. That composability is the whole point.

## Compositions are the proof

The whole point: "build a Phoenix" becomes "wire MemoryCoupon + Autocall + KnockIn." A reviewer
sees instantly you understand a note is a *portfolio of optionality*, not a magic formula.

```
# Autocallable (single underlying)
Autocallable = Schedule(observations) ∘ {
    on each obs date t_i:
        Autocall(level=AC_i): if S(t_i) ≥ AC_i → redeem 100% + Σ coupons, terminate
    Coupon(rate=c) paid each obs if S(t_i) ≥ coupon_barrier   # Phoenix-style
    at maturity if never autocalled:
        if KnockIn(KI) breached → investor long downside: payoff = 100·S_T/S_0
        else → 100% + final coupon
}

# Phoenix = Autocallable + MemoryCoupon + below-strike coupon barrier
Phoenix = Autocallable.with(
    coupon = MemoryCoupon(rate=c, barrier=CB),  # missed coupons accrue, paid on next breach
    autocall_barrier = AC_schedule,
    knock_in = KI
)

# Barrier Reverse Convertible (BRC) — decomposed into option positions
BRC = ZeroCouponNote(100)
    + FixedCoupon(c)                            # high coupon = sold optionality
    - DownAndIn_Put(strike=100, barrier=KI)     # investor is SHORT a knock-in put
# i.e. the issuer is LONG the KI put; investor's capital is at risk if KI breached
```

## Why this is "senior"

Banks have internal payoff-scripting languages. Yours is a Python DAG — same idea, smaller grammar.
A hardcoded `price_autocallable()` function is a junior signal; a *composable grammar* is a platform.

## A subtlety: barrier monitoring

Barriers can be monitored **continuously** (any moment) or **discretely** (only on observation
dates). Discretely-monitored barriers are easier to simulate but priced differently — and there's a
known correction, **Broadie-Glasserman-Kou**, that adjusts a discretely-monitored barrier toward its
continuous equivalent.

## Defend it
- Decompose a Phoenix into long/short option positions — who is long what.
- Why memory coupons increase value to the investor (and the issuer's short-vol exposure).
- Continuous vs discrete barrier monitoring and the Broadie-Glasserman-Kou continuity correction.

---

# L4 — Pricing Engine

**Does:** price any DSL product under any model via closed-form, PDE, or Monte Carlo. *(Build weeks
6–8 for MC + flagship; weeks 13–14 for Heston/LSV.)*

## The principle: price = discounted average payoff over possible futures

A deep result: today's fair price = the **average payoff across all possible futures, discounted to
today** — but averaged in a special **risk-neutral** world where every asset drifts at the risk-free
rate (not its real expected return). Monte Carlo computes that average by brute force.

```
Price = e^(−r·T) × average over simulated paths of [ payoff on that path ]
```

## Monte Carlo, step by step

**Step A — how the stock moves over one tiny step Δt:**

```
S_next = S_now × exp( (r − q − ½σ²)·Δt  +  σ·√Δt · Z )
                        └──── drift ────┘   └─ random shock ─┘
```
`r−q` = risk-neutral drift; `σ` = vol (from L2); **`Z` = a standard-normal random draw** — the
randomness.

**Step B — generate one path:** split the life into steps (e.g. 156 weekly steps over 3 years), draw
156 `Z`s, apply the formula repeatedly → one jagged 3-year journey for NIFTY.

**Step C — evaluate the payoff on that path (this is L3):** walk the path through the product rules
(autocall? coupons paid? knock-in breached?) → that path's cashflow.

**Step D — repeat ~50,000 times and average, discounted → the price.**

```
Path 1:  ₹112 (autocalled)
Path 2:  ₹65  (knocked in, big loss)
Path 3:  ₹106 (autocalled month 6)
...
Average, discounted ≈ ₹100  ← the price
```

## Why the *quality* of the randomness matters

Naive MC error shrinks only as `1/√N` (4× paths → 2× accuracy). Picture the estimated price settling
toward the true value as you add paths — and the variance-reduction tricks getting you there sooner:

```
 price
   │ ╲                        ← few paths: noisy, wide error band
   │  ╲    ╱╲
   │   ╲__╱  ╲___              naive MC (1/√N): slowly tightens
   │   ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  ← true price
   │     ╲___                  with Sobol + antithetic + control variate:
   │         ╲________         tightens far faster, same path budget
   └──────────────────────────► number of paths N
```

The variance-reduction tricks get accuracy with fewer paths:

| Trick | What it does |
|---|---|
| **Sobol (low-discrepancy)** | "Smarter random" that fills space evenly → faster convergence |
| **Antithetic variates** | For each path using `Z`, also run `−Z` → cancels noise |
| **Control variates** | Price a vanilla you can solve exactly alongside; use its known error to correct |
| **Brownian bridge** | Build the path so the most important time points get the best Sobol coordinates |
| **Common Random Numbers (CRN)** | Reuse the *same* paths across bumps so Greeks are stable |

For a **worst-of** on 3 stocks you draw 3 `Z`s per step and use a **Cholesky factorization** of the
(PSD-repaired) correlation matrix to make them move together realistically.

## The four models (increasing realism)

- **Black-Scholes (BS):** constant volatility. Analytic formulas exist for vanillas/digitals/single
  barriers — implement them as **MC benchmarks** (your MC must converge to them).
- **Local Vol (LV):** volatility is a fixed function `σ(S,t)` (the Dupire surface from L2). Reprices
  all vanillas exactly. Priced by PDE (1-D Crank-Nicolson) for low dimensions, or MC for
  path-dependents. **Weakness:** flattens the forward smile.
- **Heston (stochastic vol):** volatility has its *own* random process:
  `dS = (r−q)S dt + √v S dW₁`, `dv = κ(θ−v)dt + ξ√v dW₂`, with correlated `dW₁,dW₂`. Simulate with
  the **Andersen QE (quadratic-exponential) scheme** — plain Euler on the variance can go *negative*
  and is biased; QE is the standard fix. Vanillas price via the **characteristic function +
  Carr-Madan FFT**, which you use to *calibrate* Heston to the surface.
- **LSV (Local-Stochastic Vol — the production standard):** `dS = (r−q)S dt + L(S,t)√v S dW₁` with
  stochastic variance `v` *and* a **leverage function** `L(S,t)` tuned so the model reprices the
  *entire* vanilla surface while keeping realistic random dynamics. The calibration identity
  (Markovian projection / particle method):

  ```
  L²(S,t) = σ²_Dupire(S,t) / E[ v_t | S_t = S ]
  ```

  i.e. take the local-vol number and divide by the average stochastic variance whenever you're at
  level S. Estimating that conditional expectation `E[v_t | S_t=S]` (by binning MC paths) is the
  **hardest, highest-risk piece of the whole build** (week 14 — budget slack).

## Complexity

MC is `O(paths × steps × assets)`. LSV adds an outer calibration loop estimating conditional
expectations per step → the expensive bit. PDE is `O(space × time)` and only viable in 1–2 dims
(curse of dimensionality → MC for baskets/autocallables).

## Defend it
- Why Euler-on-variance is wrong and what QE fixes.
- Why LV alone misprices forward-smile products and SV alone misfits the spot smile → hence LSV.
- The LSV leverage-function calibration identity and what the conditional expectation means.
- Why CRN is mandatory for finite-difference Greeks.

---

# L5 — Greeks Engine

**Does:** compute first/second-order and cross sensitivities for one trade and for thousands. A
centrepiece — you implement **all four** methods. *(Build weeks 9–10.)*

## What the Greeks are

The risk numbers — how the price moves as inputs move:
- **Delta** (∂Price/∂S) — spot sensitivity (your hedge ratio).
- **Gamma** (∂²/∂S²) — how delta itself moves; convexity.
- **Vega** (∂/∂σ) — vol sensitivity. Autocallable issuers are **short vega**.
- **Vanna** (∂²/∂S∂σ), **Volga/Vomma** (∂²/∂σ²) — cross/second vol Greeks; drive the *cost of vega
  hedging* and feed P&L attribution.
- **Charm** (∂²/∂S∂t), **Speed** (∂³/∂S³), **correlation delta**, **dividend delta**, **rho**.

These are reported as **ladders** — vega by maturity bucket, correlation ladders, risk bucketed by
underlying/maturity/strike region.

## The four methods

**1. Bump-and-revalue.** Reprice, nudge an input by ε, reprice again, take the difference. Use
**central differences** and **CRN** (same paths both times). Cheapest to implement; `O(2·n_inputs)`
repricings; noisy for second-order Greeks.

**2. Pathwise derivative.** Differentiate the *payoff along each path*:
`∂Price/∂θ = E[ ∂Payoff/∂S · ∂S/∂θ ]`. **Unbiased and low-variance — but only for smooth (Lipschitz)
payoffs.** It **fails for discontinuous payoffs** (digitals, barriers): the payoff has a *jump*, so
its derivative at the kink is undefined (a spike/Dirac).

**3. Likelihood-ratio (LR) / Malliavin.** Differentiate the *probability density* instead of the
payoff: `∂Price/∂θ = E[ Payoff · ∂log p/∂θ ]`. Works precisely *where pathwise fails* (digitals,
barriers) because it never differentiates the discontinuous payoff — but it's **higher variance**.
Knowing the pathwise/LR split (when to use which, and why) is exactly the nuance that separates
serious candidates.

**4. AAD (Adjoint Algorithmic Differentiation).** Reverse-mode automatic differentiation over the
pricing computation graph. **One forward pass + one reverse pass yields *all* sensitivities at ~3–5×
the cost of a single price — independent of the number of inputs.** This is how banks get thousands
of Greeks for thousands of trades overnight. Build a small **hand-rolled tape** on one product to
*own the adjoint*, then use **JAX** for breadth.

> The AAD cost claim is the headline: bump costs `O(n_inputs × price)`; AAD costs `O(price)` for *all*
> inputs. The reason is the reverse-mode chain rule — you propagate sensitivities backward through the
> graph once, accumulating every input's contribution in a single sweep.

### Picturing AAD: one forward sweep, one reverse sweep

Pricing is a chain of operations from inputs to a final price. AAD records that chain on a **tape**,
then walks it **backward** once, carrying the derivative of the price w.r.t. each intermediate value
(the "adjoint", written `v̄`). One backward walk produces *every* input's sensitivity at once:

```
   FORWARD sweep (compute the price, record the tape)
   inputs                                                 output
   S ─┐
   σ ─┼─► [ build paths ] ─► [ eval payoff ] ─► [ average+discount ] ─► PV
   r ─┤        a                  b                     c
   ...┘
        ───────────────────────────────────────────────────────►

   REVERSE sweep (walk the tape backward, accumulate adjoints)
        ◄───────────────────────────────────────────────────────
   ∂PV/∂S ◄─┐
   ∂PV/∂σ ◄─┼── c̄=1 ─► b̄ ─► ā ─► seeds every input's adjoint
   ∂PV/∂r ◄─┤
   ...    ◄─┘
   ► ALL Greeks fall out of this single backward pass, regardless of how many inputs there are.
```

**Bump** would re-run the whole forward sweep once per input (delta, then vega, then rho, …) — cost
grows with the number of inputs. **AAD** runs forward once + backward once — cost is a small constant
multiple (~3–5×) of a single price, *independent* of input count. That is the entire reason banks use
it to get thousands of Greeks overnight.

## Defend it
- Derive the pathwise delta estimator and prove it's unbiased; explain why it fails for a digital.
- Why LR rescues digitals and why it's higher variance.
- The AAD cost claim and *why* reverse mode gives all Greeks at a constant multiple of one price.
- What vanna/volga mean for a short-vol autocallable book.

---

# L6 — Structurer Workstation

**Does:** the front-office magic. Client gives an objective in words/numbers; the system proposes
candidate structures, decomposes them, and **solves parameters to par**. *(Build week 11.)*

## Price-to-par solving

A note is "fair" when its model PV (the issuer's hedging cost) equals the issue price (par, e.g.
100) minus the issuer's margin. You solve for the one free parameter:

```
find coupon c        s.t.  PV_model(note(c)) = 100 − fee     # solve coupon
find KI barrier      s.t.  PV = target                       # solve protection level
find participation p s.t.  PV = target                       # solve upside
```

A single free parameter → **1-D root find (Brent)**. Multiple → constrained solve, but usually the
client fixes all-but-one ("I want 12% — what KI does that imply?"). The solver is well-posed because
**PV is monotone in the coupon** (more coupon → higher PV), so there's a unique root.

## The proposer (objective → structure)

| Client says | Likely structure |
|---|---|
| "12% coupon, can stomach 30% down" | Phoenix / autocallable with KI ≈ 70 |
| "capital protection + some upside" | capital-protected note = zero-coupon bond + call participation |
| "AI exposure, income" | worst-of autocallable on a tech basket |
| "income, mildly bearish vol" | barrier reverse convertible |

## Defend it
- What "to par" means (PV = issuer hedging cost + funding + margin).
- Why higher coupon ⟺ lower KI / more short optionality sold by the investor.
- Why the solver is well-posed (PV monotone in coupon).

---

# L7 — Historical Backtesting

**Does:** roll out issuance through history — e.g. issue a fresh Phoenix every month 2015→2025 —
price each at issue on that date's snapshot, simulate its life on the **realised** path, and
aggregate outcomes. *(Build weeks 15–16.)*

## The crucial distinction: pricing vs backtesting

- **Pricing (L4)** is **risk-neutral** — it averages over *simulated* futures to get fair value.
- **Backtesting (L7)** is **real-world** — it uses the **single path that actually happened** to
  determine each note's outcome.

Conflating these is a classic error. A backtest does *not* simulate; it replays history.

## What you measure

For each monthly issuance, use the realised underlying path to decide autocall/coupon/knock-in
outcomes, then aggregate across all issuances: **autocall-frequency distribution**, coupon income,
**capital-loss distribution**, the **tail** (worst 5%), and conditional performance in stress windows
(2008-analogue, March 2020).

## Survivorship-bias control

Use **point-in-time** index membership and a point-in-time liquid-name universe — the universe *as it
was* on each historical date, not today's. Otherwise you're silently only ever holding names that
survived, which **inflates** backtested autocall frequency.

## The story it tells

Autocallable backtests "look great until they don't": high coupons and frequent early redemptions
most of the time, punctuated by rare, severe tail losses. Capturing *that shape* honestly is the
whole point.

## Defend it
- Risk-neutral pricing vs real-world backtesting — why conflating them is wrong.
- How survivorship bias inflates backtested autocall frequency.
- Why autocallable backtests look great until they don't (short tail risk).

---

# L8 — Virtual Trading Book

**Does:** hold a simulated desk — tens to a few hundred booked notes — and produce daily marks and
daily Greeks across the book via historical replay. *(Build week 17.)*

## How it works

`book.generator` creates a realistic mix (autocallables, BRCs, capital-protected notes) across
underlyings, strikes, maturities, and plausible issue dates. Replay (L1) walks dates; each date
reprices every live trade (L4) and computes its Greeks (L5); results land in a positions/marks store.

## Why it's the scaling pressure point

`O(days × trades × pricing_cost)` — a few hundred autocallables × a few thousand paths × ~2500
replay days. This is exactly where AAD (Greeks cheaply) and the C++/GPU kernel (fast paths) earn
their keep, and where you quote your speedups.

## Portfolio-level thinking

The book teaches **netting** — you care about *net* delta/vega, not gross (long this autocall's vega,
short that one's). The book's aggregate vega is typically **negative** (autocallable desks are
structurally short vol). And **concentration** matters — one underlying often carries most of the
gamma.

## Defend it
- Netting — net vs gross risk.
- Why a book's aggregate vega is negative (structurally short vol).
- Concentration — one underlying carrying most of the gamma.

---

# L9 — Hedging Engine

**Does:** simulate the trader actually hedging the book through history and measure how well it
works. *(Build week 18.)*

## Dynamic delta hedging

Rebalance the underlying to flatten delta at each step. Because you rebalance **discretely** (daily,
not continuously), there's a **replication error** that scales with **√Δt** — the classic
Black-Scholes-Merton result: hedge more often → smaller error, but more transaction cost. You add a
**slippage/transaction-cost** parameter.

## Vega hedging

Hedge vol exposure with listed vanillas/variance. The residual after delta+vega hedging is
**vanna/volga and higher-order** — which is exactly what flows into P&L attribution (L10).

## Gap risk

An overnight jump straight *through* a barrier that no continuous hedge can catch — the **structural
tail loss** of an autocallable book. You can't delta-hedge it away.

## The gamma-theta trade-off

You either **bleed theta to be long gamma** (pay for convexity) or **earn theta to be short gamma**
(get paid to take convexity risk). An autocallable issuer is typically **short gamma near the
barrier** — earning theta but exposed to sharp moves.

**Output:** the distribution of hedging P&L, slippage cost, and the gap-loss tail.

## Defend it
- Why discrete delta-hedging P&L variance scales with rebalance frequency (√Δt).
- The gamma-theta trade-off; why an autocallable issuer is short gamma near barriers.
- Why gap risk can't be delta-hedged away.

---

# L10 — P&L Attribution

**Does:** every day, explain the change in each trade's value as a sum of risk-factor contributions —
the "P&L explain" a real desk reconciles each morning. *(Build week 19 — the single most impressive
desk-realism feature; invest in it.)*

## The math: a second-order Taylor expansion

```
ΔPV ≈  Δ·ΔS + ½Γ·(ΔS)²          (spot: delta, gamma)
     + Θ·Δt                      (time/theta)
     + ν·Δσ + ½(volga)·(Δσ)²     (vol: vega, volga)
     + (vanna)·ΔS·Δσ             (cross: vanna)
     + (corr delta)·Δρ           (correlation)
     + (rho)·Δr + (div delta)·Δq
     + UNEXPLAINED RESIDUAL
```

## The method

Compute Greeks at D−1, observe the risk-factor moves D−1→D, attribute via the Taylor formula, then
compare to the **actual full-revaluation** ΔPV. The **residual = actual − explained.**

## Why the residual is the headline number

- **Small residual** → your Greeks and your repricing agree → the model is internally consistent.
- **Large residual** → missing risk factor, large unhedged convexity, or a model problem.

Big residuals come from high gamma/vanna products near barriers. Note the two different P&Ls you
compute: **"Greek P&L"** (the Taylor estimate) vs **"revaluation P&L"** (a full reprice) — and *why
both* are computed (one explains, one is truth; the gap is the diagnostic).

## Defend it
- Why the residual is the most informative number in the whole report.
- Which products generate big residuals (high gamma/vanna near barriers).
- Greek P&L (Taylor) vs revaluation P&L (full reprice) and why both are computed.

---

# L11 — Model Risk Engine

**Does:** the model-validation seat. Compare LV / Heston / LSV, compute reserves, and dashboard model
risk. *(Build week 20.)*

## The central idea: marginals vs dynamics

LV and LSV are both calibrated to the **same market** and both reprice **every vanilla option
perfectly** — yet they give **different prices** for the autocallable. How?

- A **vanilla** option only cares "where does the stock *end up*?" — the **marginal distribution** of
  the terminal level. Matching all vanilla prices = matching all marginals. Both models do this. ✅
- An **autocallable** is **path-dependent** — it asks "given the stock is at level X at month 12, how
  volatile will it be *from there*?" That's a question about **dynamics**, which vanilla prices say
  *nothing* about. Here the models diverge:
  - **Local Vol:** future vol is a deterministic function of price/time — no randomness. It
    **flattens the forward smile.**
  - **LSV:** future vol stays randomly alive — realistic forward smile.

> The mind-bender: matching every snapshot of *where prices might end up* does **not** pin down how
> prices *move between* snapshots. Two models can share all marginals yet differ in dynamics.
> Path-dependent products see the difference; vanillas don't.

## The model reserve = real money

Say LV prices the autocallable at ₹100.00 and LSV at ₹98.50. That **₹1.50 gap** is genuine
uncertainty about your own valuation. A responsible desk doesn't book the optimistic number — it
holds the difference as a **model reserve**: P&L it refuses to claim because it doesn't trust any one
model that far. This is *why a desk runs multiple models on purpose* — the spread between them is the
honest measure of model risk.

## Other reserves
- **Parameter-uncertainty reserve:** perturb calibrated params within their confidence region;
  reserve = the spread of resulting prices.
- **Bid-offer reserve:** price at bid-side and offer-side marks; reserve = half-spread × sensitivity.

## Defend it
- Why LV and LSV agree on vanillas but disagree on autocallables (same marginals, different dynamics).
- What a model reserve is *for* (P&L you can't book because you don't trust the model that far).
- Why a desk runs multiple models on purpose.

---

# L12 — Stress Testing

**Does:** apply named macro scenarios to a snapshot, reprice the whole book, and decompose the
impact. *(Build week 21.)*

## The scenarios

Equity crash (−30% spot), vol spike (+10 vol pts, surface steepens), correlation breakdown (ρ → 0.9
across the board, PSD-repaired), dividend shock, rate shock — plus historical replays (March 2020).

## The key principle: coherence

Shocks must be **coherent**, not independent single-factor bumps. A real crash *also* spikes
volatility *and* pushes correlations up — all together. Applying a −30% spot shock with vol and
correlation held flat is unrealistic, and you should say so. You transform the snapshot coherently,
reprice via L4, and attribute the hit by risk factor and by product.

## Why it bites the autocallable book

**Correlation-up is the killer scenario for a worst-of book** (everything falls together → the worst
performer drags the payoff). And an autocallable book's worst day is a **sharp drop through the
knock-in with no autocall relief** — you take the downside without ever getting the early redemption.

## Defend it
- Why scenarios must be coherent (crash + vol-up + corr-up together), not independent bumps.
- Why correlation-up is the killer scenario for a worst-of book.
- Why an autocallable book's worst day is a sharp drop through the KI with no autocall relief.

---

# L13 — Documentation Engine

**Does:** auto-generate the client-facing and internal paperwork from the term-sheet object —
indicative term sheet, scenario-at-maturity table, factsheet, risk disclosures. *(Build week 12 /
ongoing.)*

## How it works

A **Pydantic** term-sheet model → **Jinja** templates → Markdown/HTML/PDF. The
**scenario-at-maturity table** comes free from the pricer (evaluate the payoff across a grid of
terminal underlying levels). Cheap to build, disproportionately impressive in a demo because it looks
like a real bank document.

## The one real point

The term sheet is generated from the **same object the pricer consumes**, so the document can never
disagree with the price. In a real bank, doc-vs-price mismatch is a genuine source of operational
risk; this design eliminates it by construction.

## Defend it
- Nothing deep — just that the term sheet and the price come from the *same* object, so they can't
  disagree.

---

# L14 — Executive Dashboard

**Does:** the front-office screen — desk NAV, daily P&L with attribution, aggregate Greeks, model
reserves, top risk concentrations and contributors, latest stress results. *(Build week 22.)*

## How it works

**Streamlit** (MVP) reading the marks/positions/attribution stores; **FastAPI + a small React front
end** if you go advanced. Design it to look like a **desk blotter**, not a homework plot: dark,
dense, tabular, with a "drill into trade" path.

## What it should surface first

What a head of desk looks at each morning, in order: **overnight P&L explain + residual**, then **top
concentrations**. Your dashboard surfaces exactly that.

## Defend it
- What a head of desk looks at first each morning (overnight P&L explain + residual, then top
  concentrations), and that your dashboard leads with it.

---

# Appendix A — Do you need live data?

**No. The entire project runs on end-of-day (EOD) historical data, by design.** The system is
"snapshot in, report out," and the snapshot is almost always a *historical* date you replay through.
Nothing in the core needs to know what's happening *right now*.

What you use (all free, all EOD/historical): **NSE F&O bhavcopy** (backbone), **NSE cash bhavcopy**,
**yfinance** (backup), **FBIL/RBI** rates, **NSE corporate actions**. Even the volatility surface is
*reconstructed* from downloaded EOD settlement prices.

"Live" appears in only two places, both deliberately downgraded:
1. The **NSE option-chain JSON endpoint** (today's live IVs) — fragile, rate-limited, format-changing.
   *Optional demo garnish only — never depend on it.*
2. **Real-time market connectivity** — explicitly in the **SKIPPED (declared)** bucket. You name it
   as out-of-scope so an interviewer knows you *chose* not to build it.

Why this is correct, not a compromise: a bank's "official close" marks are also EOD snapshots; EOD is
what makes deterministic replay and reproducible P&L possible; and live feeds are costly, brittle
plumbing that teach nothing about quant — the exact "engineering theatre" the spec warns against.

> Interview framing: *"It's an EOD system, like a desk's official-close process. I deliberately
> scoped out real-time connectivity — it's plumbing, not quant, and it would break reproducibility."*

---

# Appendix B — Glossary

Terms are grouped so related ideas sit together. Bold cross-links point to where each is explained.

## Products & structuring
- **Structured product / note** — a custom investment built from options, sold to a client. A
  *portfolio of optionality in disguise.*
- **Autocallable** — note that redeems early ("autocalls") if the underlying is above a level on an
  observation date, pays coupons, and exposes the investor to losses if a knock-in barrier is
  breached. *The flagship product.*
- **Phoenix** — an autocallable with **memory coupons** and a below-strike coupon barrier.
- **Memory coupon** — a coupon that, if missed, accrues and is paid on the next date the barrier is met.
- **Barrier Reverse Convertible (BRC)** — high-coupon note where the investor is effectively *short a
  knock-in put* (capital at risk if the barrier breaks).
- **Worst-of / best-of** — payoff driven by the worst (or best) performer among several underlyings.
- **Knock-in (KI) / knock-out** — a barrier that activates (knock-in) or cancels (knock-out) a payoff
  once the underlying crosses it.
- **Autocall barrier / coupon barrier** — the levels checked on each observation date for early
  redemption / coupon payment.
- **Capital protection** — feature guaranteeing return of (some of) principal; built as a
  zero-coupon bond + call participation.
- **Par / price-to-par** — a note is "at par" when its model PV equals the issue price (100) minus
  the issuer's margin. The structurer **solves to par** for one free parameter. *(See [L6](#l6--structurer-workstation).)*
- **Term sheet** — the document defining a note's parameters; in SPDT, the same object the pricer
  consumes. *(See [L13](#l13--documentation-engine).)*

## Volatility & the surface
- **Implied volatility (IV)** — the volatility that makes Black-Scholes reproduce an option's market
  price. The "universal language" of option prices. *(See [L1](#l1--market-data-service).)*
- **Volatility surface** — IV as a function of strike and expiry, `vol(K,T)`. *(See [L2](#l2--volatility-analytics).)*
- **Smile / skew** — the shape of IV across strikes (downside puts cost more).
- **Term structure** — how IV varies across expiries.
- **Total variance** — `w = σ²·T`; the natural additive quantity for surface work.
- **Log-moneyness** — `k = log(K/F)`; 0 = at-the-money.
- **SVI** — *Stochastic Volatility Inspired*; a 5-parameter fit for **one** expiry's smile.
- **SSVI** — *Surface SVI*; ties all slices together and is **calendar-arbitrage-free by construction**.
- **Butterfly arbitrage** — within one expiry; implied probability density goes negative. Detected by
  **Durrleman's condition**.
- **Calendar arbitrage** — across expiries; total variance fails to increase with time.
- **Dupire / local volatility** — the instantaneous vol `σ(S,t)` derived from the surface; reprices
  all vanillas exactly by construction.
- **Forward smile** — the implied smile of a future return; the diagnostic that exposes Local Vol's
  flattening pathology.
- **Sticky-strike / sticky-delta** — assumptions about how the surface moves when spot moves; they
  change your delta.

## Models & pricing
- **Black-Scholes (BS)** — constant-volatility benchmark model with closed-form vanilla prices.
- **Local Vol (LV)** — volatility is a fixed function of price and time; reprices vanillas exactly;
  flattens the forward smile.
- **Heston** — stochastic-volatility model; volatility has its own random process.
- **QE scheme** — Andersen's *Quadratic-Exponential* simulation scheme for Heston's variance (Euler
  can go negative; QE is the standard fix).
- **Characteristic function / Carr-Madan FFT** — fast vanilla pricing used to *calibrate* Heston.
- **LSV** — *Local-Stochastic Volatility*; the production standard. Combines stochastic variance with
  a **leverage function** `L(S,t)` so it reprices the whole vanilla surface *and* has realistic
  dynamics. *(See [L4](#l4--pricing-engine).)*
- **Leverage function** — the `L(S,t)` correction in LSV, set by
  `L² = σ²_Dupire / E[v_t | S_t=S]`.
- **Marginals vs dynamics** — *marginals* = distribution of where the price ends up (all vanilla
  prices pin these down); *dynamics* = how the price moves between dates (path-dependent products
  see these). The crux of the [model reserve](#l11--model-risk-engine).
- **Monte Carlo (MC)** — pricing by simulating many random future paths and averaging the payoff.
- **PDE / Crank-Nicolson** — pricing by solving the pricing differential equation on a grid;
  practical only in 1–2 dimensions.
- **Risk-neutral** — the pricing world where all assets drift at the risk-free rate; used for *fair
  value*. Contrast with *real-world* (used for [backtesting](#l7--historical-backtesting)).

## Monte Carlo machinery
- **Path** — one simulated future trajectory of the underlying(s).
- **`Z`** — a standard-normal random draw; the source of randomness per step.
- **Sobol sequence** — low-discrepancy "smart random" numbers that fill space evenly → faster convergence.
- **Antithetic variates** — pairing `Z` with `−Z` to cancel noise.
- **Control variate** — pricing a solvable instrument alongside to correct the estimate.
- **Brownian bridge** — path construction that gives the most important time points the best random coordinates.
- **Common Random Numbers (CRN)** — reusing the same paths across bumps so Greeks are stable.
- **Cholesky factorization** — decomposes the correlation matrix to generate correlated random draws.

## Greeks & risk
- **Greeks** — sensitivities of price to inputs. *(See [L5](#l5--greeks-engine).)*
- **Delta (Δ)** — ∂Price/∂spot (the hedge ratio). **Gamma (Γ)** — ∂²/∂spot² (convexity).
- **Vega (ν)** — ∂/∂vol. **Theta (Θ)** — ∂/∂time (time decay). **Rho** — ∂/∂rate.
- **Vanna** — ∂²/∂spot∂vol. **Volga / Vomma** — ∂²/∂vol². **Charm** — ∂²/∂spot∂time. **Speed** —
  ∂³/∂spot³.
- **Bump-and-revalue** — Greeks by nudging an input and repricing.
- **Pathwise derivative** — Greeks by differentiating the payoff along the path; unbiased for smooth
  payoffs, fails for digitals/barriers.
- **Likelihood-ratio (LR) / Malliavin** — Greeks by differentiating the density; works for
  discontinuous payoffs, higher variance.
- **AAD** — *Adjoint Algorithmic Differentiation*; reverse-mode AD giving **all** Greeks at a small
  constant multiple of one price.
- **Short vol / short gamma** — exposures that lose money when volatility rises / when the underlying
  moves sharply; the structural position of an autocallable issuer.
- **Vega ladder** — vega broken out by maturity bucket.

## Desk, portfolio & validation
- **Market Snapshot** — the immutable, content-hashed "market as of date D"; the central abstraction.
  *(See [L1](#l1--market-data-service).)*
- **Replay** — iterating pricing/risk over historical snapshots, deterministically.
- **Netting** — net (not gross) risk across the book.
- **P&L attribution / "explain"** — decomposing daily P&L into Greek contributions + a **residual**.
  *(See [L10](#l10--pl-attribution).)*
- **Residual** — the unexplained part of the P&L explain; the key model-consistency diagnostic.
- **Model reserve** — money set aside because models disagree (e.g. LSV−LV); profit you won't book.
  *(See [L11](#l11--model-risk-engine).)*
- **Bid-offer reserve / parameter-uncertainty reserve** — reserves for spread and calibration uncertainty.
- **Gap risk** — loss from an overnight jump through a barrier that no continuous hedge catches.
- **Slippage** — transaction cost / market impact incurred when rebalancing a hedge.
- **Survivorship bias** — using today's surviving universe for historical tests; inflates backtested
  outcomes. *(See [L7](#l7--historical-backtesting).)*
- **Coherent scenario** — a stress shock where spot, vol, and correlation move *together* realistically.
  *(See [L12](#l12--stress-testing).)*
- **Provenance tag** — label on each data point: observed / interpolated / synthetic.
- **PSD (positive semi-definite)** — property a valid correlation matrix must have; restored by
  **Higham's algorithm**.
- **Copula (Gaussian / t)** — the dependency structure for multi-asset paths; the t-copula adds **tail
  dependence** (joint crashes).

## Project meta
- **Scope contract** — the REAL / FAITHFUL / STUBBED / SKIPPED labelling of every capability.
- **DSL (Domain-Specific Language)** — here, the payoff grammar: products as graphs of primitives.
  *(See [L3](#l3--product-definition-dsl).)*
- **ADR (Architecture Decision Record)** — a short doc per non-obvious design choice.
- **DoD (Definition of Done)** — the concrete success criterion ending each build phase.

---

*Companion to `SPDT_Design_and_Build.md` v1.0. This document explains; the spec builds.*
