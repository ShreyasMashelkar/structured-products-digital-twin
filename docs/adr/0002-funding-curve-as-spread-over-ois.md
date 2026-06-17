# ADR 0002 — Issuer funding curve modelled as a spread over OIS

## Status
Accepted

## Context
Every `MarketSnapshot` carries two bootstrapped rate curves: an **OIS / risk-free
curve** (sets the risk-neutral drift `(r−q)` and discounts the option leg) and an
**issuer funding curve** that discounts the note's zero-coupon-bond leg, because a
structured note is the issuer's debt (see interview defense §XI.8).

There are two ways to build the funding curve:

1. **Direct bootstrap** from the issuer's own traded bonds/notes — a standalone
   discount curve, built exactly like OIS.
2. **Spread over OIS** — `funding = OIS + s(T)`, where `s(T)` is a credit/funding
   spread term structure calibrated to whatever issuer reference points exist. (OIS is
   still fully bootstrapped; only the spread's degrees of freedom are added on top.)

Our data sources (NSE F&O + cash bhavcopy, FBIL/RBI) yield a clean OIS/T-bill curve but
**no dense, liquid issuer bond curve**. Indian corporate/bank secondary bond marks are
sparse and stale.

## Decision
Model the funding curve as a **spread over OIS**, with the spread itself a **small
parametric term structure** (piecewise-linear, 2–3 knots, or a level/slope form) — *not*
a single flat spread. Calibrate `s(T)` to whatever issuer reference is available (primary
issuance spread, a benchmark bank-bond spread index, or CDS where it exists).

## Consequences
- **Robust under sparse data.** Inherits OIS's well-behaved shape; a 2–3-point issuer
  set can pin a spread but cannot stably bootstrap a full curve. Preserves the snapshot's
  content-hashed reproducibility (no day-to-day jitter from noisy bond marks).
- **Coherent rate risk.** A rate move propagates through both curves automatically; no
  spurious OIS-vs-funding basis from two independently bootstrapped curves.
- **Spread is a first-class, shockable factor.** Directly supports the structuring
  economics (wider spread → cheaper ZCB leg → more optionality budget) and the stress
  layer ("issuer spread +50bp"). Direct bootstrap would bury the spread inside discount
  factors.
- **Scales across issuers** — one spread curve per issuer.
- **Cost / limitation.** Assumes a simple spread shape; a genuinely non-parallel issuer
  term structure is approximated. Acceptable for cost decomposition and risk; we would
  switch to a **direct bootstrap only given a liquid issuer bond/CDS curve** with reliable
  EOD marks (the "with bank infrastructure" answer, cf. §XII.1).
