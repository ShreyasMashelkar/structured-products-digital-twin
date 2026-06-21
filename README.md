# Structured Products Digital Twin (SPDT)

> A complete simulation of an equity structured-products desk **plus its counterparty-risk twin**: `structuring → pricing → hedging → risk → P&L attribution`, then `exposure → CVA/FVA → all-in price → governance`, built on free Indian market data.

SPDT is a modular platform that structures, prices (BS / Local Vol / Heston / LSV), risk-manages, hedges, and attributes P&L for equity exotics (autocallables, Phoenix, barrier reverse convertibles, worst-of baskets) on NSE data — with AAD Greeks, model-reserve computation, historical backtesting, and a desk dashboard.

It then couples to a vendored **INR OTC / CCR / XVA engine** at a single seam (the exposure cube), so a note can be priced *all-in* — coupon net of its lifetime CVA + FVA — and gated by counterparty limits, economic capital and RAROC. See [**XVA & Counterparty Credit Risk**](#xva--counterparty-credit-risk) below and [`docs/adr/0007`](docs/adr/0007-integrate-xva-at-the-exposure-seam.md).

The full design specification and week-by-week build roadmap live in [`SPDT_Design_and_Build.md`](SPDT_Design_and_Build.md).

Two rules govern everything here:

- **Faithful, not fake.** Every component is architecturally and methodologically faithful to how a real desk works, even where it is simplified.
- **The math is the asset, not the code.** Each layer must be defensible from first principles — see [`docs/interview_defense.md`](docs/interview_defense.md).

---

## Scope contract (live — update as buckets change)

| Bucket | Meaning | Examples in SPDT |
|---|---|---|
| **REAL** | Mathematically correct, production-shaped, owned end to end | SVI/SSVI calibration, autocallable MC pricing, bump/pathwise/**AAD** Greeks (cross-checked on the autocallable), P&L attribution with **bucketed vega**, **two-curve discounting**, autocallable/Phoenix/**BRC/reverse-convertible/capital-protected** catalog, **mark-to-future exposure (LSM) → CVA + FVA + KVA − DVA → all-in coupon**, **netting / CSA-MPoR collateral / wrong-way-risk overlays**, **EAD/PFE/EEPE + ASRF economic capital + RAROC governance gate** |
| **FAITHFUL** | Correct method, scoped scale; real version differs only in size/optimisation | LSV calibration, the payoff DSL (composable leg primitives), Heston QE + Carr–Madan FFT, BGK barrier correction, historical replay, **C++ MC kernel** (one product ported, measured speedup; rest "same pattern"), the vendored **XVA/CCR engine** (CVA/FVA/KVA/MVA, SA-CCR, SIMM, WWR — surfaced by SPDT only through the exposure seam); parametric (exponential-tilt) WWR vs the engine's jointly-simulated copula version |
| **STUBBED** | Architecturally present with a clean interface; placeholder implementation | GPU pricing kernels (designed-for; CPU C++ path implemented), message queue (in-process bus that *could* be Kafka) |
| **SKIPPED (declared)** | Out of scope, named explicitly | Real-time market connectivity, **MVA** in the SPDT all-in charge (lives in the vendored engine), term-structure hazard/funding curves at the seam, multi-currency/quanto at scale |

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
| L6 | `spdt/structurer` | Price-to-par solver, objective → structure proposer |
| L7 | `spdt/backtest` | Rolling historical issuance, outcome statistics |
| L8 | `spdt/book` | Virtual trading book, daily marks & Greeks |
| L9 | `spdt/hedging` | Dynamic delta/vega hedge simulation, residual P&L |
| L10 | `spdt/pnl` | Daily P&L attribution (Taylor explain + residual) |
| L11 | `spdt/modelrisk` | LSV−LV reserve, parameter-uncertainty, bid-offer |
| L12 | `spdt/stress` | Coherent macro scenarios, historical replays |
| L13 | `spdt/reporting` | Term sheet / factsheet / scenario-table generation |
| L14 | `spdt/dashboard` | Executive desk blotter (Streamlit) + React desk (`webapp/`) |

---

## XVA & Counterparty Credit Risk

SPDT (the structuring desk) and a vendored **INR OTC / CCR / XVA engine** (`xva/`, ~12.5k LOC: CVA/FVA/KVA/MVA, SA-CCR, SIMM, wrong-way risk, economic capital) are combined as **two desks over one shared core**, coupled at exactly one place — the **exposure/position seam** — so the two product models never have to be unified ([ADR-0007](docs/adr/0007-integrate-xva-at-the-exposure-seam.md)).

```
position → mark-to-future exposure → XVA charge → all-in price → governance → desk tab
```

The `integration/` package is the only code allowed to import both worlds. The seam is one artefact, `ExposurePackage` (a path × time NPV cube + curves + counterparty), produced by SPDT's Monte Carlo and consumed by the XVA stack.

| Capability | What it does | Where |
|---|---|---|
| **Curve join** | One bootstrapped SPDT OIS curve drives XVA's `CVAEngine` directly — DFs match to 1e-8, no re-bootstrap | `integration/curve_adapter.py` |
| **Mark-to-future exposure** | Position NPV on every path at every future time. European is exact BSM; path-dependent notes use **Longstaff–Schwartz** continuation-value regression (so EE avoids the Jensen bias), and an **autocallable's EE collapses on each autocall date** as redeemed paths leave the book | `integration/exposure_export.py` |
| **All-in price** | Folds the XVA into the structurer's solve: fairness becomes `PV = par − fee − XVA`, so the offered coupon falls as the counterparty's spread widens. The charge is **`CVA + FVA + KVA − DVA`** — unilateral CVA+FVA by default, with **bilateral DVA**, lifetime **KVA** (cost of capital) and a **wrong-way-risk** tilt as opt-in knobs | `integration/all_in_price.py` |
| **CCR metrics** | EE / EPE / **EEPE** (Basel one-year-capped window) / peak **PFE** / **EAD = α·EEPE** read off the exposure cube; **ASRF economic capital** from the CDS-implied PD/LGD | `integration/governance.py` |
| **Exposure overlays** | **Netting-set** aggregation (NPVs net on common paths before exposure is taken), **CSA collateral** with threshold / MTA / **MPoR** close-out gap, and a **wrong-way-risk** exponential tilt — each a transform on the cube *before* the charge | `integration/ccr_overlays.py` |
| **Governance gate** | Mirrors the bank's trade-approval logic — limit check on EAD/PFE + **RAROC** vs hurdle → **APPROVED / REJECTED / MANUAL_REVIEW** — fed from the exposure seam, reusing the engine's `LimitEngine` / `RAROCEngine` / `EconomicCapitalEngine` | `integration/governance.py` |
| **Desk tab** | A "Counterparty & XVA" React workspace + `POST /api/xva`: dial counterparty CDS / recovery / funding / hurdle / margin / EAD limit and watch the decision, charge, exposure profile and CVA-vs-spread curve update live | `webapp/` |

**Honest scope.** The seam now prices a full **`CVA + FVA + KVA − DVA`** charge and supports **netting**, **CSA/MPoR collateral** and **wrong-way risk** (an exponential / Esscher tilt; the vendored engine carries fuller Gaussian-copula and stochastic-intensity WWR for its swap book). Deliberately still simplified: flat hazard/funding curves, a parametric WWR tilt rather than a jointly-simulated intensity, and **MVA** left to the engine. Naming exactly what's in vs. out is the point (see the two rules above).

---

## Getting started

```bash
# editable install with dev tools
pip install -e ".[dev]"

# run the tests
pytest
```

Optional extras: `pip install -e ".[ad,dashboard]"` for JAX-based AAD and the Streamlit dashboard.

To run the **React desk** (incl. the live *Counterparty & XVA* tab), see [`webapp/README.md`](webapp/README.md): `uvicorn webapp.server:app --port 8077` then `npm run dev` in `webapp/frontend`.

---

## Roadmap (high level)

- **MVP (Month 3) — "defensible core":** real NSE data → arbitrage-free SSVI surface → NIFTY autocallable priced by MC → Greeks via bump *and* pathwise/AAD (cross-checked) → coupon solved to par → term sheet rendered.
- **Advanced (Month 6) — "desk twin":** MVP + LSV + model reserves + virtual book replayed over history + dynamic hedging + daily P&L attribution + stress testing + dashboard.

See [`SPDT_Design_and_Build.md`](SPDT_Design_and_Build.md) §8 for the exact week-by-week plan.

## License

MIT
