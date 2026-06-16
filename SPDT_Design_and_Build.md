# Structured Products Digital Twin (SPDT)
### Design Specification & Exact Build Roadmap — v1.0

> A complete simulation of an equity structured-products desk: structuring → pricing → hedging → risk → model validation → P&L attribution, built on **free Indian market data** by a single student over ~6 months.

---

## 0. How to read this document

This is two documents fused together:

1. **A design spec** — what the system is, the architecture, the quant content of every layer, and the honest line between "what a Tier-1 bank does" and "what you will actually build."
2. **A build roadmap** — an exact, week-by-week plan that gets you from empty repo to a defensible flagship, prioritising the things that survive an interview.

Two rules govern everything below:

- **Faithful, not fake.** Every component is *architecturally and methodologically faithful* to how a real desk works, even where it is simplified. You never claim more than you built.
- **The math is the asset, not the code.** The single biggest failure mode for a project like this is shallow ownership of the core math — being able to run an autocallable Monte Carlo but unable to derive why the pathwise delta estimator is unbiased. Every layer below ends with a **"You must be able to defend"** box. Treat those as the real deliverable.

> **Reuse note (read first):** This project is a deliberate *superset* of your ESP (Equity Structuring & Exotics Platform) and shares a lineage with your XVA engine. The autocallable LSV pricer, the AAD spine, the dependency-graph architecture, and the model-reserve artefact you already designed for ESP are **Layers 4, 5, and 11 of this system**. Do not rebuild them. SPDT's new content is the *desk simulation* around the pricer: the structurer workstation, the virtual book, historical replay, hedging simulation, and P&L attribution. Frame SPDT as "ESP grown into a full desk twin," and you save ~2 months.

---

## 1. The scope contract (the most important section)

A student cannot build a Tier-1 desk. A student *can* build a system whose architecture is indistinguishable from one and whose core is genuinely correct. The trick is to be explicit, up front, about which of four buckets each capability falls into:

| Bucket | Meaning | Example in SPDT |
|---|---|---|
| **REAL** | Mathematically correct, production-shaped, you own it end to end | SVI/SSVI calibration, autocallable MC pricing, bump & pathwise Greeks, P&L attribution |
| **FAITHFUL** | Correct method, scoped scale; the real version differs only in size/optimisation | AAD over the pricing graph, LSV calibration, the payoff DSL, historical replay |
| **STUBBED** | Architecturally present with a clean interface; implementation is a convincing placeholder | C++/GPU pricing kernels (interface defined, Python reference impl behind it), message queue (in-process bus that *could* be Kafka) |
| **SKIPPED (declared)** | Out of scope, named explicitly so nobody thinks you missed it | Real-time market connectivity, regulatory capital (FRTB market risk), multi-currency/quanto at scale |

**Why this matters in interviews:** the strongest signal you can send is knowing exactly where the edges of your own system are. "I implemented SVI with arbitrage repair; LSV calibration is faithful but I calibrate the leverage function on a coarse grid because I'm single-threaded in Python" is a *senior* answer. "I built everything" is a junior red flag.

Keep this table live in the README and update the buckets as you go.

---

## 2. Data strategy — building a vol-surface business on free data

This is your hard constraint and your most interesting engineering story. Most students fake the data and it shows. You will instead build a real ingestion layer on free Indian sources, with synthetic fallback only where genuinely necessary, and you will be honest about the gaps. This is exactly the pattern you used on the XVA engine (FIMMDA/RBI-DBIE + synthetic fallback) — reuse the discipline.

### 2.1 The universe

Restrict to what is genuinely liquid and free:

- **Indices:** NIFTY 50, BANKNIFTY (NIFTY Bank). Deep, liquid option chains.
- **Single names:** the ~15–25 most F&O-liquid stocks (Reliance, HDFC Bank, ICICI, Infosys, TCS, SBIN, etc.).

A worst-of/basket product on 3 liquid names is enough to exercise the entire correlation + multi-asset MC machinery. You do not need 200 underlyings.

### 2.2 Free sources (and what each is actually good for)

| Source | Gives you | Reliability | Use for |
|---|---|---|---|
| **NSE F&O bhavcopy** (daily ZIP/CSV archive) | Daily **settlement prices for every option and future contract**, OI, volume | High, stable format, full history | **This is the backbone** — historical vol surfaces (see 2.3) |
| **NSE cash bhavcopy** | Daily OHLC for all cash equities + indices | High | Underlying spot history, returns, correlation |
| **yfinance** (`^NSEI`, `^NSEBANK`, `RELIANCE.NS`) | EOD OHLC, some intraday, splits | Medium (best-effort) | Quick spot series, cross-checks, gap-fill |
| **NSE option-chain JSON endpoint** | *Live* IV snapshot for current expiries | Low (fragile, needs headers/cookies, rate-limited, changes) | Optional live "today's surface" demo only — never depend on it |
| **FBIL / RBI** | MIBOR, OIS, T-bill yields, reference rates | High | Discount curve, drift |
| **NSE corporate actions** | Dividends, splits, bonus | Medium | Dividend curve, dividend delta |

**Key insight that solves the "no historical IV" problem:** you do **not** need a paid IV history. The F&O bhavcopy contains the **daily settlement price of every option contract**. Combined with the underlying close and a discount rate, you invert Black-Scholes per contract to get **implied vol per (strike, expiry) for every historical day**. That gives you a genuine historical implied-vol surface time series — for free — which is the single most valuable dataset for the whole project (backtesting, vega P&L, model reserve, surface versioning all depend on it).

### 2.3 The data pipeline (build this first — Week 1–2)

```
                          ┌─────────────────────────────┐
   NSE bhavcopy (F&O) ───►│  Raw landing (parquet)      │
   NSE bhavcopy (cash) ──►│  partitioned by date        │
   yfinance ────────────►│  immutable, append-only     │
   FBIL/RBI ────────────►└──────────────┬──────────────┘
                                         │ clean + validate
                                         ▼
                          ┌─────────────────────────────┐
                          │  Curated store              │
                          │  - spot series              │
                          │  - per-contract option px   │
                          │  - implied vol points       │  ◄── BS inversion
                          │  - rate curve               │
                          │  - dividend schedule         │
                          └──────────────┬──────────────┘
                                         │ snapshot
                                         ▼
                          ┌─────────────────────────────┐
                          │  Market Snapshot (versioned)│  ◄── this is the unit
                          │  one immutable object per   │      everything else
                          │  business date              │      consumes
                          └─────────────────────────────┘
```

**The Market Snapshot is the central abstraction of the entire system.** It is an immutable, versioned object representing "the market as of date D": spot levels, the calibrated vol surface(s), the correlation matrix, the rate curve, the dividend schedule. Every other layer takes a snapshot as input and never touches raw data. This single design choice is what makes historical replay, backtesting, and reproducible P&L attribution possible — and it is exactly how a real desk's "official close" works.

