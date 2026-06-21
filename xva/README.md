# INR OTC Derivatives Risk & Multi-Asset XVA Analytics Platform

An end-to-end quantitative finance platform for pricing, CCR risk management,
XVA computation, and regulatory capital on Indian OTC interest rate derivatives.
Built with free data sources only (RBI DBIE, FIMMDA, FBIL — all publicly available).

---

## What This Platform Does

This platform mirrors the actual workflow of a Rates / CCR / XVA desk at an Indian
or global bank: trade-level pricing → Monte Carlo exposure simulation → collateral
modelling → CVA/FVA/KVA/MVA calculation → SA-CCR regulatory capital → EOD batch
reporting → database persistence.

---

## Features

### Core Pricing & Curves
- **INR OIS Curve Bootstrapping** — Log-linear DF interpolation from FBIL MIBOR market rates
- **G-Sec Yield Curve** — Cubic spline on RBI auction yields; OIS-G-Sec spread calculation
- **Multi-Curve Framework** — OIS discounting + separate MIBOR projection curve (dual-curve)
- **INR IRS/OIS Swap Pricer** — MTM, par rate, DV01, PV01, Key Rate DV01, Gamma
- **SABR Vol Surface** — Hagan (2002) normal SABR for INR swaptions; full expiry × tenor grid
- **Equity Options Pricing** — Black-Scholes, Local Volatility, and Heston (closed-form & MC)

### Exposure Simulation
- **Hull-White 1F Monte Carlo** — Exact simulation, 10,000 paths, EE/EPE/PFE/ENE/EEPE
- **Equity Monte Carlo** — Vectorized Geometric Brownian Motion & Heston stochastic volatility models
- **HW1F Calibration** — OLS regression on RBI DBIE MIBOR history; both `a` and `σ` are data-driven
- **Persistent Exposure Cube** — PyArrow/Parquet storage of path × time × trade NPVs; correct portfolio netting
- **CSA Collateral Engine** — Threshold, MTA, exact continuous-time MPOR with Brownian diffusion correction; uncollateralised vs. CCP comparison

### XVA Engines
- **CVA / DVA** — Bootstrapped hazard rates from synthetic Indian CDS spreads; bilateral CVA
- **FVA (v1 & v2)** — Profile-based FCA/FBA and Pathwise funding cost (eliminates Jensen bias)
- **MVA & KVA** — ISDA SIMM v2.7 IM calculation; SA-CCR-based KVA term structure
- **Wrong-Way Risk** — Cox-process stochastic intensity, Gaussian copula, and regime-switching models
- **Hybrid XVA (Rates + Equity)** — Cross-asset exposure profile, combined netting sets for multi-asset portfolios

### Regulatory Capital
- **SA-CCR (Basel III)** — RC, supervisory duration, effective notional, netting set PFE
- **RWA & Capital Charge** — Per RBI Basel III guidelines; counterparty type risk weights

### Institutional Workflow & Governance
- **Pre-Trade Approval Workflow** — Evaluates Limit usage, RAROC accretion, and Incremental XVA before Trade Approval (APPROVED/REJECTED/MANUAL_REVIEW).
- **Incremental XVA** — Exact marginal XVA impact using identical Monte Carlo paths for clean differencing.
- **Counterparty Limits** — EAD and PFE limit monitoring with RAG status logic across Legal Entity hierarchies.
- **RAROC & Economic Capital** — ASRF (Asymptotic Single Risk Factor) model for Economic Capital at 99.9% confidence; Hurdle-based RAROC and EVA analysis.

### Analytics & Reporting
- **PnL Attribution** — Carry, Roll-Down, Delta, Gamma, New Fixing, Unexplained decomposition
- **Exposure Attribution** — Day-over-day exposure changes separated by New Trades, Matured Trades, Market Moves, and Unexplained.
- **XVA Attribution** — Day-over-day CVA changes; spread, exposure, time-decay components
- **Stress Testing** — RBI rate shock (±100/200bps) × credit spread widening scenarios
- **Management Reporting API** — Consolidated daily JSON reports detailing Capital, Returns, Stress, WWR, and Governance status.
- **Model Validation Suite** — 8 quantitative MRM tests: MC convergence, bootstrap repricing,
  antithetic VR, CVA analytical benchmark, no-arbitrage forwards, SA-CCR formulas, HW1F fit

