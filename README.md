---
title: Structured Products Digital Twin
emoji: 📈
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
---

# Structured Products Digital Twin (SPDT)

> A production-shaped educational simulation of an equity structured-products desk **plus its counterparty-risk twin**: `structuring → pricing → hedging → risk → P&L attribution`, then `exposure → CVA/FVA → all-in price → governance`, built on free Indian market data.

SPDT is a modular platform that structures, prices (BS / Local Vol / Heston / LSV), risk-manages, hedges, and attributes P&L for equity exotics (autocallables, Phoenix, barrier reverse convertibles, worst-of baskets) on NSE data — with AAD Greeks, typed payoff decomposition, semi-static vanilla-strip replication, model-reserve computation, historical backtesting, and a desk dashboard.

It then couples to a separate **INR OTC / CCR / XVA engine that I built as its own project** at a single seam (the exposure cube), so a note can be priced *all-in* — coupon net of its lifetime CVA + FVA — and gated by counterparty limits, economic capital and RAROC. See [**XVA & Counterparty Credit Risk**](#xva--counterparty-credit-risk) below and [`docs/adr/0007`](docs/adr/0007-integrate-xva-at-the-exposure-seam.md).

The full design specification and week-by-week build roadmap live in [`SPDT_Design_and_Build.md`](SPDT_Design_and_Build.md). **New here? Read the [project walkthrough](docs/PROJECT_WALKTHROUGH.md)** — the end-to-end story from client need to the XVA decision, with a talk track. For the app itself, the [**user guide**](docs/USER_GUIDE.md) documents every tab with live screenshots, how to use each page, and the math behind every number.

Two rules govern everything here:

- **Faithful, not fake.** Every component is architecturally and methodologically faithful to how a real desk works, even where it is simplified.
- **The math is the asset, not the code.** Each layer must be defensible from first principles — see [`docs/interview_defense.md`](docs/interview_defense.md).

---

## Scope contract (live — update as buckets change)

| Bucket | Meaning | Examples in SPDT |
|---|---|---|
| **REAL** | Mathematically correct, production-shaped, owned end to end | SVI/SSVI calibration, autocallable MC pricing, bump/pathwise/**AAD** Greeks (cross-checked on the autocallable), P&L attribution with **bucketed vega**, **two-curve discounting**, autocallable/Phoenix/**BRC/reverse-convertible/capital-protected** catalog, **mark-to-future exposure (LSM) → CVA + FVA + KVA + MVA − DVA → all-in coupon**, **netting / CSA-MPoR collateral / dynamic IM / wrong-way-risk overlays**, **term-structure credit curves**, **CS01 / JTD / credit-stress**, **EAD/PFE/EEPE + ASRF economic capital + equity SA-CCR EAD + RAROC governance gate** |
| **FAITHFUL** | Correct method, scoped scale; a bank implementation differs in calibration depth, liquidity treatment and operational controls | LSV calibration, the payoff DSL (composable leg primitives), Heston QE + Carr–Madan FFT, BGK barrier correction, historical replay, **semi-static barrier replication** (model-calibrated liquid vanilla strip + tracking/residual-risk lifecycle), **C++ MC kernel** (one product ported, measured speedup; rest "same pattern"), the companion **XVA/CCR engine** (CVA/FVA/KVA/MVA, SA-CCR, SIMM, WWR — built separately and surfaced by SPDT only through the exposure seam); parametric (exponential-tilt) WWR vs the engine's jointly-simulated copula version |
| **STUBBED** | Architecturally present with a clean interface; placeholder implementation | GPU pricing kernels (designed-for; CPU C++ path implemented), message queue (in-process bus that *could* be Kafka) |
| **SKIPPED (declared)** | Out of scope, named explicitly | Real-time market connectivity, full **regulatory CVA capital inside the equity seam** (BA-CVA / FRTB-CVA live in the companion CCR/XVA project), a **jointly-simulated** WWR intensity inside SPDT (the seam uses a parametric tilt), the **rates/swap** asset class (Hull-White, swaptions, CCIL data — served by the companion engine directly), multi-currency/quanto at scale |

---

## Architecture (14 layers)

```
EXECUTIVE DASHBOARD (L14)
  ▲   ▲   ▲   ▲   ▲
Hedging(L9) · P&L Attr(L10) · Model Risk(L11) · Stress(L12) · Docs(L13)
                      │
            VIRTUAL TRADING BOOK (L8)
                      │
  Structurer(L6) · Backtesting(L7) · Greeks Engine(L5)
                      │
              PRICING ENGINE (L4)
                      │
  Product DSL(L3) · Vol Analytics(L2) · Market Data(L1)
```

Everything is **snapshot-in, report-out**: every layer consumes an immutable, versioned `MarketSnapshot` and never touches raw data, which is what makes historical replay and reproducible P&L attribution possible.

| Layer | Package | Responsibility |
|---|---|---|
| L1 | `spdt/data` | Ingest, clean, version, snapshot, replay market data |
| L2 | `spdt/vol` | SVI/SSVI surface, arbitrage repair, Dupire local vol, forward smile |
| — | `spdt/corr` | Correlation estimators, Higham PSD repair, copulas |
| L3 | `spdt/products` | Payoff DSL — products as DAGs of primitives |
| L4 | `spdt/pricing` | Closed-form / PDE / MC pricing under BS, LV, Heston, LSV |
| L5 | `spdt/greeks` | Bump, pathwise, likelihood-ratio, AAD |
| L6 | `spdt/structurer` | Price-to-par solver; **Originate recommender** — ranks the best-fit family across all four, then solves it to par |
| L7 | `spdt/backtest` | Rolling historical issuance, outcome statistics |
| L8 | `spdt/book` | Virtual trading book, daily marks & Greeks |
| L9 | `spdt/hedging` | Dynamic delta/vega hedge simulation, residual P&L |
| L10 | `spdt/pnl` | Daily P&L attribution (Taylor explain + residual) |
| L11 | `spdt/modelrisk` | LSV−LV reserve, parameter-uncertainty, bid-offer |
| L12 | `spdt/stress` | Coherent macro scenarios, historical replays |
| L13 | `spdt/reporting` | Term sheet / factsheet / scenario-table generation |
| L14 | `spdt/dashboard` | Executive desk blotter (Streamlit) + React desk (`webapp/`) |

### Methodology & Engine Specs

To ensure institutional fidelity, SPDT relies on industry-standard quantitative methods rather than simplified black-box approximations. The core engine specifications are:

*   **Pricing Models:** 
    *   **Local Stochastic Volatility (LSV):** Calibrated via Dupire's equation coupled with a Heston stochastic volatility process to correctly price the forward smile and barrier gap risk.
    *   **Alternatives:** Pure Black-Scholes, Local Volatility (LV), and Heston are also available and used to compute the LSV−LV model reserve.
*   **Monte Carlo Kernel:** 
    *   Implemented as a hot **C++ kernel** exposed to Python via `pybind11` for high-performance path generation.
    *   **Iterations:** Standard runs use **100,000 paths**.
    *   **Variance Reduction:** Utilizes **Sobol low-discrepancy sequences** combined with a Brownian Bridge construction.
*   **Greeks Engine:** 
    *   Computes standard bump-and-revalue (finite difference) Greeks.
    *   Implements **Adjoint Algorithmic Differentiation (AAD)** to compute all first-order sensitivities (Delta, Vega across the surface) at a constant multiple of a single pricing run.
*   **Structuring Solvers:** Uses Brent's method and Levenberg-Marquardt to solve exotic note structures to par (e.g., finding the exact coupon rate that makes PV = 0 at inception, net of XVA and fees).
*   **Multi-Asset Capabilities:** The engine is asset-agnostic. While Indian equities (NIFTY) are used for the live demo via NSE Bhavcopy, the `WorstOf` engine dynamically accepts any $N$-dimensional asset basket (e.g., US equities like AAPL, TSLA) and automatically scales the Cholesky correlation matrix.

### Decomposition and semi-static hedge lifecycle

The risk layer now turns each supported note into typed components (`funding`, `coupon`,
`vanilla`, `digital`, `barrier`, `autocall`, `correlation`) before selecting an executable hedge.
Relative contractual levels remain tied to the trade's immutable inception fixing; option hedge
weights are quantities in absolute-price units, avoiding the notional/spot scaling ambiguity that
often appears in educational implementations.

For discretely monitored down barriers, the replication engine projects the path-dependent payoff
onto a deterministic strip of European puts snapped to a listed-style strike grid, with a 5×-face
gross inventory constraint. It reports the remaining tracking error and residual cash Greeks. The
lifecycle uses the contractual observation schedule and explicit persisted barrier/unwind state—it
does not infer a historical knock-in from today's spot. Knock-outs are eligible for progressive
pre-unwind; knock-ins transition to vanilla exposure only after an observed activation event. The
React **Semi-Static Hedging** workspace consumes the same signed live book, selected trade and
simulated spot/vol as **Book & Risk**. The displayed strip is explicitly a BS indicative hedge for
the barrier component, not a claim that the entire callable note is exactly replicated.

### Outcome Lab

The React **Outcome Lab** selects an actual 2Y NIFTY autocallable from the current 15-trade
blotter (and exposes its `NOTE-*` identifier and source terms), then carries that booked payoff
through three decision-focused studies behind one `GET /api/outcomes` payload:

- a five-path synthetic regime ensemble with monthly rolling issuance, autocall, holding-period,
  loss-frequency, tail-return and cross-seed robustness ranges;
- an out-of-sample comparison of unhedged, exact terminal-KI delta, constrained semi-static and
  inventory-budgeted hybrid hedges, including P&L dispersion, expected shortfall, turnover,
  execution cost and a documented eligibility/selection rule; and
- one client re-offer case showing the 12% target, booked coupon, model-fair coupon, XVA-adjusted
  offerable coupon, target shortfall and restructuring menu alongside hedge selection,
  EAD/economic capital, RAROC and governance decision. The
  CCR exposure is explicitly to the dealer's OTC hedge counterparty, not the funded note investor.

The bundled issuance study is explicitly labelled a **synthetic regime replay**, not observed
NIFTY performance. Its series seam is replaceable with point-in-time closes; the disclosure is
shown in the UI so an illustrative student result cannot be mistaken for client performance.

### Market-data sources (L1)

Three interchangeable sources behind one `fetch() → RawMarketData` seam, so the whole stack is source-agnostic:

```
 Synthetic  (default) ─┐  generated smile · deterministic (tests/CI/case study)
 NSE bhavcopy (LIVE)  ─┼─► RawMarketData ─► MarketSnapshot ─► arb-free SSVI surface ─► everything above
 Dhan API   (LIVE)    ─┘  real EOD (walk-back) / intraday (broker token)   ▲ FBIL OIS rates
```

Synthetic is the reproducible default; `SPDT_LIVE=1` uses NSE's public **EOD bhavcopy** (walks back to the latest published file); `SPDT_SOURCE=dhan` uses DhanHQ's authenticated **intraday** API. Live rates bootstrap from **FBIL**. A local Bloomberg Terminal workbook can also be supplied with `SPDT_SOURCE=bloomberg-rates` / `SPDT_BLOOMBERG_RATES_XLSX`, but that export is treated only as a **MIFOR funding overlay** unless it contains a true MIBOR/OIS curve. See [`webapp/README.md`](webapp/README.md#data-source-env-driven).

---

## XVA & Counterparty Credit Risk

SPDT (the structuring desk) and a separately built **INR OTC / CCR / XVA engine** (`xva/`, ~12.5k LOC: CVA/FVA/KVA/MVA, SA-CCR, SIMM, wrong-way risk, economic capital) are combined as **two desks over one shared core**, coupled at exactly one place — the **exposure/position seam** — so the two product models never have to be unified ([ADR-0007](docs/adr/0007-integrate-xva-at-the-exposure-seam.md)).

> **Ownership boundary.** `spdt/` is the equity structured-products desk. `xva/` is a standalone
> INR CCR/XVA platform I built earlier and integrated here as a companion engine. The `integration/`
> package is the seam between them: SPDT produces exposure packages; the CCR/XVA engine consumes
> them for charge, capital and governance. The two product models stay deliberately separate.

```
   SPDT (equity structuring)                 companion XVA / CCR engine
 ┌───────────────────────────┐            ┌────────────────────────────┐
 │ payoff DSL · MC pricing   │            │ CVAEngine · KVA · MVA      │
 │ Heston/LSV · SSVI · AAD   │            │ CSAEngine · BA-CVA · SIMM  │
 └─────────────┬─────────────┘            └─────────────▲──────────────┘
               │  produces                              │  consumes
               │            ┌──────────────────────┐    │
               └──────────► │   ExposurePackage     │ ───┘
                            │ path × time NPV cube  │
                            │ + curves + cpty       │
                            └──────────┬───────────┘
                                       │   integration/ (the only cross-world importer)
   position → exposure → [ netting · CSA/MPoR collateral · wrong-way tilt ]
            → CVA + FVA + KVA + MVA − DVA → all-in coupon
            → EAD/PFE · economic + regulatory capital · CS01/JTD/stress
            → RAROC governance gate → React desk tab
```

The `integration/` package is the only code allowed to import both worlds. The seam is one artefact, `ExposurePackage` (a path × time NPV cube + curves + counterparty), produced by SPDT's Monte Carlo and consumed by the XVA stack. **Worked example with real numbers:** [`docs/xva_case_study.md`](docs/xva_case_study.md).

| Capability | What it does | Where |
|---|---|---|
| **Curve join** | One bootstrapped SPDT OIS curve drives XVA's `CVAEngine` directly — DFs match to 1e-8, no re-bootstrap | `integration/curve_adapter.py` |
| **Mark-to-future exposure** | Position NPV on every path at every future time. European is exact BSM; path-dependent notes use **Longstaff–Schwartz** continuation-value regression (so EE avoids the Jensen bias), and an **autocallable's EE collapses on each autocall date** as redeemed paths leave the book | `integration/exposure_export.py` |
| **All-in price** | Folds the XVA into the structurer's solve: fairness becomes `PV = par − fee − XVA`, so the offered coupon falls as the counterparty's spread widens. The full charge is **`CVA + FVA + KVA + MVA − DVA`** — unilateral CVA+FVA by default, with **bilateral DVA**, lifetime **KVA**, **MVA** (funding of initial margin) and a **wrong-way-risk** tilt as opt-in knobs | `integration/all_in_price.py` |
| **CCR metrics** | EE / EPE / **EEPE** (Basel one-year-capped window) / peak **PFE** / **EAD = α·EEPE** read off the cube; **ASRF economic capital**; plus a regulatory **SA-CCR EAD** with the Basel **equity** supervisory factors | `integration/governance.py`, `integration/xva_risk.py` |
| **Exposure overlays** | **Netting-set** aggregation (NPVs net on common paths before exposure is taken), **CSA collateral** (threshold / MTA / **MPoR** close-out gap), **dynamic initial margin** (99% MPoR move → the MVA driver), and a **wrong-way-risk** tilt | `integration/ccr_overlays.py` |
| **Term-structure credit** | Bootstrap a piecewise-hazard credit curve from CDS **tenors** (not a single flat spread); drops into the charge, capital and gate unchanged | `integration/credit.py` |
| **XVA risk** | **CS01** (the CVA desk's hedge ratio, by bump & revalue), **jump-to-default**, and a **credit-stress ladder** of the charge | `integration/xva_risk.py` |
| **Governance gate** | Mirrors the bank's trade-approval logic — limit check on EAD/PFE + **RAROC** vs hurdle → **APPROVED / REJECTED / MANUAL_REVIEW** — fed from the exposure seam, reusing the engine's `LimitEngine` / `RAROCEngine` / `EconomicCapitalEngine` | `integration/governance.py` |
| **Desk tab** | A "Counterparty & XVA" React workspace + `POST /api/xva`: dial counterparty CDS / recovery / funding / hurdle / margin / EAD limit and watch the decision, charge, exposure profile and CVA-vs-spread curve update live | `webapp/` |

**Honest scope.** The seam now prices the full **`CVA + FVA + KVA + MVA − DVA`** suite and supports **netting**, **CSA/MPoR collateral**, **dynamic IM**, **term-structure credit curves**, **CS01 / JTD / stress** and a regulatory **equity SA-CCR EAD**. Deliberately still owned by the companion CCR/XVA project rather than SPDT's equity seam: **regulatory CVA capital** (BA-CVA / FRTB-CVA), a **jointly-simulated** WWR intensity (vs the parametric tilt here), and the entire **rates/swap** world (Hull-White, swaptions, CCIL/RBI data) — a different asset class the engine serves directly. Naming exactly what's in vs. out is the point (see the two rules above).

---

## Getting started

```bash
# editable install with dev tools
pip install -e ".[dev]"

# run the tests
pytest

# run the companion XVA engine's own suite
pytest xva/tests

# the same quality gates used by CI
ruff check spdt integration webapp tests
mypy spdt integration webapp

# frontend type-check + production build
cd webapp/frontend && npm ci && npm run build
```

Optional extras: `pip install -e ".[ad,dashboard]"` for JAX-based AAD and the Streamlit dashboard.

To run the **React desk** (incl. the live *Counterparty & XVA* tab), see [`webapp/README.md`](webapp/README.md): `uvicorn webapp.server:app --port 8077` then `npm run dev` in `webapp/frontend`.

### Deploy (single image)

The whole desk ships as **one Docker image** ([`Dockerfile`](Dockerfile)): stage 1 builds the Vite/React frontend, stage 2 serves the built SPA *and* the FastAPI engine from one uvicorn process (same-origin `/api`) on port `7860`. This targets **Hugging Face Spaces** (Docker SDK) but runs anywhere Docker does:

```bash
docker build -t spdt . && docker run -p 7860:7860 spdt   # → http://localhost:7860
```

---

## Roadmap (high level)

- **MVP (Month 3) — "defensible core":** real NSE data → arbitrage-free SSVI surface → NIFTY autocallable priced by MC → Greeks via bump *and* pathwise/AAD (cross-checked) → coupon solved to par → term sheet rendered.
- **Advanced (Month 6) — "desk twin":** MVP + LSV + model reserves + virtual book replayed over history + dynamic hedging + daily P&L attribution + stress testing + dashboard.

See [`SPDT_Design_and_Build.md`](SPDT_Design_and_Build.md) §8 for the exact week-by-week plan.

## License

MIT