### 2.4 Synthetic fallback (declared, bounded)

Where real data is missing (illiquid strikes, pre-listing history, a name with thin options), generate synthetically — but make it *visible*:

- Fill missing surface points by calibrating SVI to the liquid points and extrapolating, flagged `source=interpolated`.
- For stress/backtest scenarios with no historical analogue, generate paths from a calibrated model, flagged `source=synthetic`.
- **Never silently mix.** Every data point carries a provenance tag. A risk report that can say "this vega is computed on 80% observed / 20% interpolated surface" is more credible than one that hides it.

### 2.5 Data hygiene that earns credit

- **Versioning:** snapshots are content-addressed (hash of inputs). Re-running yesterday gives byte-identical results. This is "reproducible risk," a real desk requirement.
- **Survivorship bias control** (matters for backtesting, Layer 7): your universe must be the universe *as it was* on each historical date, not today's universe. Maintain a point-in-time membership list; otherwise your Phoenix backtest is silently cheating by only ever holding names that survived.
- **Holiday / corporate-action calendar:** NSE trading calendar + adjustment for splits/bonus so spot series are continuous.

> **You must be able to defend:** why BS-inverting settlement prices gives a usable but biased IV (settlement ≠ traded mid, wide bid-offer on wings); how you detect and repair calendar/butterfly arbitrage in the resulting raw surface before calibration; what survivorship bias does to a backtested autocall frequency (inflates it).

---

## 3. System architecture

### 3.1 The spine: a desk, not a library

The thing that makes SPDT more than a pricer is that the architecture mirrors the **people and the workflow** of a real desk. Each role maps to a service, and a trade flows through them:

```
  CLIENT          "I want 12% on AI names, can stomach 30% down"
    │
    ▼
  STRUCTURER  ──► Structurer Workstation (L6)
    │             solves params to par, proposes candidate notes
    ▼
  TRADER      ──► Pricing Engine (L4) + Greeks Engine (L5)
    │             prices it, books it into the Virtual Book (L8)
    ▼
  RISK MGR    ──► Risk reports (L5), Stress (L12), P&L Attribution (L10)
    │
    ▼
  MODEL VAL   ──► Model Risk Engine (L11): LV vs Heston vs LSV, reserves
    │
    ▼
  HEDGING     ──► Hedging Engine (L9): dynamic delta/vega, residual P&L
    │
    ▼
  HISTORY     ──► Backtesting (L7) + Historical Replay (L1) feed it all
```

Underneath, three foundational services that everyone consumes:
**Market Data (L1)**, **Volatility Analytics (L2)**, and the **Product Definition DSL (L3)**.

### 3.2 Component diagram (services & dependencies)

```
┌───────────────────────────────────────────────────────────────────────┐
│                         EXECUTIVE DASHBOARD (L14)                       │
│         NAV · P&L · Greeks · reserves · concentrations · stress         │
└───────────────────────────────────────────────────────────────────────┘
            ▲            ▲             ▲            ▲            ▲
            │            │             │            │            │
   ┌────────┴───┐ ┌──────┴─────┐ ┌─────┴──────┐ ┌───┴──────┐ ┌───┴────────┐
   │ Hedging L9 │ │ P&L Attr   │ │ Model Risk │ │ Stress   │ │ Docs Engine│
   │            │ │   L10      │ │   L11      │ │   L12    │ │   L13      │
   └────┬───────┘ └─────┬──────┘ └─────┬──────┘ └────┬─────┘ └─────┬──────┘
        │               │              │             │             │
        └───────────────┴──────┬───────┴─────────────┴─────────────┘
                               ▼
                ┌──────────────────────────────┐
                │     VIRTUAL TRADING BOOK L8   │  trades, positions, daily marks
                └──────────────┬───────────────┘
                               │
        ┌──────────────────────┼───────────────────────┐
        ▼                      ▼                        ▼
┌───────────────┐   ┌────────────────────┐   ┌────────────────────┐
│ Structurer L6 │   │  Backtesting  L7   │   │  Greeks Engine  L5 │
│  (par solver) │   │ (rolling issuance) │   │ bump/pathwise/AAD  │
└───────┬───────┘   └─────────┬──────────┘   └─────────┬──────────┘
        │                     │                        │
        └─────────────────────┼────────────────────────┘
                               ▼
                ┌──────────────────────────────┐
                │      PRICING ENGINE  L4       │  CF / PDE / MC / LSV
                └──────────────┬───────────────┘
                               │ consumes payoffs + snapshots
        ┌──────────────────────┼───────────────────────┐
        ▼                      ▼                        ▼
┌───────────────┐   ┌────────────────────┐   ┌────────────────────┐
│ Product DSL L3│   │ Vol Analytics  L2  │   │  Market Data   L1  │
│ payoff graph  │   │ SVI/SSVI/LV/fwd    │   │ snapshots, replay  │
└───────────────┘   └────────────────────┘   └────────────────────┘
```

### 3.3 Data-flow (one trading day in replay)

```
date D ──► L1 loads/builds Market Snapshot(D)
        ──► L2 calibrates surface(s) on D, exposes vol(K,T), local vol, fwd smile
        ──► L8 walks every booked trade:
                 L4 reprices on Snapshot(D)
                 L5 computes Greeks on Snapshot(D)
        ──► L10 explains PnL(D-1→D) = Σ Greek·Δrisk-factor + residual
        ──► L9 computes the day's hedge rebalance + hedging P&L
        ──► L11 recomputes model reserve (LSV−LV) on new surface
        ──► L12 (periodic) shocks Snapshot(D) and reprices the book
        ──► L14 aggregates: desk NAV, P&L, top risks, reserves
```

Everything is **snapshot-in, report-out**, which is why the whole thing replays deterministically over history.

### 3.4 Why this is "no monolith" without microservice theatre

You will **not** stand up 14 Docker containers and a real Kafka cluster — that is engineering theatre that adds months and teaches you nothing about quant. Instead:

- Each layer is a **Python package** with a **clean, typed public API** (a `Protocol`/ABC), no cross-layer reaching into internals.
- They communicate through an **in-process event bus** (a thin pub/sub class). The *interface* is message-shaped, so the claim "this could be swapped for Kafka/Redis Streams without touching business logic" is true and defensible.
- One layer (e.g. the pricing engine) can later be lifted into its own process/service behind the same API to prove the boundary is real. Do this for *one* layer as a demonstration, not all 14.

This is the honest version of "modular services": real boundaries, deferred distribution.

---

## 4. Repository structure

