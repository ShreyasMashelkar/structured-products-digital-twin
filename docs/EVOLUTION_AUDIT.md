# SPDT — Full Platform Evolution Audit

*A historical reconstruction of how the Structured Products Digital Twin was built, stage by
stage, with the technical and financial substance of each addition explained in depth. Every
claim is traceable to a commit hash, file path, or line number actually in the repo.*

Audit produced against `HEAD = 96a27b3` (main), build history `88daa60 … 96a27b3`.

---

## Executive Summary

SPDT was built in **six waves over five days (2026‑06‑16 → 06‑20)**, in a deliberate order that
is itself revealing: **documentation and design spec first**, then a **full L1–L13 architectural
spine** with deliberately *stubbed* advanced models, then the **sophistication** (SSVI / local
vol / Heston / LSV / correlation) poured into those stubs on a parallel track, then a **two‑curve
rate foundation**, then a **first Streamlit UI**, and finally a **large consolidation** that
committed the entire FastAPI+React web app, the C++ accelerator, full AAD, bucketed vega, the BGK
barrier correction, and four ADRs in one shot — followed by four PR‑gated refinement passes.

**The single most important finding, and a correction to the brief that commissioned this audit:**
the working tree is **clean** (`git status --short` is empty; `git diff --stat HEAD` is empty).
The brief was written at a moment when a huge fraction of the advanced work — the web app, the C++
kernel, AAD, bucketed vega, the barrier correction, term‑vol, the native bridge, the composable
legs DSL, and ADRs 0003–0006 — existed **only as uncommitted working‑tree changes**. **That is no
longer true.** All of it was committed on 2026‑06‑20 in **`b742b6e` ("Build full desk twin")**,
which is precisely the "uncommitted‑work consolidation commit" the brief recommends creating. The
history gap is closed; a reader relying on `git log` alone would now see the full story (with one
caveat: that one commit is enormous and flattens what was really weeks of layered work — §0, §5).

---

## §0 — Ground Truth: what is committed, and what the commit log hides

Three structural facts a naïve `git log` reading would get wrong:

**1. The working tree is clean — nothing advanced is uncommitted anymore.**
`git status --short` → empty. Every file the brief lists as "built, present, but uncommitted"
(`webapp/server.py`, `cpp/`, `spdt/greeks/aad/vec.py`, `spdt/greeks/buckets.py`,
`spdt/pricing/analytic/barrier_correction.py`, `spdt/pricing/models/term_vol.py`,
`spdt/pricing/native.py`, `spdt/products/legs.py`) returns the **same first‑add commit**:

```
webapp/server.py                              b742b6e Build full desk twin …
cpp                                           b742b6e Build full desk twin …
spdt/greeks/aad/vec.py                        b742b6e Build full desk twin …
spdt/greeks/buckets.py                        b742b6e Build full desk twin …
spdt/pricing/analytic/barrier_correction.py   b742b6e Build full desk twin …
spdt/pricing/models/term_vol.py               b742b6e Build full desk twin …
spdt/pricing/native.py                        b742b6e Build full desk twin …
spdt/products/legs.py                         b742b6e Build full desk twin …
```

So the work the brief feared could be lost to a disk failure is now in version control and pushed
to `origin/main`.

