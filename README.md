# Structured Products Digital Twin (SPDT)

> A complete simulation of an equity structured-products desk: **structuring → pricing → hedging → risk → model validation → P&L attribution**, built on free Indian market data.

SPDT is a modular platform that structures, prices (BS / Local Vol / Heston / LSV), risk-manages, hedges, and attributes P&L for equity exotics (autocallables, Phoenix, barrier reverse convertibles, worst-of baskets) on NSE data — with AAD Greeks, model-reserve computation, historical backtesting, and a desk dashboard.

The full design specification and week-by-week build roadmap live in [`SPDT_Design_and_Build.md`](SPDT_Design_and_Build.md).

Two rules govern everything here:

- **Faithful, not fake.** Every component is architecturally and methodologically faithful to how a real desk works, even where it is simplified.
- **The math is the asset, not the code.** Each layer must be defensible from first principles — see [`docs/interview_defense.md`](docs/interview_defense.md).

---

## Scope contract (live — update as buckets change)

| Bucket | Meaning | Examples in SPDT |
|---|---|---|
| **REAL** | Mathematically correct, production-shaped, owned end to end | SVI/SSVI calibration, autocallable MC pricing, bump/pathwise/**AAD** Greeks (cross-checked on the autocallable), P&L attribution with **bucketed vega**, **two-curve discounting**, autocallable/Phoenix/**BRC/reverse-convertible/capital-protected** catalog |
| **FAITHFUL** | Correct method, scoped scale; real version differs only in size/optimisation | LSV calibration, the payoff DSL (composable leg primitives), Heston QE + Carr–Madan FFT, BGK barrier correction, historical replay, **C++ MC kernel** (one product ported, measured speedup; rest "same pattern") |
| **STUBBED** | Architecturally present with a clean interface; placeholder implementation | GPU pricing kernels (designed-for; CPU C++ path implemented), message queue (in-process bus that *could* be Kafka) |
| **SKIPPED (declared)** | Out of scope, named explicitly | Real-time market connectivity, regulatory capital (FRTB), multi-currency/quanto at scale |

---

## Architecture (14 layers)

```
EXECUTIVE DASHBOARD (L14)
  ▲   ▲   ▲   ▲   ▲
Hedging(L9) · P&L Attr(L10) · Model Risk(L11) · Stress(L12) · Docs(L13)
                      │
            VIRTUAL TRADING BOOK (L8)
                      │
  Structurer(L6) · Backtesting(L7) · Greeks Engine(L5)
                      │
              PRICING ENGINE (L4)
                      │
  Product DSL(L3) · Vol Analytics(L2) · Market Data(L1)
```

Everything is **snapshot-in, report-out**: every layer consumes an immutable, versioned `MarketSnapshot` and never touches raw data, which is what makes historical replay and reproducible P&L attribution possible.

| Layer | Package | Responsibility |
|---|---|---|
| L1 | `spdt/data` | Ingest, clean, version, snapshot, replay market data |
| L2 | `spdt/vol` | SVI/SSVI surface, arbitrage repair, Dupire local vol, forward smile |
| — | `spdt/corr` | Correlation estimators, Higham PSD repair, copulas |
| L3 | `spdt/products` | Payoff DSL — products as DAGs of primitives |
| L4 | `spdt/pricing` | Closed-form / PDE / MC pricing under BS, LV, Heston, LSV |
| L5 | `spdt/greeks` | Bump, pathwise, likelihood-ratio, AAD |
| L6 | `spdt/structurer` | Price-to-par solver, objective → structure proposer |
| L7 | `spdt/backtest` | Rolling historical issuance, outcome statistics |
| L8 | `spdt/book` | Virtual trading book, daily marks & Greeks |
| L9 | `spdt/hedging` | Dynamic delta/vega hedge simulation, residual P&L |
| L10 | `spdt/pnl` | Daily P&L attribution (Taylor explain + residual) |
| L11 | `spdt/modelrisk` | LSV−LV reserve, parameter-uncertainty, bid-offer |
| L12 | `spdt/stress` | Coherent macro scenarios, historical replays |
| L13 | `spdt/reporting` | Term sheet / factsheet / scenario-table generation |
| L14 | `spdt/dashboard` | Executive desk blotter (Streamlit) |

---

## Getting started

```bash
# editable install with dev tools
pip install -e ".[dev]"

# run the tests
pytest
```

Optional extras: `pip install -e ".[ad,dashboard]"` for JAX-based AAD and the Streamlit dashboard.

---

## Roadmap (high level)

- **MVP (Month 3) — "defensible core":** real NSE data → arbitrage-free SSVI surface → NIFTY autocallable priced by MC → Greeks via bump *and* pathwise/AAD (cross-checked) → coupon solved to par → term sheet rendered.
- **Advanced (Month 6) — "desk twin":** MVP + LSV + model reserves + virtual book replayed over history + dynamic hedging + daily P&L attribution + stress testing + dashboard.

See [`SPDT_Design_and_Build.md`](SPDT_Design_and_Build.md) §8 for the exact week-by-week plan.

## License

MIT