```
spdt/
├── README.md                      # vision + the live scope-contract table
├── pyproject.toml                 # uv/poetry; pinned deps
├── docs/
│   ├── architecture.md            # this document, trimmed
│   ├── adr/                       # architecture decision records (1 per big choice)
│   └── interview_defense.md       # the "you must defend" boxes, collected
├── spdt/
│   ├── core/                      # shared types: Date, Snapshot, Currency, enums
│   │   ├── snapshot.py            # the immutable Market Snapshot (the spine)
│   │   ├── bus.py                 # in-process event bus (the "queue" interface)
│   │   └── provenance.py          # data source tagging
│   ├── data/                      # L1 Market Data Service
│   │   ├── ingest/                # nse_bhavcopy.py, yfinance_src.py, fbil.py
│   │   ├── curate/                # cleaning, BS-inversion to IV points
│   │   ├── store.py               # parquet curated store, versioned
│   │   └── replay.py              # historical replay iterator
│   ├── vol/                       # L2 Volatility Analytics
│   │   ├── svi.py                 # raw SVI calibration
│   │   ├── ssvi.py                # surface-SVI (no calendar arb by construction)
│   │   ├── arbitrage.py           # butterfly + calendar checks/repair
│   │   ├── localvol.py            # Dupire local vol from surface
│   │   ├── forward_smile.py       # forward-starting smile extraction
│   │   └── stickiness.py          # sticky strike/delta/moneyness regimes
│   ├── corr/                      # correlation framework
│   │   ├── estimators.py          # historical, EWMA, implied
│   │   ├── psd.py                 # Higham nearest-PSD projection
│   │   └── copula.py              # Gaussian + t copula samplers
│   ├── products/                  # L3 Product Definition DSL
│   │   ├── primitives.py          # Barrier, Digital, Coupon, Autocall, WorstOf...
│   │   ├── graph.py               # payoff as a DAG of primitives
│   │   ├── catalog.py             # Phoenix, Autocallable, BRC, etc. compositions
│   │   └── termsheet.py           # structured params per product
│   ├── pricing/                   # L4 Pricing Engine
│   │   ├── engine.py              # dispatch: closed-form / PDE / MC
│   │   ├── analytic/              # BS, digital, single barrier closed forms
│   │   ├── pde/                   # 1D Crank-Nicolson (LV) for vanilla/barrier
│   │   ├── mc/                    # path gen, RNG, variance reduction
│   │   │   ├── rng.py             # Sobol + Mersenne, antithetic, brownian bridge
│   │   │   ├── schemes.py         # Euler/Milstein, QE for Heston
│   │   │   └── paths.py           # correlated multi-asset path generator
│   │   └── models/                # BS, LocalVol, Heston, LSV
│   ├── greeks/                    # L5 Greeks Engine
│   │   ├── bump.py                # bump-and-revalue (+ central, CRN)
│   │   ├── pathwise.py            # pathwise derivative estimators
│   │   ├── likelihood.py          # likelihood-ratio / Malliavin for digitals
│   │   └── aad/                   # tape-based reverse-mode AD
│   ├── structurer/                # L6 Structurer Workstation
│   │   ├── solver.py              # price-to-par root finder
│   │   ├── objectives.py          # "12% coupon", "capital protected", ...
│   │   └── proposer.py            # objective -> candidate structures
│   ├── backtest/                  # L7 Historical Backtesting
│   │   ├── issuance.py            # rolling monthly issuance
│   │   └── stats.py               # autocall freq, loss dist, tail metrics
│   ├── book/                      # L8 Virtual Trading Book
│   │   ├── book.py                # positions, daily marks, daily greeks
│   │   └── generator.py           # synth a desk of N notes
│   ├── hedging/                   # L9 Hedging Engine
│   │   └── delta_vega.py          # dynamic hedge sim, slippage, gap loss
│   ├── pnl/                       # L10 P&L Attribution
│   │   └── attribution.py         # Taylor explain: delta/gamma/theta/vega/vanna/volga/corr/residual
│   ├── modelrisk/                 # L11 Model Risk Engine
│   │   └── reserves.py            # LSV-LV reserve, param-uncertainty, bid-offer
│   ├── stress/                    # L12 Stress Testing
│   │   └── scenarios.py           # crash, vol spike, corr breakdown, div/rate shock
│   ├── reporting/                 # L13 Documentation Engine
│   │   └── termsheet_render.py    # indicative term sheet, factsheet, scenario table
│   └── dashboard/                 # L14 Executive Dashboard (Streamlit/Dash/FastAPI+React)
├── cpp/                           # FAITHFUL/STUBBED: hot kernels (pybind11)
│   └── mc_kernel/                 # correlated path gen + payoff eval
├── tests/                         # mirror of spdt/ — this is graded heavily
│   ├── analytic_benchmarks/       # MC vs closed-form convergence
│   ├── greeks_consistency/        # AAD vs bump vs pathwise agree
│   └── arbitrage/                 # surface stays arb-free
└── notebooks/                     # exploration only; nothing important lives here
```

**Folder-structure principles that read as senior:**
- `tests/` mirrors `spdt/` one-to-one. A reviewer who opens `tests/` first should learn what the system does.
- Cross-layer calls go through `__init__.py` public APIs only. No `from spdt.pricing.mc.paths import _internal`.
- `docs/adr/` (Architecture Decision Records): one short file per non-obvious choice ("why SSVI not just SVI", "why QE scheme for Heston", "why in-process bus"). This is the single cheapest credibility signal you can produce.

---

## 5. Technology stack

| Concern | Choice | Why |
|---|---|---|
| Core language | **Python 3.12** | speed of development; the quant lingua franca |
| Numerics | NumPy, SciPy, numba | numba JITs the MC inner loop to near-C without leaving Python |
| AD | hand-rolled tape **or** JAX | JAX gives you reverse-mode AD + vectorisation + GPU "for free"; a hand-rolled tape proves you understand AAD. Build a small hand-rolled tape for one product to *learn it*, use JAX for breadth. |
| Hot kernels | **C++17 + pybind11** | one kernel (correlated MC path + payoff) ported to C++ proves the C++ claim and gives a real speedup number to quote |
| GPU | JAX/CuPy (optional) | MC is embarrassingly parallel; quote a speedup if you have a GPU, else declare it as a designed-for opportunity |
| Storage | **Parquet** (pyarrow) + DuckDB | columnar, free, fast, no server; DuckDB lets you SQL over parquet for the curated store |
| Calibration | SciPy `least_squares`, `differential_evolution` | SVI/SSVI/Heston calibration |
| Dashboard | **Streamlit** (MVP) → FastAPI + lightweight React (advanced) | Streamlit gets you a desk UI in a day; FastAPI shows you can do a real service |
| Config | Pydantic | typed term sheets and snapshots; validation for free |
| Testing | pytest + hypothesis | property-based tests for arbitrage-freeness and Greek consistency |
| Reproducibility | content-hashed snapshots, pinned seeds | deterministic replay |

**Where C++ and GPU genuinely belong** (state this, even if you stub it):
- **C++:** the Monte Carlo path generator and payoff evaluator — the 95% hot loop. A bank writes this in C++/CUDA. You port *one* product's path to demonstrate, measure the speedup, and declare the rest as "same pattern."
- **GPU:** multi-asset MC for the whole book overnight (thousands of notes × tens of thousands of paths) is the canonical GPU workload. Designed-for; implement if you have hardware.

