# SPDT — Project Walkthrough & Talk Track

How to explain this project to someone — from a client's need to the end of the XVA journey. Layered so you can scale from a 30-second pitch to a deep technical dive. A single trade is threaded through the whole thing so it stays concrete: a **2-year NIFTY memory autocallable** faced against a corporate counterparty at a **300bp CDS spread**. The numbers are real — see [`xva_case_study.md`](xva_case_study.md).

---

## Part A — The talk track (rehearse these)

### 🎯 30-second elevator
> "I built a digital twin of an equity structured-products desk **and** its counterparty-risk function. On real Indian market data, it takes a client brief, structures and prices an exotic autocallable, then runs it through the full XVA stack — CVA, FVA, KVA, MVA — to produce an *all-in* price and an automated trade-approval decision. The headline: the same note's coupon drops from **3.6% to 0.5%** just from the counterparty's credit quality, and the platform shows you exactly why."

### 🎯 2-minute version
Three beats:
1. **The thesis** — two desks (structuring + XVA/CCR) over one shared core, coupled at a single seam (the exposure cube), so the two product models never have to merge.
2. **The journey** — client need → propose structure → price → solve coupon to par → **mark-to-future exposure** → CVA/FVA/KVA/MVA → **all-in price** → economic & regulatory capital → governance decision.
3. **The killer number** — coupon 3.62% → 0.55% under a 300bp counterparty; widen the spread and it falls further. The platform makes "who you trade with changes the price" explicit.

### 🎯 Deep-dive (technical interview)
Walk Part B, but spend your time on the three things that signal seniority:
1. **The seam decision** (ADR-0007) — *why* coupling at exposure, not the product model, is correct architecture.
2. **Mark-to-future exposure** — Longstaff–Schwartz continuation value, and the autocallable EE that **collapses on each autocall date**.
3. **The all-in price** — how XVA folds back into the structurer's par-solve.

### Slide / whiteboard outline (7 panels)
1. Two desks, one seam (the diagram in the README).
2. Client brief → proposed Phoenix autocallable.
3. MC price → solve coupon to par (3.62%).
4. The exposure cube → EE profile (the autocall-collapse chart).
5. The XVA waterfall: CVA + FVA + KVA + MVA − DVA = 5.06.
6. All-in coupon 3.62% → 0.55%; capital economic vs regulatory.
7. Governance gate → APPROVED / REJECTED / MANUAL_REVIEW.

### Two reflexes that win interviews
- **Always anchor on the running example.** "Let me walk you through one autocallable…" beats abstraction every time.
- **Welcome the "what's simplified?" question.** You have a *declared* scope contract (flat funding curve, parametric WWR, no full FRTB-CVA, single-counterparty). Naming limits precisely is what separates understanding from copying.

---

## Part B — The end-to-end journey (the detailed version)

### The thesis: two desks, one seam
A bank has two groups that both touch the same trade — the **structuring desk** (prices & hedges the note) and the **XVA/CCR desk** (charges it for default, funding and capital cost). In the project these are two codebases (SPDT + a vendored XVA engine) that talk through **exactly one object — the exposure cube** — and nothing else (ADR-0007). The structuring desk *produces* it; the XVA desk *consumes* it. That seam is the whole story.

### Stage 0 — Market data foundation (a real, 3-way pipeline)
Everything starts from a versioned `MarketSnapshot`: spot, an OIS discount curve, and an **arbitrage-free implied-vol surface** (SVI/SSVI + arbitrage repair). The data behind it comes from three interchangeable sources, all behind one `fetch() → RawMarketData` seam:

```
                       ┌──────────── option chain + spot ────────────┐
 Synthetic  (default) ─┤ generated smile (~24,100)  ·  reproducible   │
 NSE bhavcopy (LIVE)  ─┤ real EOD chain (~1,800 legs, walks back to   │ ──► RawMarketData ──► MarketSnapshot
 Dhan API   (LIVE)    ─┤ latest published) · intraday via broker token│        (+ FBIL OIS rates)        │
                       └──────────────────────────────────────────────┘                                  ▼
                                                                              arb-free SSVI surface · two-curve discounting
```

- **Synthetic** (default) — a generated spot + smile; **deterministic**, so tests, the case study and CI are reproducible.
- **NSE bhavcopy** (`SPDT_LIVE=1`) — the real public **EOD** F&O file; walks back to the latest *published* file, so it works any time of day (mid-session it serves the previous close — settlement marks).
- **Dhan** (`SPDT_SOURCE=dhan`) — DhanHQ's authenticated **intraday** option-chain API; a broker feed, so it isn't IP-blocked like the public NSE endpoints.