### Infrastructure
- **EOD Batch Engine** — Full portfolio CVA/FVA/KVA/MVA/EAD per counterparty in one run
- **SQLite Persistence** — XVAResult, CurveSnapshot, MarketDataSnapshot via SQLAlchemy
- **FastAPI REST Layer** — Comprehensive API endpoints for pricing, curves, and trade approval pipelines.
- **Streamlit Dashboard** — 34 pages organized into institutional categories with dynamic dual-dropdown navigation and heavy `@st.cache_data` state caching for instant reloads.

---

## Data Sources (All Free)

| Source | Data | URL |
|---|---|---|
| RBI DBIE | Overnight MIBOR history, G-Sec yields, policy rates | https://dbie.rbi.org.in |
| FIMMDA | OIS curve market rates, IRS benchmark rates | https://www.fimmda.org |
| FBIL | MIBOR overnight fixing, OIS benchmarks | https://www.fbil.org.in |
| CCIL | OIS/IRS volumes, settlement data | https://www.ccilindia.com |

**Note:** INR swaption implied vols and Indian CDS curves require Bloomberg/Refinitiv
and are not freely available. Accordingly:
- SABR ATM vol is anchored to realised MIBOR vol (RBI DBIE — free)
- CDS spreads are synthetic market-convention proxies (documented in `counterparties.csv`)
- HW1F calibration uses realised MIBOR vol, not swaption vols

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run full test suite
pytest tests/ -v

# Run EOD batch (generates comprehensive report)
python -m src.eod.risk_engine

# Launch dashboard
streamlit run app/streamlit_app.py

# Start REST API
uvicorn api.main:app --reload --port 8000
```

---

## Project Structure
XVA Engine/
├── src/
│   ├── calibration/      # HW1F calibration from MIBOR history
│   ├── curves/           # OIS/G-Sec bootstrapping, multi-curve, CDS bootstrapper
│   ├── data_ingestion/   # Market data (FIMMDA/DBIE anchored)
│   ├── economic_capital/ # ASRF Economic Capital models
│   ├── eod/              # EOD Risk Engine
│   ├── exposure/         # Persistent Parquet exposure cube
│   ├── limits/           # Limit engine
│   ├── montecarlo/       # Hull-White 1F/2F simulation + Quasi-MC
│   ├── csa/              # CSA collateral engine
│   ├── portfolio/        # Netting engine, capital optimizer
│   ├── pricing/          # Swap pricer, swaption (Bachelier), SABR
│   ├── raroc/            # RAROC engine
│   ├── reporting/        # Management reporting API
│   ├── sa_ccr/           # SA-CCR EAD, RWA, capital, FRTB-CVA
│   ├── stress/           # Rate shock + credit spread stress tests
│   ├── utils/            # Autodiff, vectorised ops
│   ├── validation/       # Model validation suite (MRM)
│   ├── workflow/         # Trade approval, hierarchy, incremental XVA
│   ├── wwr/              # Specific & General wrong-way risk
│   └── xva/              # CVA, DVA, FVA v1/v2, KVA, MVA, SIMM
├── api/                  # FastAPI REST endpoints
├── app/                  # Streamlit dashboard (34 pages)
├── db/                   # SQLAlchemy models + SQLite
├── data/                 # Portfolio, counterparties, CSA master, exposure cube
├── reports/              # EOD batch output CSV
├── tests/                # Pytest suite (231 tests)
└── requirements.txt

---

## Tech Stack

Python 3.10+ · NumPy · SciPy · Pandas · PyArrow · Plotly · Streamlit · FastAPI · SQLAlchemy · Pytest

---

## Resume Line

> Built an end-to-end INR OTC derivatives risk, multi-asset XVA analytics, and institutional governance platform. Implemented FBIL MIBOR OIS curve bootstrapping, SABR vol surface, Hull-White/Heston Monte Carlo, CSA-aware exposure simulation via a persistent Parquet cube, and full multi-asset XVA suite (CVA/DVA/FVA/MVA/KVA). Engineered a complete front-to-back institutional workflow integrating Basel SA-CCR/FRTB-CVA capital, Economic Capital (ASRF), pre-trade limits, Incremental XVA via identical MC paths, and RAROC-based automated Trade Approval. Includes an MRM model validation suite (IMM backtesting), PnL/Exposure attribution, IFRS-13 accounting, FastAPI REST layer, SQLite persistence, and a comprehensive 34-page Streamlit dashboard. All data anchored to free Indian market sources (RBI DBIE, FIMMDA).