---

## 6. Layer-by-layer quant & engineering design

Each layer: **what it does · the math · the method · complexity · what a bank does vs what you build · what you must defend.**

---

### L1 — Market Data Service

**Does:** ingest, clean, version, snapshot, and replay market data. Produces the immutable Market Snapshot every other layer consumes.

**Math/method:** BS inversion for IV points (Newton with vega, fall back to Brent for deep wings where vega → 0); calendar/holiday alignment; corporate-action back-adjustment of spot series.

**Complexity:** ingestion is I/O-bound; BS inversion is `O(contracts)` per day with a few Newton steps each — trivial.

**Bank vs you:** a bank has a tick database (kdb+), official close marks, golden-source curves, and an entire market-data org. You have parquet + DuckDB and EOD bhavcopy. The *abstraction* (versioned snapshot, official close) is identical; the scale and latency are not. Declare that.

> **Defend:** why you invert to IV per contract rather than store prices (so the surface layer is model-agnostic to spot/rate moves); Newton vs Brent for IV; why settlement-price IVs are biased on the wings.

---

### L2 — Volatility Analytics Service

**Does:** turn discrete IV points into a clean, arbitrage-free, queryable surface; expose `vol(K,T)`, local vol, forward smile, and stickiness regimes.

**Math:**
- **SVI (raw, per slice):** total variance `w(k) = a + b( ρ(k−m) + √((k−m)² + σ²) )` where `k = log(K/F)`. Five params per maturity slice. Fit by least squares to observed total variance.
- **SSVI (surface):** `w(k,θ) = (θ/2)( 1 + ρφ(θ)k + √((φ(θ)k + ρ)² + (1−ρ²)) )` with `θ` the ATM total variance term structure and `φ(θ)` a power-law or heston-like function. SSVI is **calendar-arbitrage-free by construction** under simple parameter conditions — that's the whole point of using it over independent SVI slices.
- **Butterfly (static) arbitrage:** densities must be non-negative ⇒ Durrleman's condition `g(k) ≥ 0`. Check it; repair by constraining SVI params.
- **Dupire local vol:** `σ_LV²(K,T) = ( ∂C/∂T + (r−q)K ∂C/∂K + qC ) / ( ½ K² ∂²C/∂K² )`. Compute the derivatives **on the calibrated SVI/SSVI surface in total-variance space**, never by finite-differencing raw quotes (that explodes). This is the standard trick and a key defend point.
- **Forward smile:** the smile of `S_{T2}/S_{T1}` implied by the surface — exposes that LV flattens forward smile (its known pathology) while SV/LSV keep it, motivating Layer 11.

**Method:** per-slice SVI via `least_squares` with sensible param bounds + a global SSVI fit; Durrleman check on a `k`-grid; Dupire via analytic derivatives of the SVI parametrisation.

**Complexity:** calibration `O(slices × iters × points)`; surface query `O(1)` after fit.

**Bank vs you:** banks run SSVI/SABR/proprietary surfaces with desk overrides and live recalibration. You do EOD SSVI with arbitrage repair. Faithful.

> **Defend:** SVI vs SSVI (slice vs surface, why SSVI removes calendar arb); the two arbitrage types and how each manifests; why Dupire LV reprices vanillas exactly *by construction* and what that does and doesn't buy you; sticky-strike vs sticky-delta and which regime your delta assumes.

---

### Correlation framework (feeds L4/L12)

**Math:**
- **Historical:** sample correlation of log-returns; **EWMA** for recency.
- **Implied correlation:** back out average pairwise ρ that makes a basket/index vol consistent with constituent vols: `σ_idx² = Σ wᵢ²σᵢ² + Σ_{i≠j} wᵢwⱼσᵢσⱼρ` ⇒ solve for ρ (the "implied correlation" the index dispersion desk trades).
- **PSD repair:** shocked/estimated matrices may not be PSD. **Higham (2002)** alternating-projections gives the nearest correlation matrix in Frobenius norm. Implement it; it's ~30 lines and a great signal.
- **Copulas:** Gaussian copula via Cholesky of ρ; **t-copula** adds tail dependence (one extra chi-square mixing variable) — important because equities crash together, which Gaussian copula understates.

> **Defend:** why a shocked correlation matrix breaks PSD and what a non-PSD matrix does to Cholesky/MC (imaginary "vols", negative variance); Gaussian vs t copula tail dependence and why it matters for worst-of products.

---

### L3 — Product Definition Framework (the payoff DSL)

**Does:** represent any structured note as a **composition of primitives**, not hardcoded payoff functions. This is the layer that makes the project look like a platform.

**Design:** a payoff is a **directed acyclic graph** of typed nodes evaluated against a set of simulated paths. Primitives:

`Underlying`, `Basket(weights)`, `WorstOf/BestOf`, `Barrier(level, type, monitoring)`, `Digital(strike, payout)`, `Coupon(rate, schedule)`, `MemoryCoupon`, `Autocall(barrier, schedule)`, `KnockIn(barrier)`, `Participation(rate, cap, floor)`, `CapitalProtection(level)`.

Each node implements `evaluate(paths, market) -> cashflows` and (for AAD) is differentiable.

**Compositions (show these explicitly — they are the DSL's proof):**

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
    coupon = MemoryCoupon(rate=c, barrier=CB),   # missed coupons accrue, paid on next breach
    autocall_barrier = AC_schedule,
    knock_in = KI
)

# Barrier Reverse Convertible (BRC)
BRC = ZeroCouponNote(100)
    + FixedCoupon(c)                              # high coupon = sold optionality
    - DownAndIn_Put(strike=100, barrier=KI)       # investor is SHORT a KI put
