# ADR 0005 — In-process event bus instead of a real message broker

## Status
Accepted

## Context
The architecture mirrors a desk's workflow — structurer → trader → risk → model validation →
hedging — and the design language is "modular services that communicate by messages." The
tempting way to demonstrate that is to stand up a real broker (Kafka / Redis Streams) and run
each layer as its own container. For a single student building a pricing/risk system, that is
**engineering theatre**: it adds weeks of infrastructure, teaches nothing about quant, and the
distributed-systems failure modes it introduces are not the point of the project.

## Decision
Communicate through a thin **in-process pub/sub event bus** (`spdt/core/bus.py`): a small class
where layers publish and subscribe to typed messages. The **interface is message-shaped** —
publish/subscribe on named topics with structured payloads — so the claim "this could be swapped
for Kafka/Redis Streams without touching business logic" is *true and checkable*, not aspirational.
Each layer remains a Python package with a clean typed public API and no cross-layer reaching into
internals; the bus is how they talk.

## Consequences
- **Real module boundaries, deferred distribution.** The boundaries that matter (typed APIs,
  message contracts, no internal reach-through) are enforced now; the distribution that does not
  matter (containers, brokers, network) is deferred without changing any business logic.
- **Deterministic and reproducible.** In-process means no network non-determinism, which keeps
  historical replay and content-hashed snapshots byte-reproducible — a hard requirement for the
  P&L attribution and reserve work.
- **Cheap to demonstrate the boundary is real.** One layer (e.g. the pricing engine) can later be
  lifted into its own process behind the same message API to prove the seam — done once as a
  demonstration, not fourteen times.
- **Cost / limitation.** No true concurrency, backpressure, or fault tolerance, and a crash takes
  the whole process down. Acceptable: this is a single-machine analytics twin, not a latency- or
  availability-critical production service. The migration path (same interface, real broker) is
  the honest "with bank infrastructure" answer.
