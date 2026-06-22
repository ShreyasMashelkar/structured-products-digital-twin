# SPDT Architecture

This is the trimmed architecture reference. The full design specification and build
roadmap live in [`../SPDT_Design_and_Build.md`](../SPDT_Design_and_Build.md).

## The spine

The architecture mirrors the **people and workflow** of a real desk. A trade flows:

```
CLIENT → STRUCTURER (L6) → TRADER: Pricing (L4) + Greeks (L5) → books into Virtual Book (L8)
       → RISK MGR: reports (L5) + Stress (L12) + P&L Attribution (L10)
       → MODEL VAL: Model Risk (L11) → HEDGING (L9)
       → HISTORY: Backtesting (L7) + Replay (L1) feed it all
       → XVA/CCR DESK: exposure seam → CVA/FVA/KVA/MVA → all-in price → governance (see below)
```

Three foundational services everyone consumes: **Market Data (L1)**, **Volatility
Analytics (L2)**, and the **Product Definition DSL (L3)**.

## Central abstraction: the Market Snapshot

An immutable, versioned, content-hashed object representing "the market as of date D":
spot levels, calibrated vol surface(s), correlation matrix, two bootstrapped rate
curves (OIS/risk-free + issuer funding), dividend schedule, and per-field provenance
tags. Every other layer takes a snapshot as input and never touches raw data. Rates
are bootstrapped term structures, never assumed flat: the OIS curve sets the
risk-neutral drift and discounts the option leg; the funding curve (OIS + issuer
spread) discounts the note's zero-coupon-bond leg.

## No monolith without microservice theatre

- Each layer is a Python package with a clean, typed public API (`Protocol`/ABC).
- Layers communicate through an in-process event bus (`spdt/core/bus.py`) whose
  interface is message-shaped — swappable for Kafka/Redis Streams without touching
  business logic.
- One layer may later be lifted into its own process behind the same API to prove the
  boundary is real. This is the honest version of "modular services": real boundaries,
  deferred distribution.

## Market-data sources (L1)

Three interchangeable sources sit behind one `fetch() → RawMarketData` seam, so the
whole stack is source-agnostic:

- **Synthetic** (default) — a generated spot + smile; deterministic, so tests, the case
  study and CI are reproducible.
- **NSE bhavcopy** (`SPDT_LIVE=1`) — the public **EOD** F&O file; walks back to the latest
  *published* file, so it works any time of day (mid-session it serves the previous close).
- **Dhan** (`SPDT_SOURCE=dhan`) — DhanHQ's authenticated **intraday** option-chain API; a
  broker feed, so it isn't IP-blocked like the public NSE endpoints.

Rates always bootstrap from **FBIL** (India's OIS benchmark). NSE blocks public *scraping*,
so the reliable free live path is EOD bhavcopy; Dhan is the keyed route for true intraday.

## The XVA / CCR seam (two desks, one core)

A vendored INR OTC / CCR / XVA engine (`xva/`) is combined with SPDT as **two desks over one
shared core**, coupled at exactly one place — the **exposure/position seam** — so the two
product models never have to be unified ([ADR-0007](adr/0007-integrate-xva-at-the-exposure-seam.md)).

- The seam is one artefact, `ExposurePackage` (a path × time NPV cube + curves + counterparty),
  produced by SPDT's Monte Carlo (mark-to-future, via Longstaff–Schwartz for path-dependent
  notes) and consumed by the XVA stack.
- `integration/` is the **only** package allowed to import both worlds; it *reuses* the engine's
  `CVAEngine` / `KVAEngine` / `MVAEngine` / `CSAEngine` / `BACVAEngine` rather than reimplementing.
- The journey: `position → exposure → [netting · CSA/MPoR collateral · wrong-way tilt] →
  CVA + FVA + KVA + MVA − DVA → all-in price → EAD/PFE + economic & regulatory capital +
  CS01/JTD/stress → RAROC governance gate → React desk tab`.

Full narrative with numbers: [`PROJECT_WALKTHROUGH.md`](PROJECT_WALKTHROUGH.md) ·
[`xva_case_study.md`](xva_case_study.md).

See [`adr/`](adr/) for Architecture Decision Records, one per non-obvious choice.