# i.e. you (the issuer) are long the KI put; investor's capital at risk if KI breached
```

The DSL turns "build a Phoenix" into "wire MemoryCoupon + Autocall + KnockIn." A reviewer sees instantly that you understand a structured note is a *portfolio of optionality*, not a magic formula.

**Bank vs you:** banks have payoff DSLs/scripting languages (e.g. internal "payoff languages"). Yours is a Python DAG. Same idea, smaller grammar.

> **Defend:** decompose a Phoenix into long/short option positions and explain who is long what; why memory coupons increase the note's value to the investor (and the issuer's short-vol exposure); continuous vs discrete barrier monitoring and the Broadie-Glasserman-Kou continuity correction.

---

### L4 — Pricing Engine

**Does:** price any DSL product under any model via closed-form, PDE, or Monte Carlo.

**Math/method by model:**
- **Black-Scholes:** analytic for vanillas/digitals/single barriers (closed forms exist — implement them as MC benchmarks).
- **Local Vol:** PDE (1D Crank-Nicolson) for low-dimensional payoffs; MC with the Dupire LV surface for path-dependents. Reprices vanillas exactly.
- **Heston:** `dS = (r−q)S dt + √v S dW₁`, `dv = κ(θ−v)dt + ξ√v dW₂`, `d⟨W₁,W₂⟩=ρdt`. Simulate with the **Andersen QE scheme** (quadratic-exponential) — Euler on the variance process is biased/can go negative; QE is the standard. Closed-form vanillas via the **Heston characteristic function + Carr-Madan FFT** (use these to *calibrate* Heston to the surface).
- **LSV (the production standard):** `dS = (r−q)S dt + L(S,t)√v S dW₁`, with stochastic variance `v` (Heston-like) and a **leverage function** `L(S,t)` calibrated so the model reprices the *entire* vanilla surface. The calibration identity (particle/Markovian projection): `L²(S,t) = σ_Dupire²(S,t) / E[v_t | S_t = S]`. The conditional expectation is estimated by a **particle method** (McKean) or by binning MC paths. This is the hard, valuable part — and it's the piece you already designed for ESP, so port it.

**Monte Carlo architecture:**
- **RNG:** Sobol (low-discrepancy) for the main estimate + Mersenne Twister for checks; **Brownian bridge** construction so the most important dimensions get the best Sobol coordinates.
- **Variance reduction:** antithetic variates, control variates (price a vanilla analytically as the control), importance sampling for deep-barrier/digital tails.
- **Correlated multi-asset paths:** Cholesky (or PCA) factorisation of the (PSD-repaired) correlation matrix drives correlated Brownian increments.
- **Common random numbers (CRN):** *the same paths/seed* across bumps — essential for stable Greeks (you used CRN in the XVA engine's incremental XVA; same principle).

**Complexity:** MC is `O(paths × steps × assets)`; LSV calibration adds an outer loop estimating conditional expectations per step ⇒ the expensive bit. PDE is `O(space × time)` and only viable in 1–2 dims (curse of dimensionality ⇒ MC for baskets/autocallables).

**Bank vs you:** banks run LSV/local-stoch-vol-with-jumps on GPU farms, nightly, over the whole book. You run scoped LSV on NIFTY/BANKNIFTY and a 3-name worst-of, single-machine, numba/JAX-accelerated. Faithful.

> **Defend:** why Euler-on-variance is wrong and what QE fixes; why LV alone misprices forward-smile-sensitive products (cliquets, forward-start) and SV alone misfits the spot smile, hence LSV; the LSV leverage-function calibration identity and what the conditional expectation means; why CRN is mandatory for finite-difference Greeks.

---

### L5 — Greeks Engine

**Does:** compute first/second-order and cross Greeks for one trade and for thousands.

**Methods (you implement all four — this is a centrepiece):**
- **Bump-and-revalue:** central differences with **CRN**; cheapest to implement, `O(2·n_risk_factors)` repricings, noisy for second order.
- **Pathwise derivative:** differentiate the payoff along the path: `∂Price/∂θ = E[∂Payoff/∂S · ∂S/∂θ]`. Unbiased and low-variance *for Lipschitz payoffs*. **Fails for discontinuous payoffs** (digitals, barriers) — the kink has no pathwise derivative.
- **Likelihood-ratio (LR) / Malliavin:** differentiate the *density* not the payoff: `∂Price/∂θ = E[Payoff · ∂log p/∂θ]`. Works for discontinuous payoffs (digitals) where pathwise fails, but higher variance. The pathwise/LR split is exactly the kind of nuance that separates serious candidates.
- **AAD (adjoint algorithmic differentiation):** reverse-mode AD over the pricing computation graph. One forward pass + one reverse pass yields **all** sensitivities at ~3–5× the cost of a single price, *independent of the number of inputs*. This is how banks get thousands of Greeks for thousands of trades overnight. Build a small hand-rolled tape on one product to show you understand the adjoint, then use JAX for breadth.

**The Greeks themselves:** delta, gamma, vega, **vanna** (∂²/∂S∂σ), **volga/vomma** (∂²/∂σ²), **charm** (∂²/∂S∂t), **speed** (∂³/∂S³), correlation delta, dividend delta. Vanna/volga matter because they drive the cost of vega hedging and feed P&L attribution (L10).

**Reports:** vega ladders (vega by maturity bucket), correlation ladders, bucketed risk by underlying/maturity/strike region.

**Complexity:** bump = `O(n_inputs · price_cost)`; AAD = `O(price_cost)` for *all* inputs — the entire reason AAD exists. State this number; it's the headline.

> **Defend:** *why pathwise is unbiased and why it fails for digitals*; *why LR rescues digitals and why it's higher variance*; the AAD cost claim ("all Greeks at a small constant multiple of one price, independent of input count") and *why* reverse mode gives that; what vanna/volga mean for a short-vol autocallable book.

---

### L6 — Structurer Workstation

**Does:** the front-office magic. Client gives an objective in words/numbers; system proposes candidate structures, decomposes them, and **solves parameters to par**.

**Math — price-to-par solver:** a note is "fair" when its model PV (issuer's hedging cost) equals the issue price (par, e.g. 100) minus the issuer's margin. You solve for the free parameter:

```
find  coupon c   s.t.  PV_model(note(c)) = 100 − fee        # solve coupon
find  KI barrier s.t.  PV = target                          # solve protection level
find  participation p s.t. PV = target                      # solve upside
```

Single free parameter ⇒ 1D root find (Brent). Multiple ⇒ constrained solve; usually you fix all but one because clients specify all-but-one ("I want 12% — what KI does that imply?").

**Objective → structure mapping (the proposer):**
| Client says | Likely structure |
|---|---|
| "12% coupon, can stomach 30% down" | Phoenix / autocallable with KI ≈ 70 |
| "capital protection + some upside" | capital-protected note = ZC bond + call participation |
| "AI exposure, income" | worst-of autocallable on a tech basket |
| "income, mildly bearish vol" | barrier reverse convertible |

**Bank vs you:** a structurer's pricer does exactly this — solve to par given a target. Your version is genuinely the same workflow.

> **Defend:** what "to par" means (PV = issuer hedging cost + funding + margin); why higher coupon ⟺ lower KI / more short optionality sold by the investor; why the solver is well-posed (PV monotone in coupon).

---

### L7 — Historical Backtesting Engine

**Does:** roll out issuance through history (e.g. issue a fresh Phoenix every month 2015→2025), price each at issue on that date's snapshot, simulate its life on *realised* paths, and aggregate outcomes.

**Math/method:** for each issuance date use the **historical realised path** of the underlying to determine autocall/coupon/KI outcomes (this is a backtest, not a risk-neutral simulation — use the real path that happened). Aggregate: autocall-frequency distribution, coupon income, capital-loss distribution, tail (worst 5%), and conditional performance in stress windows (2008-analogue, March 2020, etc.).

**Survivorship-bias control:** use point-in-time index membership and point-in-time liquid-name universe; otherwise frequencies are inflated.

**Complexity:** `O(issuance_dates × pricing_cost)`; embarrassingly parallel across issuance dates.

> **Defend:** the difference between *risk-neutral pricing* (Layer 4, for fair value) and *real-world backtesting* (Layer 7, using the path that actually happened) — conflating these is a classic error; how survivorship bias inflates backtested autocall frequency; why autocallable backtests look great until they don't (short tail risk).

---

### L8 — Virtual Trading Book

**Does:** hold a simulated desk — tens to a few hundred booked notes — and produce daily marks and daily Greeks across the book via historical replay.

**Method:** `book.generator` creates a realistic mix (autocallables, BRCs, capital-protected notes) across underlyings, strikes, and maturities, with plausible issue dates. Replay (L1) walks dates; each date reprices every live trade (L4) and computes Greeks (L5); results land in a positions/marks store.

**Complexity:** `O(days × trades × pricing_cost)` — this is your scaling pressure point and the reason AAD + C++/GPU matter. A few hundred autocallables × a few thousand paths × ~2500 replay days is exactly where you'll quote your speedups.

> **Defend:** netting (your book's net delta/vega, not gross — long this autocall's vega, short that one's); why the book's aggregate vega is negative (autocallable desks are structurally short vol); concentration (one underlying carrying most of the gamma).

---

### L9 — Hedging Engine

**Does:** simulate the trader actually hedging the book through history and measure how well it works.

**Math/method:**
- **Dynamic delta hedging:** rebalance the underlying to flatten delta at each step; **discrete rebalancing error** scales with `√Δt` (the classic Black-Scholes-Merton replication error), plus transaction cost/slippage you parametrise.
- **Vega hedging:** hedge with listed vanillas/variance; residual = vanna/volga/higher-order, which feeds attribution.
- **Gap risk:** overnight jumps through a barrier that no continuous hedge catches — the structural tail loss of an autocallable book.
- Output: distribution of hedging P&L, slippage cost, gap-loss tail.

**Complexity:** `O(days × hedge_instruments × pricing)`.

> **Defend:** why discrete delta-hedging P&L variance scales with rebalance frequency; the gamma-theta trade-off (you bleed theta to be short gamma, or pay theta to be long gamma — an autocallable issuer is typically short gamma near barriers); why gap risk can't be delta-hedged away.

---

### L10 — P&L Attribution Engine

**Does:** every day, explain the change in each trade's value as a sum of risk-factor contributions — the "P&L explain" a real desk reconciles each morning.

**Math:** second-order Taylor expansion of PV in the risk factors:

```
ΔPV ≈  Δ·ΔS + ½Γ·(ΔS)²            (spot: delta, gamma)
     + Θ·Δt                       (time/theta)
     + ν·Δσ + ½(volga)·(Δσ)²      (vol: vega, volga)
     + (vanna)·ΔS·Δσ              (cross: vanna)
     + (corr delta)·Δρ            (correlation)
     + (rho)·Δr + (div delta)·Δq
     + UNEXPLAINED RESIDUAL
