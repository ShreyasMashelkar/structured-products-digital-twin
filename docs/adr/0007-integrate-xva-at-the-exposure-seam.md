# ADR 0007 — Combine SPDT + XVA at the exposure seam (shared core, two desks)

## Status
Accepted

## Context
SPDT (this repo, the equity structuring desk) and the XVA Engine (an INR OTC / CCR / XVA
platform, now vendored under `xva/`) are complementary halves of one derivatives business: SPDT
*prices and hedges* equity structured notes; XVA *charges* positions for counterparty, funding and
capital cost. They already share a data foundation (FBIL/RBI free Indian data), a curve framework
(OIS bootstrapping), and a Heston/AAD lineage. The XVA engine even ships the equity hooks the
structured notes need (`src/pricing/equity_options.py`, `src/montecarlo/equity_mc.py`,
`src/xva/hybrid_xva.py`). The question is *how* to combine them without a costly, value-free merge.

## Decision
Integrate at the **exposure/position seam, not the product model**, and keep two desks over one
shared core.

1. **One contract between the two systems: `ExposurePackage`** (`integration/exposure_package.py`)
   — a mark-to-future artefact (path × time NPV + time grid + counterparty + curves). SPDT
   *produces* it from its own Monte-Carlo engine; XVA *consumes* it via `ExposureCube.write_paths`
   → `compute_ee_profile` → `CVAEngine.compute_cva` / FVA / KVA / MVA. The two product models
   (SPDT's payoff DSL, XVA's trade objects) **stay independent** — they never need to be unified.

2. **Curve adapter, not re-bootstrap** (`integration/curve_adapter.py`). SPDT's `Curve.df(tau)`
   and XVA's `OISCurve.df(t)` are both year-fraction → discount-factor. A thin adapter lets a
   single bootstrapped SPDT curve drive `CVAEngine(ois_curve)` directly. One curve, two consumers.

3. **Two UIs, one backend.** SPDT's React desk stays the live front office; XVA's Streamlit stays
   the deep CCR/capital analytics surface. We add at most a thin "Counterparty & XVA" tab to the
   React desk for the per-trade charge — we do **not** rebuild XVA's ~12.5k LOC of analytics in
   React (effort with no new capability; see "two different kinds of tool" below).

4. **Vendored via `git subtree --squash`** under `xva/`. SPDT history stays readable; the original
   XVA repo retains its 33-commit granular history. Generated artefacts (exposure cube, EOD
   reports, db) are git-ignored.

## Rationale
- **The value is in the backend, not the frontend.** XVA-inclusive pricing and governance gating
  are core/data concerns; they need a shared backend, not a shared UI.
- **Integrate at the narrowest sufficient interface.** Exposure (path × time NPV) is the one thing
  XVA needs from SPDT and the one thing SPDT can produce that it doesn't already consume. Coupling
  there — and nowhere else — keeps each desk's product modelling free to evolve.
- **The hard new quant is bounded to one place:** structured-note *mark-to-future* (path-dependent
  EE, e.g. an autocallable's exposure collapsing on autocall). Everything else is assembly over
  code that already exists on both sides.

## Consequences
- A new top-level `integration/` package depends on *both* `spdt.*` and the vendored XVA `src.*`
  (it puts `xva/` on `sys.path`). It is the only place allowed to import across both worlds.
- The first milestone is a **curve-join proof**: one SPDT curve drives `CVAEngine` and the adapter's
  discount factors match the source to 1e-8 (`tests/test_xva_integration.py`, which carries every
  integration-phase gate end to end).
- Subsequent phases (exposure export → XVA charge → all-in price → governance → desk tab) each land
  as their own commit behind a verifiable gate; no second "big bang" commit.
- Scope discipline is explicit: integration happens *only* at `position → exposure → XVA → price`.
  Merging the two product models or the two UIs is out of scope unless a separate ADR overrides it.
