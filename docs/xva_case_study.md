# XVA case study — one note, term sheet → all-in price → governance

A single worked example through the whole `position → exposure → XVA → price → decision` chain (ADR-0007), with the **actual numbers** the platform produces. Reproduce it from `integration/` directly; the figures below are from a 20k-path run (seed-fixed, so they're stable to the third significant figure).

## The trade

A 2-year INR **memory autocallable** on NIFTY, struck at spot:

| Term | Value |
|---|---|
| Notional | 100 (par) |
| Observation dates | 0.5, 1.0, 1.5, 2.0y |
| Autocall level | 100% |
| Coupon barrier | 80% |
| Knock-in | 60% |
| Memory coupon | yes |
| Model | Black–Scholes, σ = 22%, r = 6%, q = 0 |
| Counterparty | 300bp CDS, 40% recovery |
| Issuer (for DVA) | 120bp CDS |
| Placement fee | 1.0 |

## 1 — Mark-to-future exposure

The note is simulated and repriced on every path at every observation; the path-dependent value is the Longstaff–Schwartz continuation value (so EE isn't biased up by Jensen). The expected-exposure profile **builds, then collapses at each autocall date** as redeemed paths leave the book.

| Metric | Value | Meaning |
|---|---|---|
| Peak EE | 101.8 | largest expected positive exposure |
| EPE | 51.3 | time-averaged EE |
| EEPE | 101.1 | effective EPE (Basel 1y-capped window) |
| Peak PFE (95%) | 105.7 | tail exposure |
| **EAD** = α·EEPE | **141.6** | economic exposure-at-default (α = 1.4) |

## 2 — The XVA charge

`total = CVA + FVA + KVA + MVA − DVA`, in note-currency units:

| Component | Value | Source |
|---|---|---|
| CVA | 2.78 | EE × counterparty default prob × discount |
| FVA | 0.45 | funding the EPE at +50bp |
| KVA | 1.69 | 12% cost of capital on the EAD profile |
| MVA | 0.14 | funding 99%/10-day initial margin |
| DVA | 0.00 | a long note has one-sided exposure → no own-default benefit |
| **Total XVA** | **5.06** | |

## 3 — Capital & XVA risk

| Measure | Value | Note |
|---|---|---|
| Economic capital (ASRF 99.9%) | 22.1 | from the CDS-implied PD/LGD |
| Regulatory EAD (equity SA-CCR) | 183.5 | 32% supervisory factor, RC + PFE add-on |
| Regulatory CVA capital (BA-CVA) | 3.14 | RW 12% (corporate IG) |
| CS01 (ΔCVA / +1bp) | 0.009 | the CVA desk's hedge ratio |
| Jump-to-default (net of CVA) | 56.7 | immediate-default loss beyond the reserve |

## 4 — The all-in price

The structurer solves the coupon to `par − fee`, then to `par − fee − XVA`:

| Coupon (annualised) | Value | |
|---|---|---|
| To par (no XVA) | **7.25% p.a.** | the naïve quote |
| All-in (net of XVA) | **1.09% p.a.** | what the desk can honestly offer to a 300bp counterparty |

Carrying the lifetime counterparty, funding, capital and margin cost cuts the offerable coupon by **~6 points (615bp)** — and it falls further as the counterparty's spread widens. *This is the headline of the combined platform.* (Figures are annualised; `coupon_rate` is per-observation × 2 obs/year. Numbers reflect the full `CVA+FVA+KVA+MVA` charge above — the desk's default tab shows CVA+FVA only, a milder drop, until you switch KVA/MVA on.)

## 5 — The governance decision

Against a 200 EAD limit and a 10% RAROC hurdle, with a 1.0 structuring margin:

> **Decision: MANUAL_REVIEW** — *"Standalone RAROC below hurdle."* (trade RAROC ≈ −10%)

The 1.0 margin doesn't cover the 5.06 all-in charge, so the trade can't clear the hurdle on its own. Widen the margin or tighten the counterparty and it flips to **APPROVED**; breach the EAD limit and it flips to **REJECTED**. That decision logic mirrors the bank's trade-approval workflow, fed entirely from the exposure seam.

---

*Run it live:* the **Counterparty & XVA** tab on the React desk (`webapp/`) exposes every knob above — counterparty/own CDS, funding, cost of capital, MVA, wrong-way β, collateral — and updates the charge breakdown, the capital comparison and the CVA stress ladder in real time.