```

The **residual** is the headline diagnostic: a small residual means your Greeks and your repricing agree (model is internally consistent); a large residual flags missing risk factors, big convexity, or a model issue. A desk that can't explain its P&L can't trade.

**Method:** compute Greeks at D-1, observe risk-factor moves D-1→D, attribute, then compare to actual full-reval ΔPV; residual = actual − explained.

> **Defend:** why the residual is the most informative number in the whole report; which products generate big residuals (high gamma/vanna near barriers); the difference between "Greek P&L" (Taylor) and "revaluation P&L" (full reprice) and why both are computed.

---

### L11 — Model Risk Engine

**Does:** the model-validation seat. Compare LV / Heston / LSV, compute reserves, and dashboard model risk. (This is your ESP model-reserve artefact — port it.)

**Math:**
- **Model reserve = LSV price − LV price** for the same product. For forward-smile-sensitive products (autocallables, cliquets) this gap is *material* and *real money* — it's the reserve the desk holds against using the "wrong" model. The fact that LV and LSV both reprice vanillas identically but disagree on exotics is the entire reason this reserve exists, and it's a genuinely sophisticated point to make.
- **Parameter-uncertainty reserve:** perturb calibrated params within their confidence region; reserve = spread of prices.
- **Bid-offer reserve:** price at bid-side and offer-side marks; reserve = half-spread × sensitivity.

**Method:** price the book under all three models on the same snapshot; tabulate gaps; flag products where model choice dominates.

> **Defend:** *why LV and LSV agree on vanillas but disagree on autocallables* (they match the marginal distributions but not the dynamics/forward smile); what a model reserve is *for* (P&L you can't book because you don't trust your model that far); why a desk runs multiple models on purpose.

---

### L12 — Stress Testing Engine

**Does:** apply named macro scenarios to a snapshot, reprice the whole book, and decompose the impact.

**Scenarios:** equity crash (−30% spot), vol spike (+10 vol pts, surface steepens), correlation breakdown (ρ → 0.9 across the board, PSD-repaired), dividend shock, rate shock — and historical replays (March 2020).

**Method:** transform the snapshot (shock spot/surface/corr coherently — a crash also spikes vol and correlation; a one-factor shock is unrealistic and you should say so), reprice via L4, attribute the hit by risk factor and by product.

> **Defend:** why scenarios must be *coherent* (crash + vol-up + corr-up together) not independent single-factor bumps; why correlation-up is the killer scenario for a worst-of book; why an autocallable book's worst day is a sharp drop *through* the KI with no autocall relief.

---

### L13 — Documentation Engine

**Does:** auto-generate the client-facing and internal paperwork from the term sheet object — indicative term sheet, scenario-at-maturity table, factsheet, risk disclosures.

**Method:** Pydantic term-sheet model → Jinja templates → Markdown/HTML/PDF. The scenario-at-maturity table comes free from the pricer (evaluate payoff across a grid of terminal underlying levels). This layer is cheap and disproportionately impressive in a demo because it looks like a real bank document.

> **Defend:** nothing deep; just that the term sheet is generated from the *same* object the pricer consumes, so the document can never disagree with the price (a real source of operational risk that this design eliminates).

---

### L14 — Executive Dashboard

**Does:** the front-office screen — desk NAV, daily P&L with attribution, aggregate Greeks, model reserves, top risk concentrations and contributors, latest stress results.

**Method:** Streamlit (MVP) reading the marks/positions/attribution stores; FastAPI + a small React front end if you go advanced. Design it to look like a desk blotter, not a homework plot: dark, dense, tabular, with a "drill into trade" path.

> **Defend:** what a head of desk looks at first each morning (overnight P&L explain + residual, then top concentrations), and that your dashboard surfaces exactly that.

---

## 7. Data model / core schemas

These are the few objects everything else is built on (Pydantic/dataclasses). Keep them small and immutable.

```
MarketSnapshot
  date: Date
  spots: {underlying -> float}
  surfaces: {underlying -> VolSurface}        # calibrated SVI/SSVI params + raw points
  correlation: CorrelationMatrix              # PSD-validated
  rate_curve: Curve                           # discount + forward rates
  dividends: {underlying -> DividendSchedule}
  provenance: {field -> source_tag}           # observed / interpolated / synthetic
  content_hash: str                           # reproducibility

