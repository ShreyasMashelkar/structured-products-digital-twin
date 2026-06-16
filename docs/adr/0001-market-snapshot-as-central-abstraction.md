# ADR 0001 — Market Snapshot as the central immutable abstraction

## Status
Accepted

## Context
The system must support historical replay, deterministic backtesting, and reproducible
P&L attribution. These all require that "the market as of date D" be a single,
well-defined, reproducible object — not a set of ad-hoc reads against raw data scattered
through the codebase.

## Decision
Introduce an immutable, versioned `MarketSnapshot` as the unit every layer consumes:
spot levels, calibrated vol surface(s), correlation matrix, rate curve, dividend
schedule, and per-field provenance tags. Snapshots are **content-addressed** (hashed
over their inputs) so re-running a given date yields byte-identical results.

No layer above L1 touches raw data; they all take a snapshot in and emit reports out.

## Consequences
- Historical replay is a simple iterator over snapshots.
- Reproducible risk: re-running yesterday gives identical numbers ("official close").
- Provenance tags let risk reports state, e.g., "80% observed / 20% interpolated surface".
- Cost: snapshots must be built and stored per business date; curation logic lives in L1.