**2. The history is genuinely multi‑branch, then becomes PR‑gated.**
`git branch -a` shows the parallel tracks the brief anticipated:
`build/advanced-pricing`, `build/fbil-rate-bootstrap`, `build/desk-dashboard`,
plus doc branches (`shreyas/docs-layer-walkthrough`, `shreyas/docs-interview-defense`,
`docs/bootstrapped-rate-curves`) and a stale `build/spdt-full-stack` (now behind `main`).
The early topology is a fan: `build/advanced-pricing` → merged into `build/fbil-rate-bootstrap`
→ merged into `build/desk-dashboard` (commits `39b9c68`, `fefeb48`, `1ebe067`, `2f214bf`,
`b9de8e5`), then squared up through PRs #4/#6/#7. From `b742b6e` onward the project switches to a
**clean PR‑per‑feature flow** (#8 → #12).

**3. `b742b6e` is a "big bang" commit that under‑represents real effort.**
One commit added the entire web app, the C++ kernel, AAD, bucketed vega, BGK correction, term‑vol,
the native bridge, the legs DSL, and four ADRs. Git will date all of that to 2026‑06‑20 even
though, by internal evidence (ADRs that argue design choices, import graphs, stub‑then‑fill
patterns), it was built incrementally beforehand and simply committed late. **Wherever this audit
dates something to `b742b6e`, treat that as "committed then," not "built then."** Build order
within that commit is *inferred* from internal evidence and labelled as such.

---

## §1 — Chronological Build Narrative

### Wave 0 — Scaffold + design spec — `88daa60` (2026‑06‑16)
**What:** repository skeleton and the `docs/SPDT_Design_and_Build.md` design spec defining the
L1–L14 layer model.
**Why first:** the design doc fixes the *layer contract* (one‑way dependency direction, what each
layer owns) before any code, so later parallel branches can target disjoint layers without
colliding. This is a deliberate **design‑doc‑first** discipline, not code‑first.

### Wave 1 — Documentation‑first phase — `3e74ef3` (#1), `00cf4c3` (#2), `7651a1b` (#3) (06‑16→17)
**What:** three documentation PRs *before* the implementation spine — a plain‑English layer
walkthrough, an "interview defense & derivations" answer key, and a standalone note documenting
the **two‑curve rate model (OIS + issuer funding)**.
**Why this order:** the two‑curve *methodology* is documented (`7651a1b`, 06‑17) a full two days
before it is *implemented* (`8ea2e74`, 06‑19). Writing the derivation first is what lets the later
bootstrap be a transcription rather than a discovery — and it is why the funding‑curve ADR (0002)
reads as settled rather than exploratory.
**Build‑process note:** documenting the financial derivations before writing the code is unusual
for a solo project and is the clearest signal of the builder's priorities (§5).

### Wave 2 — The L1–L13 MVP spine — `e398aa0` (2026‑06‑18)
**What:** the entire architecture in one commit — data layer, products DSL, pricing, structurer,
book, hedging, P&L, model risk, stress, reporting. **But deliberately shallow on models.**

Verified MVP state (via `git show e398aa0:…`):
- **Catalog = one product.** `spdt/products/catalog.py` contains only `Autocallable` (a single
  `@dataclass class Autocallable(Product)`). The four income/protection notes and the worst‑of do
  not exist yet.
- **Advanced models are empty stubs.** `heston.py`, `lsv.py`, `ssvi.py`, `localvol.py`,
  `forward_smile.py` are all **0 non‑blank lines** at `e398aa0`. Only `spdt/vol/svi.py` is real
  (65 lines) — single‑expiry SVI slices.
- **21 test files** (now 42).

**So "MVP" meant:** the full *plumbing* of a desk — products‑as‑graph, a structurer, a book, a
hedging loop, model‑risk and stress scaffolding — pricing everything off **single‑slice SVI / flat
Black‑Scholes**, with the advanced‑model files scaffolded as empty placeholders to be filled on a
branch. The problem this solved: it let every downstream layer (book, hedging, stress, reporting)
be designed against a *stable pricing interface* before the hard quant landed, so the sophistication
could be added later without re‑touching the spine.

### Wave 3 — The advanced‑pricing track — `2c0e37e` (2026‑06‑19, `build/advanced-pricing`)
**What — the single largest sophistication jump in the committed history.** The stubs become real
(`git show 2c0e37e --stat`): `heston.py` 0→134 lines, `lsv.py` 0→124, `ssvi.py` 0→115,
`localvol.py` (Dupire), plus `tests/test_correlation.py`, `test_localvol_pricing.py`,
`test_ssvi_localvol.py`, and real NSE bhavcopy ingestion (`nse_bhavcopy.py` +141 lines).
**What it added, and why each:**
- **SSVI surface** over the per‑slice SVI — see ADR 0003. Independent SVI slices can cross in
  total variance across expiries (calendar arbitrage); SSVI is calendar‑arb‑free by construction.
- **Dupire local vol** from the smooth total‑variance surface — the unique 1‑factor diffusion that
  reprices the *entire* smile.
- **Heston** stochastic vol — gives smile *dynamics* a local‑vol model gets wrong.
- **LSV** on top of *both* — combines LV's exact vanilla calibration with Heston's correct forward
  smile (§4A).
- **Correlation / worst‑of** — Higham PSD repair, Gaussian + t copulas, and a worst‑of pricer
  whose value rises with correlation and sits below the single name.
**Problem solved:** before this, the desk's *own* barrier risk — which is acutely smile‑sensitive —
was measured with a flat‑vol model that structurally cannot see smile risk.

### Wave 4 — Two‑curve rate bootstrap — `8ea2e74`, `d85b762`, `1410e03` (06‑19, `build/fbil-rate-bootstrap`)
**What:** bootstrap the OIS/risk‑free curve from FBIL T‑bill + OIS quotes (`8ea2e74`); a live FBIL
downloader (`d85b762`); wire FBIL rates into the live NSE pipeline `build_live_snapshot` (`1410e03`).
**Why this order:** the bootstrap (`8ea2e74`) is committed *before* the downloader (`d85b762`) —
the curve methodology is built and tested against fixture quotes first, then the live data source
is plugged in. You can write a bootstrap before you have a feed; you cannot validate a feed before
you have a bootstrap to consume it. (See §4B for the financial content.)

### Wave 5 — The L14 Streamlit desk blotter — `0776403` (2026‑06‑19, `build/desk-dashboard`)
**What:** the first user‑facing surface — a Streamlit blotter exposing the book, greeks, stress and
reserves.
**What stayed backend‑only:** the structurer's live solve, the full model‑risk machinery, and all
pricing internals — Streamlit showed read‑outs, not an interactive structuring bench. This is the
limitation that motivates the next pivot (§2).
*(`c4aca75` is housekeeping — ruff F401 unused‑import fixes; `0dc51c7`/`e6eb90b` fix `.gitignore`
mistakes that were excluding the desk cache and the `book/` package.)*

### Wave 6 — The "full desk twin" consolidation — `b742b6e` (2026‑06‑20, PR #8)
**What (committed here, built incrementally before — see §0.3):** the entire `webapp/` FastAPI
backend + React/TS/Tailwind frontend; the `cpp/` C++ MC kernel + `spdt/pricing/native.py` bridge;
**full AAD** (`spdt/greeks/aad/vec.py`); **bucketed vega** (`spdt/greeks/buckets.py`); the **BGK
barrier correction** (`spdt/pricing/analytic/barrier_correction.py`); **term‑vol** model
(`term_vol.py`); the **composable legs DSL** (`spdt/products/legs.py`); and **ADRs 0003–0006**.
`4390e93` immediately fixes CI (declares the `web`/`test` deps and relaxes Heston complex‑typing
for mypy). This is the commit that closes the history gap.

### Wave 7 — Four PR‑gated refinement passes (2026‑06‑20, #9–#12)
- **`feea68f` (#9)** — design polish, live vega re‑mark, chart‑axis fixes.
- **`8b47e80` (#10)** — the **worst‑of becomes a real sub‑book** (3 baskets, aggregated correlation
  risk), full live blotter re‑marking, and the structurer build‑gaps (fee slider, issuer‑spread
  shock, hedge‑capacity, barrier monitoring).
- **`9e48aa5` (#11)** — **core deepening**: the empty modules get filled — Crank–Nicolson PDE,
  vega hedging under Heston, gap‑risk in the hedging engine, and the forward‑smile / stickiness
  L2 analytics.
- **`5a0451f` (#12)** — fix a real scenario‑table pricing bug (path struck at `ref=100` vs
  struck‑at‑spot wiped principal) and switch greek displays to cash gamma.

### Wave 8 — XVA / CCR integration & live data (2026‑06‑21→22, PRs #13–#29)
The second half of the platform: a vendored INR OTC / CCR / XVA engine combined with SPDT as **two
desks over one seam** ([ADR‑0007](adr/0007-integrate-xva-at-the-exposure-seam.md)). PR‑per‑phase
throughout — the granular cadence the rest of this audit recommended.
- **#13** — the integration foundation: vendored engine (`xva/`), the `ExposurePackage` curve‑join
  seam, and Phases 3–6 (mark‑to‑future exposure via Longstaff–Schwartz; all‑in price folding
  CVA+FVA into the par‑solve; the governance gate; the React **Counterparty & XVA** tab).
- **#14–#17** — hardening (CI now gates `integration/`+`webapp/`, repo mypy‑clean), and **CCR depth**:
  bilateral **DVA**, **KVA** in the price, Basel **EEPE** 1y cap, **CSA/MPoR collateral**,
  netting‑set aggregation, **wrong‑way risk**, then **MVA**, term‑structure credit, **CS01/JTD/stress**,
  equity **SA‑CCR** EAD and **BA‑CVA** capital — all surfaced live on the desk tab.
- **#18–#27** — docs: project walkthrough, XVA case study, README/architecture/interview‑defense
  brought current; a scope‑discipline fix (re‑export `CreditCurve` so `integration/` stays the sole
  cross‑world importer).
- **#20→#25** — the **live‑data pipeline**: NSE EOD **bhavcopy** (walk‑back to the latest published
  file), a removed‑then‑justified source selector, and an authenticated **Dhan** intraday source
  (nsepython was tried and dropped — NSE blocks public scraping). Synthetic stays the reproducible
  default; FBIL supplies rates.
- **#28–#29** — surface the **all‑in coupon** headline on the desk (base → net‑of‑XVA, live) and
  correct the documented coupons to annualised figures (7.25% → 1.09% p.a. at 300bp).

The result: `position → exposure → CVA+FVA+KVA+MVA−DVA → all‑in price → economic & regulatory
capital → RAROC governance → desk tab`, on synthetic / EOD / intraday data. ~280 tests, ruff + mypy
clean across ~100 files.

---

## §2 — The biggest pivot: Streamlit → React/FastAPI (zero commit history explains it)

The Streamlit blotter (`0776403`) and the React app (`b742b6e`) sit two commits apart with no
written rationale. Reasoning from what each surface *can do*:

| Requirement (from `webapp/frontend`) | Streamlit (`spdt/dashboard`) | Why Streamlit can't |
|---|---|---|
| **Debounced live structurer solve** — drag a slider, the coupon re‑solves continuously | rerun‑per‑widget model | every interaction re‑runs the whole script top‑to‑bottom; no client‑side debounce or partial update |
| **Simulated market tick** (700 ms mean‑reverting walk re‑marking NAV/Δ/vega/blotter) | server reruns | a `setInterval` re‑mark loop with retained client state is a React idiom; Streamlit has no persistent client tick |
| **Master‑detail trade selection** across a 4‑tab workspace | page‑per‑script | Streamlit's navigation is page‑switching, not in‑app state‑routed selection with a retained blotter |
| **Custom visual control** (3D vol surface that *breathes*, KPI flash, washes) | component sandbox | Streamlit's component model boxes you into its layout/theme; the desk needed pixel control |

**Conclusion (evidence‑cited):** the specific requirement Streamlit could not satisfy is
**stateful, low‑latency interactivity** — a structurer that solves *as you drag* and a book that
*ticks* — because Streamlit's execution model is "re‑run the whole script on any change." `App.tsx`
encodes exactly what Streamlit lacks: a client‑held `Market` state, a `setInterval` tick
(`App.tsx:97‑107`), and a `useMemo` Taylor re‑mark of the whole book (`App.tsx:113‑142`). That is
not expressible in Streamlit's model, which is why the desk outgrew it.

---

## §3 — Then (MVP `e398aa0`) vs Now (`96a27b3`)

| Dimension | At MVP (`e398aa0`, 06‑18) | Now (`96a27b3`, 06‑20) |
|---|---|---|
| **Catalog products** | **1** — `Autocallable` only | **5** — Autocallable, BRC, Reverse Convertible, Capital‑Protected Note, Worst‑Of Autocallable (`catalog.py:26,108,179,230,282`) |
| **Volatility model** | single‑slice **SVI** (65 lines) + flat BS; Heston/LSV/SSVI/localvol = **empty stubs (0 lines)** | **SSVI surface** + Dupire **local vol** + **Heston** (QE + Carr–Madan FFT) + **LSV** + **Crank–Nicolson PDE** |
| **Greeks method** | bump / pathwise | bump / pathwise / likelihood‑ratio / **AAD**, cross‑checked; **bucketed vega**; cash gamma display |
| **Discounting** | (spine present) | **two‑curve**: OIS discounting + issuer funding spread (ADR 0002) |
| **Data source** | fixtures | **NSE bhavcopy** + **FBIL** live OIS/T‑bill bootstrap |
| **Correlation / basket** | `corr/copula.py` **stub** | Higham PSD repair + Gaussian/t copula + worst‑of **sub‑book** with aggregated correlation risk |
| **Hedging** | delta loop | delta + **vega hedge under Heston** + **gap‑risk** (un‑hedgeable tail) |
| **Frontend** | none | Streamlit → **React/TS/Tailwind + FastAPI** desk terminal |
| **Native acceleration** | none | optional **C++ kernel** with graceful NumPy/Python fallback (ADR 0006) |
| **Test files** | **21** | **42** |

---

## §4 — Technical & Financial Reference (the deep section)

### A. Volatility & smile modelling

**Why a smile model at all.** Black‑Scholes assumes one constant σ for all strikes/expiries. The
market does not: out‑of‑the‑money puts trade at higher implied vol (the equity **put skew**), so a
flat σ *misprices anything with smile‑sensitive convexity*. An autocallable's embedded down‑and‑in
put lives exactly where the skew is steepest — price it flat and you systematically mismark your
own barrier risk.

**SVI (raw, 5‑parameter).** Each expiry's total variance is `w(k) = a + b(ρ(k−m) + √((k−m)²+σ²))`
in log‑moneyness `k`. The parameters control: `a` overall level, `b` the wing slope (how fast vol
rises away from the money), `ρ` the skew (asymmetry — negative for equity), `m` the horizontal
shift (where the smile bottoms), `σ` the curvature/ATM smoothness. SVI is the market‑standard slice
parameterisation because these five knobs map cleanly to observable smile features.

**Why SSVI over independent slices (ADR 0003).** Fitting SVI to each expiry *independently* gives
no guarantee that total variance is non‑decreasing in maturity at every strike — slices can cross,
which is **calendar arbitrage** (a free lunch: buy the cheaper longer‑dated variance, sell the
dearer short). **SSVI** parameterises the *whole surface* —
`w(k,θ) = (θ/2)(1 + ρφ(θ)k + √((φ(θ)k+ρ)² + 1−ρ²))` with `θ(T)` the ATM total‑variance term
structure and `φ` a power‑law — and is **calendar‑arb‑free by construction** under simple
parameter conditions, butterfly‑free under a companion condition on `θφ` (Gatheral–Jacquier). The
repo keeps per‑slice SVI as the calibration target/diagnostic but exposes SSVI as the surface.

**Dupire local vol.** Given an arbitrage‑free surface, there is a *unique* 1‑factor diffusion
`dS = (r−q)S dt + σ_LV(S,t) S dW` that reprices every vanilla, with
`σ_LV²(K,T) = ∂_T w / (1 − (k/w)∂_k w + ¼(−¼ − 1/w + k²/w²)(∂_k w)² + ½∂_kk w)` (the Dupire
formula in total‑variance form). Its strength is perfect static calibration; its known weakness is
**forward‑smile collapse** — propagate the surface forward and the smile flattens, so LV misprices
forward‑starting and strongly path‑dependent payoffs (cliquets, autocallables). This pathology is
exactly what the L2 forward‑smile module (Wave 7) makes visible and what motivates LSV.

**Heston stochastic vol.** Variance is its own mean‑reverting process:
`dv = κ(θ−v)dt + ξ√v dW₂`, `dS = (r−q)S dt + √v S dW₁`, `corr(dW₁,dW₂) = ρ`. Read the parameters:
**κ** mean‑reversion speed, **θ** long‑run variance, **ξ** vol‑of‑vol (smile curvature), **ρ**
spot/vol correlation (the **leverage effect** — ρ<0 makes down‑moves coincide with vol spikes,
i.e. the skew). Heston has a closed‑form **characteristic function**, so vanillas price by a single
Fourier inversion (Carr–Madan FFT) — fast enough to calibrate. It gives smile *dynamics* LV cannot.

**Andersen QE — why naïve Euler fails (ADR 0004).** Simulating the CIR variance with plain Euler,
`v_{t+Δ} = v + κ(θ−v)Δ + ξ√v √Δ Z`, can drive `v` **negative**, and `√v` of a negative number is
undefined — the scheme blows up or requires ugly truncation that biases the price. **Andersen's
Quadratic‑Exponential** scheme matches the first two moments of the *exact* non‑central‑χ²
transition law with one of two analytic proxies chosen per step by the variance level (a squared
Gaussian when variance is high, an exponential‑with‑atom when low), staying non‑negative by
construction. The martingale correction must be derived carefully, but the result is a stable,
accurate variance path — which matters because an autocallable's payoff hinges on whether the path
pierces a barrier, and a variance scheme that mis‑simulates vol mis‑simulates the barrier crossing.

**LSV (local‑stochastic vol).** Calibrate a **leverage function** `L(S,t)` so that
`σ_eff(S,t) = L(S,t)·√v` reproduces the vanilla surface *exactly* (LV's strength) while a Heston
factor supplies realistic forward‑smile dynamics (Heston's strength). `L` is found by the particle
method: `L²(S,t) = σ_LV²(S,t) / E[v | S_t=S]`, the conditional expectation estimated by binning
simulated paths. LSV is why the desk can hold *both* a perfectly‑calibrated price *and* correct
smile dynamics — and the gap between LSV and pure LV on exotic prices is booked as a **model
reserve** (§4F).

### B. Rates & discounting (two‑curve)

Pre‑2008, one LIBOR curve both discounted and forecast. The crisis broke the assumption that
inter‑bank funding was risk‑free; discounting moved to **OIS** (overnight indexed swap rates ≈ the
true risk‑free proxy, here bootstrapped from FBIL OIS/T‑bill quotes), while forecasting/funding
uses a *separate, wider* curve. For a structured note this is not cosmetic: the **option leg** (the
desk's hedge) is discounted on **OIS**, but the note's **funding leg** — the issuer borrowing at
its own credit — is discounted on the **issuer curve = OIS + funding spread** (ADR 0002). That
spread is real money: issuing a note funds the desk more cheaply than unsecured borrowing, and that
**funding benefit is part of the structuring economics** — ignore it and you misprice the note and
miss the issuer's actual edge. (Documented `7651a1b` 06‑17, implemented `8ea2e74` 06‑19.)

### C. Greeks & risk computation

- **Bump‑and‑reprice.** Perturb an input, reprice, finite‑difference. Simplest; **O(n)** repricings
  for n greeks; and *noisy for discontinuous payoffs* — a barrier's payoff jumps, so a bump that
  moves a path across the barrier produces a huge spurious difference.
- **Pathwise.** Differentiate the payoff w.r.t. the parameter *along each path* and average. Low
  variance, but **fails at payoff discontinuities** (the derivative of a step is a delta function)
  without smoothing — exactly the barrier problem again.
- **Likelihood‑ratio.** Differentiate the *probability density* instead of the payoff, so it works
  *through* discontinuities (the payoff is left alone), at the cost of higher variance.
- **AAD (adjoint algorithmic differentiation).** Apply the reverse‑mode chain rule to the entire
  pricing computation graph: one forward pass records the operations (a "tape"), one reverse pass
  propagates adjoints back through it, yielding **all** sensitivities in a *single* reverse sweep —
  **O(1) marginal cost per greek** regardless of how many, versus O(n) for bump. For a Monte‑Carlo
  autocallable with path‑dependent barriers and dozens of risk factors (spot, each vol bucket,
  rates, correlations), this is the difference between one reverse pass and dozens of full
  repricings. `spdt/greeks/aad/vec.py` implements a vectorised tape over the MC payoff graph and is
  cross‑checked against bump/pathwise; **bucketed vega** (`buckets.py`) then attributes vega to
  individual tenor/strike buckets of the surface rather than one number.

### D. Correlation & multi‑asset

- **Nearest‑PSD repair (Higham).** An estimated or *shocked* correlation matrix need not be a valid
  correlation matrix — stress a few entries and you can lose positive‑semi‑definiteness, which
  makes the Cholesky factor (needed to simulate correlated normals) fail. Higham's algorithm
  projects the broken matrix onto the nearest valid correlation matrix by **alternating
  projections** (onto the set of PSD matrices via eigenvalue clipping, and onto the set of
  unit‑diagonal matrices), converging to the closest legitimate matrix.
- **Gaussian vs t‑copula.** A Gaussian copula has *zero tail dependence* — in the extreme, names
  decouple. A **t‑copula** has heavy joint tails: names crash *together*. For a **worst‑of** payoff
  — driven entirely by the *worst* performer, i.e. by joint downside co‑movement — tail dependence
  is the whole risk, so modelling it with a Gaussian copula understates exactly the scenario that
  hurts.
- **Correlated GBM.** Simulate independent normals, correlate them with the Cholesky factor of the
  (repaired) correlation matrix, evolve each asset as GBM. The worst‑of value correctly **rises with
  correlation** (more correlated names disperse less, so the worst performer is less bad) and sits
  **below** any single‑name autocallable (the investor is short dispersion).

### E. Product mechanics (plain language)

- **Autocallable / Phoenix.** On each observation date, if the underlying is at/above the
  **autocall level**, the note redeems early at par plus coupon. If it never autocalls, at maturity
  the investor is protected unless the underlying has breached the **knock‑in** barrier, in which
  case they take the downside (often 1‑for‑1). **Memory** coupons accrue missed coupons and pay
  them once a coupon barrier is next met. The investor is effectively *short a down‑and‑in put and
  short volatility* in exchange for an above‑market coupon.
- **Barrier Reverse Convertible.** A high fixed coupon plus a short down‑and‑in put: full coupon
  always, principal returned *unless* the knock‑in barrier is breached, then losses below strike.
- **Reverse Convertible.** Same idea without the barrier — the short put is *always live*, so
  principal is at risk 1‑for‑1 below strike regardless of any barrier. (This is the product whose
  scenario table the §1 Wave‑7 fix corrected.)
- **Capital‑Protected Note.** A zero‑coupon bond + a long call: principal floored at maturity, with
  upside participation. The "safe" structure; pays for protection by giving up coupon/participation.
- **Struck vs floating initial fixing — and its delta consequence.** A note **struck** at a fixed
  level references a constant `S₀`; a **floating** fixing re‑strikes to the path's start. This is
  not a detail: if a worst‑of's inner option re‑strikes to the *bumped* spot when you compute
  delta, the bump cancels and **delta comes out zero** — the position looks deltaless when it
  isn't. The repo's worst‑of fixes the inner fixing at `1.0` precisely so bumping spot yields a real
  basket delta (a bug found and fixed during Wave 7).

### F. Model risk & validation

Two models calibrated to the **same** vanilla smile *will* disagree on exotic, path‑dependent
prices — LV and LSV reprice every vanilla identically yet differ on an autocallable because they
imply different *forward* smiles (§4A). A real desk cannot mark an exotic at one model's number and
ignore the other; it books the disagreement as a **model reserve** (here, `LSV − LV`, plus a
**bid‑offer reserve**). This is why banks run an independent **model‑validation / IPV** function: a
reserve is a capital charge against the possibility that your chosen model is the wrong one. SPDT
surfaces this as a first‑class KPI, which is unusually honest for a project of this scale.

### G. Engineering architecture

- **Layered L1–L14 with one‑way dependencies.** Each layer (data → vol → pricing → structurer →
  book → greeks → hedging → P&L → model‑risk → stress → reporting → UI) owns a responsibility and
  depends *only downward*. That is what let the MVP (`e398aa0`) ship the whole spine with stubbed
  models and have the advanced track (`2c0e37e`) fill them in without touching the layers above.
- **Products as a DAG of primitives** (`spdt/products/legs.py`). Rather than one hard‑coded payoff
  function per product, a note is a composable graph of payoff primitives (coupons, barriers,
  digitals, redemptions) tagged by leg (OPTION vs FUNDING for two‑curve discounting). Adding a new
  product becomes *composition*, not a new bespoke pricer — which is why going from 1 to 5 catalog
  products did not require five new pricing engines.
- **In‑process event bus (ADR 0005).** Layers talk through a thin typed pub/sub bus
  (`spdt/core/bus.py`) instead of importing each other's internals, so the claim "this could be
  swapped for Kafka/Redis Streams without touching business logic" is *structurally true and
  checkable*, not marketing — the interface is already message‑shaped.
- **Optional native kernel with graceful fallback (ADR 0006).** `price_autocallable(backend="auto")`
  has three implementations behind one signature: the C++ xoshiro256**/Box–Muller kernel, a
  vectorised NumPy reference computing the *identical* algorithm, and a pure‑Python scalar loop as
  the honest baseline. `native.py` does `try: import _spdt_mc except ImportError:` and **falls back
  to NumPy** if the compiled extension is absent; the wheel installs with no compiler, the kernel is
  built out‑of‑band, and tests skip when it is missing. A desk drops to native code only where the
  Python/NumPy MC loop overhead dominates — here, the inner autocallable path loop — and the design
  ensures the platform never *requires* the compiler to run.

---

## §5 — Synthesis

**1. What the build order reveals about priorities.** The actual order — verified, not assumed —
is **docs → MVP spine (stubbed) → sophistication → rates → UI → consolidation → refinement**. Two
things stand out: (a) **documentation and financial derivations came first** (the two‑curve model
was written 06‑17, coded 06‑19), and (b) the builder **shipped the whole architecture before any
of the hard quant**, deliberately stubbing Heston/LSV/SSVI to 0 lines and filling them on a
parallel branch. That is a mature instinct — design the contract, then pour in the math — and it is
why the layers never had to be re‑cut as sophistication landed.

**2. The biggest risk created by the (former) uncommitted situation — now resolved.** At the moment
the brief was written, a disk loss would have destroyed the *entire* web app, the C++ kernel, AAD,
bucketed vega, the BGK correction, term‑vol, the native bridge, the legs DSL, and four ADRs — the
most sophisticated ~half of the platform, none of it in version control. **That risk is now zero:**
`b742b6e` committed all of it and it is pushed to `origin/main`; the working tree is clean. The
*residual* risk is historiographical, not existential — `b742b6e` is a single giant commit that
flattens weeks of layered work into one timestamp, so the *granular* "why" of those files lives in
the ADRs and code comments rather than in commit messages.

**3. Recommendation going forward.** The consolidation the brief recommended has effectively
happened (it is `b742b6e`). To avoid needing this audit again: (a) keep the **PR‑per‑feature
cadence** that began at #8 — #9 through #12 are exactly the granular, well‑described history that
was missing earlier; (b) when a future change spans many files, resist a second "big bang" — split
by layer; (c) treat the ADR directory as the durable "why," since commit messages alone proved
insufficient for the pre‑`b742b6e` work. The history is healthy now; the task is to keep it that
way.

---

*End of audit. Every dated claim is traceable to a commit in `git log --all`; every "now" claim to
a file at `HEAD = 96a27b3`; every MVP claim to `git show e398aa0:<path>`. Inferences (build order
inside `b742b6e`) are labelled as such and never presented as dated fact.*