VolSurface
  underlying: str
  param_model: "SVI" | "SSVI"
  slices: {expiry -> SVIParams(a,b,rho,m,sigma)}
  arb_status: ArbReport                       # butterfly + calendar diagnostics

TermSheet            # the product instance, consumed by pricer AND doc engine
  product_type: str
  underlyings: [str]
  notional, issue_date, maturity
  schedule: [ObservationDate]
  params: {coupon, ki_barrier, ac_barriers[], participation, ...}
  payoff_graph: PayoffDAG                      # the DSL composition

Trade
  id, term_sheet: TermSheet, direction, book_date
PositionMark
  trade_id, date, pv, greeks: GreekSet, model: str
PnLExplain
  trade_id, date, delta_pnl, gamma_pnl, theta, vega_pnl, vanna, volga, corr, residual
ModelReserve
  trade_id, date, lsv_minus_lv, param_uncertainty, bid_offer
```

**Storage layout (parquet, partitioned):**
```
curated/spot/underlying=RELIANCE/year=2023/*.parquet
curated/iv_points/underlying=NIFTY/date=2023-06-15/*.parquet
snapshots/date=2023-06-15/snapshot.parquet  (+ content_hash in name)
book/marks/date=.../*.parquet
book/pnl_explain/date=.../*.parquet
```
DuckDB queries across these directly — no database server, free, fast.

---

## 8. The exact build roadmap

Sequenced so that **every phase ends in something demonstrable and defensible**, and so the highest-signal, highest-risk pieces (vol surface, autocallable MC, AAD, P&L explain) come early enough to fail and recover. Assume ~12–15 focused hrs/week.

### Guiding principle: vertical slices, not horizontal layers
Do **not** build all of L1, then all of L2, etc. Build a thin vertical slice end-to-end first (data → surface → price one product → one Greek → one report), then deepen. You want a working autocallable price in Week 4, not Month 4.

### MVP definition (end of Month 3) — "defensible core"
A working pipeline that: ingests real NSE data → builds an arbitrage-free SSVI surface → prices a NIFTY autocallable by Monte Carlo → computes its Greeks by bump **and** pathwise/AAD (cross-checked) → solves a coupon to par → renders a term sheet. One underlying, one flagship product, done *correctly*. **If you only finish the MVP, you still have an interview-winning project.**

### Advanced definition (end of Month 6) — "desk twin"
MVP + LSV + model reserves + a virtual book of N notes replayed over history + dynamic hedging sim + daily P&L attribution + stress testing + dashboard. This is the full digital twin.

---

### Month 0 — Foundations (Week 0, ~1 week)
- Repo, `pyproject.toml`, CI (pytest on push), `core/` types, the in-process event **bus**, provenance tagging.
- README with the **scope-contract table** filled in (all REAL/FAITHFUL/STUBBED/SKIPPED guesses).
- First ADR: "Market Snapshot as the central immutable abstraction."
- **DoD:** `pip install -e .` works; one trivial test green; bus passes a message.

### Month 1 — Data + Vol surface + BS (Weeks 1–4): **the foundation slice**
- **W1 — Ingestion:** NSE F&O + cash bhavcopy downloader → raw parquet; yfinance fallback; FBIL rate curve. Calendar + corporate-action adjustment.
- **W2 — Curation + IV inversion:** BS Newton/Brent inversion of settlement prices → historical IV points. Build & freeze the first `MarketSnapshot`. *This unlocks everything.*
- **W3 — SVI + arbitrage:** per-slice SVI calibration; Durrleman butterfly check; basic repair. Plot a clean smile vs raw points.
- **W4 — SSVI + Dupire + BS pricer:** SSVI surface (calendar-arb-free); Dupire local vol from the parametrisation; analytic BS/digital/barrier closed forms (your MC benchmarks).
- **DoD:** given any historical date, produce an arbitrage-free surface and price a vanilla three ways agreeing to 1e-6; arbitrage tests pass as property-based tests.

### Month 2 — DSL + Monte Carlo + the flagship product (Weeks 5–8)
- **W5 — Payoff DSL:** primitives + payoff DAG + evaluator. Compose vanilla, digital, single barrier; test against closed forms.
- **W6 — MC core:** RNG (Sobol + antithetic + Brownian bridge), GBM/LV path generator, control-variate variance reduction. Convergence study (MC → closed form as paths↑) as a notebook + test.
- **W7 — Autocallable + Phoenix:** compose Autocall + MemoryCoupon + KnockIn; price by MC; reproduce known qualitative behaviours (coupon ↑ as KI ↓). Add BRC, reverse convertible, capital-protected note.
- **W8 — Correlation + worst-of:** historical/EWMA/implied correlation, Higham PSD repair, Gaussian + t copula, correlated multi-asset paths; price a 3-name worst-of autocallable.
- **DoD:** flagship NIFTY autocallable prices stably; worst-of basket prices with correlated MC; every product traces back to DSL primitives.

### Month 3 — Greeks + Structurer + MVP wrap (Weeks 9–12)
- **W9 — Bump & pathwise Greeks:** full Greek set via CRN bump; pathwise for the smooth parts; vega ladders + bucketed reports.
- **W10 — LR + AAD:** likelihood-ratio for digital/barrier deltas; hand-rolled AAD tape on the autocallable to *own the adjoint*; then JAX for breadth. Cross-check AAD vs bump vs pathwise agree (a headline test).
- **W11 — Structurer Workstation:** price-to-par 1D solver (Brent); objective→structure proposer; "I want 12%" → solved KI.
- **W12 — Documentation engine + MVP demo:** term-sheet render, scenario-at-maturity table, factsheet. **Record a 5-minute MVP demo.** Refresh the scope-contract table to reality.
- **DoD = MVP:** the full Month-3 vertical slice runs end to end; AAD/bump/pathwise agree; you can defend every box. **Ship this. Put it on the CV now.**

### Month 4 — Models + Backtesting (Weeks 13–16)
- **W13 — Heston:** characteristic function + Carr-Madan FFT vanilla pricer; QE simulation scheme; calibrate Heston to the surface.
- **W14 — LSV:** leverage-function calibration (particle/binning) so LSV reprices the vanilla surface; validate the repricing. *Port from ESP.* (Highest-risk advanced item — buffer time here.)
- **W15 — Backtesting engine:** rolling monthly issuance 2015→2025 on realised paths; autocall-frequency, loss, tail distributions; survivorship-bias controls.
- **W16 — Backtest analysis:** stress-window performance; the "looks great until the tail" story written up.
- **DoD:** LSV reprices vanillas to tolerance; a 10-year rolling Phoenix backtest produces credible, bias-controlled distributions.

### Month 5 — Book + Hedging + Attribution + Model risk (Weeks 17–20)
- **W17 — Virtual book:** generate N notes; replay engine producing daily marks + Greeks across the book; netting/aggregation.
- **W18 — Hedging engine:** dynamic delta (+ vega) hedge sim over history; slippage, gap loss; hedging-P&L distribution.
- **W19 — P&L attribution:** daily Taylor explain (delta/gamma/theta/vega/vanna/volga/corr) + residual vs full reval. *This is the single most impressive desk-realism feature — invest in it.*
- **W20 — Model risk engine:** LSV−LV reserve across the book; param-uncertainty + bid-offer reserves; reserve dashboard data.
- **DoD:** replay a book over a historical window with daily P&L explain whose residual is demonstrably small; model reserves computed book-wide.

### Month 6 — Stress + Dashboard + polish (Weeks 21–24)
- **W21 — Stress testing:** coherent multi-factor scenarios + historical replays; per-product and per-risk-factor decomposition.
- **W22 — Dashboard:** Streamlit desk blotter — NAV, P&L explain, Greeks, reserves, concentrations, stress. Drill-into-trade.
- **W23 — C++/GPU demonstrator:** port the MC path+payoff kernel to C++ (pybind11), measure & quote the speedup; (GPU via JAX if hardware). Write the ADR.
- **W24 — Documentation + narrative:** finalise this design doc, the ADRs, the `interview_defense.md`, and a polished README with architecture diagram and a 8–10 min demo video. Final scope-contract pass.
- **DoD = Advanced:** the full digital twin demos end to end from one screen.

### If you fall behind (triage order — protect these)
Keep, in priority order: **(1)** arbitrage-free surface, **(2)** autocallable MC price, **(3)** AAD/pathwise Greeks cross-checked, **(4)** P&L attribution with residual, **(5)** model reserve LSV−LV. These five are what get discussed in interviews. Drop, if needed: full GPU, the React dashboard (keep Streamlit), the breadth of product catalog (keep autocallable + BRC + worst-of), multi-name beyond 3.

---

## 9. Recruiter-facing project narrative

**One-liner (CV):**
> Built a structured-products desk "digital twin": a modular platform that structures, prices (BS/LV/Heston/LSV), risk-manages, hedges, and attributes P&L for equity exotics (autocallables, Phoenix, BRCs, worst-of) on Indian markets — with AAD Greeks, model-reserve computation, historical backtesting, and a desk dashboard, on free NSE data.

**The three things to lead with (in this order):**
1. **It's a desk, not a pricer.** Most candidates show a Heston calibration. You show the *workflow* — structurer → trader → risk → model validation → hedging — integrated, with historical replay and daily P&L explain. That's the differentiator.
2. **The hard quant is real and cross-checked.** SSVI with arbitrage repair; LSV calibrated to reprice the surface; AAD giving all Greeks at a constant multiple of one price, validated against bump and pathwise; the LSV−LV model reserve.
3. **You know your edges.** The scope-contract table. You can say precisely what's production-faithful vs scoped, which is a senior signal.

**The 90-second version for a screen:**
> "I noticed student exotics projects stop at pricing one product. A real desk is a system — someone structures it to par for a client, a trader books and hedges it, risk explains the daily P&L, model validation holds a reserve for the LSV-vs-local-vol gap. So I built the whole loop as a modular platform on free NSE data, since I can't pay for a vol feed. The interesting engineering was reconstructing historical implied-vol surfaces by inverting F&O settlement prices from bhavcopy — that gave me a real surface time series to backtest on. The interesting quant was getting LSV to reprice the vanilla surface and then watching it disagree with local vol on autocallables by enough to matter — which is exactly the model reserve a desk would hold."

**Your EI-engineering angle (underused — use it here):** signal processing and control systems map directly to this domain. Frame it: *"My EI background is why the surface/filtering and the dynamic-hedging-as-feedback-control parts came naturally — a delta hedge is a control loop tracking a moving target, hedging error is tracking error, and surface construction is a regularised inverse problem."* This turns a non-CS/non-finance degree into a distinctive strength rather than a gap.

**Tailoring:**
- *Structuring/exotics desks:* lead with the Structurer Workstation + DSL + price-to-par.
- *Quant research:* lead with SSVI/LSV calibration + the model reserve.
- *Quant dev:* lead with the architecture, AAD, the C++ kernel + speedup, reproducible snapshots.
- *Risk/XVA (your XVA engine's natural sibling):* lead with P&L attribution, stress testing, and reserves — and explicitly position SPDT + the XVA engine as "the trading side and the counterparty-risk side of the same book."

---

## 10. Interview-defense appendix (your real deliverable)

Collect every "**You must be able to defend**" box above into `docs/interview_defense.md` and rehearse them out loud from first principles. The honest risk on a project this broad is that you can *run* it but not *derive* it. The questions you will actually get:

- Derive the pathwise delta estimator and prove it's unbiased; now explain why it fails for a digital and how LR fixes it.
- Why does AAD give all sensitivities at ~constant cost regardless of input count? (Reverse-mode chain rule.)
- SVI vs SSVI — what arbitrage does each control, and how do you detect butterfly arbitrage?
- Why do LV and LSV agree on vanillas but disagree on autocallables? (Same marginals, different dynamics/forward smile.) What is the resulting reserve *for*?
- Why is the QE scheme used for Heston instead of Euler?
- What is the LSV leverage-function calibration identity and what does the conditional expectation represent?
- Walk me through your daily P&L explain — what does a large residual tell you?
- Why must stress scenarios be coherent across spot/vol/correlation?
- Why is an autocallable desk structurally short vol and short gamma near the barrier, and where does it lose money?

**Build a one-page derivation card for each.** Knowing these cold is worth more than any extra feature.

---

## 11. Honest closing assessment

- **Single most valuable, most overlooked piece:** the bhavcopy → IV-surface reconstruction. It's the thing that makes the whole project possible on free data, it's a genuine bit of engineering, and it's a great story. Get it working in Week 2 and the rest has a foundation.
- **Highest-risk piece:** LSV calibration (W14). Budget slack. If it slips, ship MVP + Heston + reserves-vs-Heston and declare LSV as in-progress — still strong.
- **The trap:** breadth over depth. A correct autocallable with bulletproof, cross-checked Greeks and a clean P&L explain beats twelve half-working product types. Resist the catalog.
- **The multiplier:** you already have the XVA engine and the ESP design. SPDT is the integrating frame. Presented together — "I built the counterparty-risk side (XVA), the structuring side (ESP), and the trading-desk twin that ties them together (SPDT)" — that's not a student portfolio, that's a coherent thesis about how a derivatives business works.

*Version 1.0 — living document. Update the scope-contract table as buckets change; add an ADR for every non-obvious decision.*
