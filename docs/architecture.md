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
```

Three foundational services everyone consumes: **Market Data (L1)**, **Volatility
Analytics (L2)**, and the **Product Definition DSL (L3)**.

## Central abstraction: the Market Snapshot

An immutable, versioned, content-hashed object representing "the market as of date D":
spot levels, calibrated vol surface(s), correlation matrix, rate curve, dividend
schedule, and per-field provenance tags. Every other layer takes a snapshot as input
and never touches raw data.

## No monolith without microservice theatre

- Each layer is a Python package with a clean, typed public API (`Protocol`/ABC).
- Layers communicate through an in-process event bus (`spdt/core/bus.py`) whose
  interface is message-shaped — swappable for Kafka/Redis Streams without touching
  business logic.
- One layer may later be lifted into its own process behind the same API to prove the
  boundary is real. This is the honest version of "modular services": real boundaries,
  deferred distribution.

See [`adr/`](adr/) for Architecture Decision Records, one per non-obvious choice.