Rates always bootstrap from **FBIL** (India's OIS benchmark). *Snapshot in, report out* — every layer consumes an immutable snapshot, which is what makes reproducible pricing and historical replay possible. (Engineering note worth telling: NSE blocks public *scraping*, so the reliable free live path is EOD bhavcopy; Dhan is the keyed route for true intraday — bhavcopy is the better default, Dhan only when real-time matters.)

### Stage 1 — The client need
A private-bank client: *"~12% annual income, can stomach a 30% drop, 2-year horizon."* That's a **client brief**.

### Stage 2 — Propose a structure
The **structurer** maps the brief to a **Phoenix autocallable** — memory coupon above a barrier, early redemption ("autocall") above 100%, capital at risk only if a 60% knock-in breaks. The client is effectively *selling a deep down-and-in put*, and that premium funds the coupon.

### Stage 3 — Price it
**Monte Carlo** under the desk model (BS here; also Heston / local vol / LSV). Path-dependent features (autocall, memory, knock-in) evaluated path by path; **two-curve discounting** (OIS for the option leg, OIS+funding for the issuer leg).

### Stage 4 — Solve to par
"Fair" means model PV = issue price − fee. Hold every client term fixed and **solve the coupon** (1-D Brent root find) so `PV = 100 − fee`. → **3.62% p.a.** — the naïve quote.

### Stage 5 — Greeks & risk
Sensitivities by **bump, pathwise, and AAD** (cross-checked), bucketed vega, model reserves (LSV−LV), stress, hedging simulation. The mature structuring half — one line in a pitch, not the differentiator.

> **↓ The trade now crosses the seam into the XVA / CCR world ↓**

### Stage 6 — The seam: mark-to-future exposure
The XVA desk needs: *on every future path, at every future date, what's this worth — so how much could the counterparty owe me if they default?* SPDT produces an **`ExposurePackage`**: a `paths × time` NPV cube + curves + counterparty. Path-dependent value uses **Longstaff–Schwartz** regression (continuation value, avoiding the Jensen up-bias of realised cashflows). The **expected-exposure (EE) profile builds, then collapses at each autocall date** as redeemed paths leave the book — the recognizable CCR signature of an autocallable.

### Stage 7 — CCR metrics
From the cube: **EE / EPE / EEPE** (Basel 1y-capped) / peak **PFE** (95%) / **EAD = α·EEPE** (α = 1.4) → ≈ **142**.

### Stage 8 — The XVA charge (cost of doing this trade with this counterparty)
- **CVA** — expected counterparty-default loss → **2.78**
- **FVA** — funding the exposure at the issuer spread → **0.45**
- **KVA** — cost of holding regulatory capital over the life → **1.69**
- **MVA** — funding initial margin (99% / 10-day) → **0.14**
- **DVA** — mirror benefit from own default → **0** (a long note is one-sided)
- → **Total XVA ≈ 5.06**, convention `CVA + FVA + KVA + MVA − DVA`.

### Stage 9 — CCR overlays (how a desk reduces the charge)
- **Netting** — offsetting trades cancel *before* exposure is taken.
- **Collateral (CSA)** — variation margin with threshold/MTA; only the **close-out gap over the MPoR** survives.
- **Wrong-way risk** — exposure tilted to be high *when the counterparty defaults*.

### Stage 10 — The all-in price (the punchline)
Fairness becomes **`PV = par − fee − XVA`**, and the coupon is re-solved against the lower target → **3.62% → 0.55% p.a.** for our 300bp counterparty (and lower still as the spread widens). *The same note pays a different coupon depending on who you trade it with — and the platform makes that explicit.*

### Stage 11 — Capital, two ways
**Economic** (ASRF unexpected loss, 99.9% ≈ 22) and **regulatory** (**BA-CVA** capital ≈ 3.1, **equity SA-CCR EAD** ≈ 184). Economic *and* regulatory side by side is how a real CCR desk thinks.

### Stage 12 — XVA risk (what the CVA desk hedges daily)
**CS01** (ΔCVA per +1bp — the hedge ratio), **jump-to-default** (immediate-default loss net of reserve), and a **credit-stress ladder**.

### Stage 13 — Governance gate (should we do this trade?)
Mirrors a bank's trade-approval workflow: check **EAD/PFE vs limits** and **RAROC vs hurdle** → **APPROVED / REJECTED / MANUAL_REVIEW** with reasons. Our example: a thin 1.0 margin can't cover the 5.06 charge → **MANUAL_REVIEW**. Widen margin → APPROVED; breach a limit → REJECTED.

### Stage 14 — The desk UI
A React trading desk with a "Counterparty & XVA" tab: pick a note, dial counterparty CDS / funding / cost-of-capital / collateral, and watch the charge breakdown, capital, CS01/JTD, exposure profile and CVA-vs-spread curve update live, ending in the governance verdict — running against synthetic, EOD (bhavcopy), or live intraday (Dhan) data (the masthead shows the data date with an **EOD** badge when it lags).

---

## The architecture / engineering story (if they push on craft)
- **One seam, enforced.** `integration/` is the *only* package allowed to import both worlds; the boundary is real, not aspirational.
- **Reuse over rebuild.** The integration layer wires the vendored engine's `CVAEngine` / `KVAEngine` / `MVAEngine` / `CSAEngine` / `BACVAEngine` rather than reimplementing them — it owns the *seam*, not the analytics.
- **Honest scope.** A `REAL / FAITHFUL / STUBBED / SKIPPED` contract names exactly what's production-shaped vs simplified vs out of scope.
- **Quality gates.** ~270 tests, ~88% coverage, ruff + mypy clean across 100+ files, CI on Python *and* the frontend.

## What's deliberately out of scope (have these ready)
Jointly-simulated (vs parametric) wrong-way risk, full **FRTB-CVA** regulatory capital, term-structure funding curves everywhere, and the entire **rates/swap** asset class (Hull-White, swaptions) — all served by the vendored engine directly, not forced through the equity seam.

---

*Pointers:* architecture → [`adr/0007-integrate-xva-at-the-exposure-seam.md`](adr/0007-integrate-xva-at-the-exposure-seam.md) · worked numbers → [`xva_case_study.md`](xva_case_study.md) · run it → [`../webapp/README.md`](../webapp/README.md).
