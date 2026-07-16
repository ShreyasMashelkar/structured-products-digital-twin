# XTS Integration Roadmap for SPDT

## Purpose

This document explains how the Structured Products Digital Twin (SPDT) should evolve if AC Agarwal / Symphony XTS API access is obtained.

The target end-state is not just "connect to a broker API." The target is:

> A live Indian-market structured-products pricing, risk, hedging, and execution-aware desk platform.

XTS should be treated as infrastructure around the quant engine:

- Market data source for live prices, option chains, futures, candles, and instrument metadata.
- Execution and account source for orders, trades, positions, margins, and fill state.
- Broker bridge for turning SPDT hedge recommendations into paper or real trading workflows.

XTS should not be treated as a replacement for SPDT's pricing, Greeks, volatility, correlation, XVA, stress, or model-risk engines.

## Current SPDT Position

SPDT already has the core desk stack:

- Market data abstraction: `spdt/data`, `spdt/core/snapshot.py`
- Pricing: `spdt/pricing`
- Products and payoff DSL: `spdt/products`
- Volatility: `spdt/vol`
- Greeks: `spdt/greeks`
- Hedging and replication: `spdt/hedging`, `spdt/replication`
- Structuring: `spdt/structurer`
- Book and portfolio: `spdt/book`, `spdt/portfolio`
- P&L attribution: `spdt/pnl`
- Stress and backtesting: `spdt/stress`, `spdt/backtest`
- XVA integration: `integration/`, `xva/`
- React/FastAPI desk: `webapp/`

The major missing piece is real-time broker connectivity. XTS fills that gap.

## What XTS Provides

The useful XTS surface splits into two parts.

### Market Data API

Expected capabilities:

- Live quotes / LTP
- Bid and ask prices
- Market depth
- OHLC candles / historical bars
- Instrument master and exchange instrument IDs
- Equity, index, futures, options, currency, and commodity data, depending on enabled broker segments
- WebSocket tick streams

SPDT use cases:

- Live spot and futures marks
- Listed option-chain snapshots
- Intraday price monitoring
- Live dashboard feeds
- Barrier and autocall trigger monitoring
- Hedge rebalancing triggers
- Intraday P&L and risk updates

### Interactive / Trading API

Expected capabilities:

- Order placement
- Order modification and cancellation
- Order book
- Trade book
- Positions
- Holdings
- Margins / limits
- WebSocket order updates

SPDT use cases:

- Paper and live hedge execution
- Fill tracking
- Position reconciliation
- Execution cost analytics
- Hedge P&L attribution
- Risk limits and execution controls

## Design Principle

All XTS integration should flow through explicit adapters. Core quant modules should not import XTS clients directly.

Correct shape:

```text
XTS API
  -> spdt/data/ingest/xts.py
  -> MarketSnapshot
  -> pricing / greeks / vol / hedging / pnl / dashboard
```

and:

```text
hedge recommendation
  -> spdt/execution/paper.py
  -> spdt/execution/xts.py
  -> order state / fills / positions
  -> P&L attribution / dashboard
```

Avoid this:

```text
pricing engine -> direct XTS call
greeks engine -> direct XTS call
dashboard -> direct XTS call for business logic
```

The snapshot abstraction must remain the center of the system.

## Existing Improvements Covered

These are improvements to the existing SPDT project.

| Improvement | Implementation Area | Main Files / Modules |
|---|---|---|
| Replace synthetic/live stubs with real broker data | XTS market data adapter and snapshot builder | `spdt/data/ingest/xts.py`, `spdt/data/snapshot_builder.py`, `spdt/core/snapshot.py` |
| Live dashboard | Real-time API endpoints and React views | `webapp/server.py`, `webapp/frontend/src/views.tsx`, `webapp/frontend/src/App.tsx` |
| Better pricing inputs | Spot, futures, option chain, bid/ask, liquidity, candles | `spdt/data`, `spdt/vol`, `spdt/pricing` |
| Hedge recommendation engine | Turn Greeks and replication output into proposed trades | `spdt/hedging`, `spdt/replication`, `spdt/optimization`, `spdt/decisions` |
| Real P&L attribution | Use live marks, positions, orders, and fills | `spdt/pnl`, `spdt/analytics`, `spdt/backtest` |
| Execution-aware structuring | Include hedge cost, liquidity, slippage, margin, and executable instruments in product design | `spdt/structurer`, `spdt/optimization`, `spdt/execution` |

## New Ventures Covered

These are new product directions unlocked by XTS.

| Venture | What It Becomes | Roadmap Phases |
|---|---|---|
| Structured Product Trading Desk Simulator | Full desk workflow with book, risk, hedges, P&L, and approvals | Phases 5, 6, 8, 10 |
| Auto-Hedging Engine | Rule-based or optimization-based delta/vega hedge execution | Phases 6, 7, 8 |
| Live Autocallable Monitor | Autocall probability, barrier distance, coupon state, observation-date risk | Phases 4, 5, 10 |
| Indian Market Structured Product Issuer Toolkit | NIFTY/BANKNIFTY/equity note pricing, term sheets, hedge-cost-aware offers | Phases 3, 4, 10 |
| Broker-Integrated Risk Terminal | Bloomberg/Murex/Numerix-lite desk terminal for Indian structured products | Phases 1-10 |
| Execution Quality Analytics | Slippage, fill quality, latency, spread cost, market impact | Phases 6, 7, 9 |
| Client-Facing Payoff Explorer | Scenario returns, payoff diagrams, outcome probabilities, live indicative pricing | Phase 11 |
| Intraday Risk Alerts | Live barrier, Greek, liquidity, P&L, and margin alerts | Phase 12 |

## Roadmap Overview

Recommended build sequence:

1. XTS market data adapter
2. Live `MarketSnapshot` integration
3. Option chain and volatility surface
4. Live pricing and Greeks
5. Live dashboard upgrade
6. Paper execution layer
7. XTS interactive API in read-only mode
8. Hedge automation
9. P&L and execution attribution
10. Structured-products desk MVP
11. Client-facing payoff explorer
12. Intraday risk alert engine

The first major milestone should be:

> Live XTS-fed NIFTY/BANKNIFTY structured-product dashboard with pricing, Greeks, volatility surface, and paper hedge recommendations.

## Phase 1: XTS Market Data Adapter

### Goal

Bring broker market data into SPDT without disturbing the existing data abstraction.

### Build

Add:

- `spdt/data/ingest/xts.py`
- `tests/test_xts_ingest.py`
- Optional: `spdt/data/ingest/xts_types.py`

Core objects:

```python
class XTSMarketDataClient:
    def login(self) -> None: ...
    def instruments(self, exchange_segment: str) -> list[Instrument]: ...
    def quote(self, instruments: list[InstrumentRef]) -> list[Quote]: ...
    def candles(self, instrument: InstrumentRef, start, end, interval: str) -> list[Candle]: ...
    def option_chain(self, underlying: str, expiry: str) -> OptionChain: ...
```

Normalized data models:

- `Instrument`
- `InstrumentRef`
- `Quote`
- `DepthLevel`
- `Candle`
- `OptionContract`
- `OptionChain`

### Environment Variables

Do not hard-code credentials.

Suggested variables:

```text
SPDT_XTS_BASE_URL=
SPDT_XTS_MARKETDATA_APP_KEY=
SPDT_XTS_MARKETDATA_SECRET=
SPDT_XTS_INTERACTIVE_APP_KEY=
SPDT_XTS_INTERACTIVE_SECRET=
SPDT_XTS_CLIENT_ID=
SPDT_XTS_SOURCE=mock|live
```

### Testing

Use a mock XTS transport first. Tests should not require real credentials.

Test cases:

- Parses instrument master.
- Normalizes quotes into SPDT data models.
- Handles stale or missing quotes.
- Handles API failure with clear errors.
- Does not leak secrets in logs.

### Done When

- SPDT can fetch and normalize live or mocked NIFTY/BANKNIFTY/equity quotes.
- No pricing module imports XTS directly.
- Unit tests pass with mock credentials.

## Phase 2: Live Market Snapshot Integration

### Goal

Make the existing pricing engine consume XTS-fed data through `MarketSnapshot`.

### Build

Modify or extend:

- `spdt/core/snapshot.py`
- `spdt/data/snapshot_builder.py`
- `spdt/data/store.py`

Add:

```python
MarketSnapshot.from_xts(...)
```

or better:

```python
class XTSMarketSnapshotBuilder:
    def build(self, universe, asof) -> MarketSnapshot: ...
```

Snapshot should include:

- Source: `xts`
- Timestamp
- Underlying spot marks
- Futures marks
- Option marks
- Bid/ask where available
- Instrument IDs
- Staleness flags
- Provenance for each data point

### Design Requirements

- Preserve deterministic replay where possible by storing snapshots.
- Never silently mix XTS live data with synthetic data.
- Every fallback must carry provenance.
- Stale quotes should be explicit.

### Done When

- A structured product can be priced using an XTS-fed `MarketSnapshot`.
- The same snapshot can be saved and replayed.
- Dashboard/API can report snapshot source and timestamp.

## Phase 3: Option Chain and Volatility Surface

### Goal

Use XTS option data to improve listed-market realism.

### Build

Use:

- `spdt/data/curate/bs_inversion.py`
- `spdt/vol/svi.py`
- `spdt/vol/ssvi.py`
- `spdt/vol/arbitrage.py`
- `spdt/vol/surface.py`

Add:

- Live option-chain fetcher
- Bid/ask implied volatility
- Mid implied volatility
- Liquidity filters
- Strike and expiry selection
- Surface calibration from live option marks
- Arbitrage checks
- Surface diagnostics

### Inputs

For each option:

- Underlying
- Expiry
- Strike
- Call/put
- LTP
- Bid
- Ask
- Open interest
- Volume
- Timestamp

### Outputs

- Raw IV points
- Cleaned IV points
- Calibrated SVI/SSVI surface
- Bid/ask IV bands
- Liquidity score
- Arbitrage warnings

### Done When

- Dashboard displays a live NIFTY or BANKNIFTY implied-volatility smile.
- SPDT pricing can use the live calibrated surface.
- Illiquid and stale options are excluded or flagged.

## Phase 4: Live Pricing and Greeks

### Goal

Continuously reprice structured products as the market moves.

### Build

Use:

- `spdt/pricing/engine.py`
- `spdt/products`
- `spdt/greeks`
- `spdt/portfolio/aggregator.py`
- `spdt/book`

Add:

- Live repricing loop
- Product-level risk refresh
- Portfolio-level risk refresh
- Barrier distance
- Autocall distance
- Autocall probability estimate
- Scenario table
- Greek changes since prior snapshot

### Products to Support First

1. NIFTY autocallable
2. BANKNIFTY barrier reverse convertible
3. Worst-of basket on 2-3 liquid Indian names
4. Capital-protected note

### Done When

- At least one live product reprices from XTS-fed data.
- Greeks update without manually rebuilding the app.
- Dashboard shows price, delta, vega, theta, barrier distance, and next observation risk.

## Phase 5: Live Dashboard Upgrade

### Goal

Turn the existing app into a live desk terminal.

### Build

Use:

- `webapp/server.py`
- `webapp/frontend/src/App.tsx`
- `webapp/frontend/src/views.tsx`
- `webapp/frontend/src/components`
- `spdt/dashboard`

### Views

Add or upgrade these workspaces:

- Market overview
- Product book
- Live option chain
- Volatility surface
- Product detail
- Greeks and risk
- Hedge recommendations
- P&L attribution
- Execution blotter
- Alerts

### API Endpoints

Suggested endpoints:

```text
GET /api/live/market
GET /api/live/snapshot
GET /api/live/option-chain?underlying=NIFTY
GET /api/live/vol-surface?underlying=NIFTY
GET /api/book/live
GET /api/risk/live
GET /api/hedges/recommendations
GET /api/execution/blotter
GET /api/alerts
```

### Done When

- The dashboard feels like a live trading/risk terminal.
- Users can see live market inputs, model outputs, risk, and suggested hedges in one flow.

## Phase 6: Paper Execution Layer

### Goal

Simulate trading before any real order routing exists.

### Build

Add:

- `spdt/execution/__init__.py`
- `spdt/execution/types.py`
- `spdt/execution/paper.py`
- `spdt/execution/costs.py`
- `tests/test_paper_execution.py`

Core objects:

- `Order`
- `OrderIntent`
- `OrderStatus`
- `Fill`
- `ExecutionReport`
- `Position`
- `ExecutionVenue`

Paper execution should support:

- Market order simulation
- Limit order simulation
- Partial fills
- Slippage
- Bid/ask crossing cost
- Brokerage / taxes / fees
- Execution logs
- Paper positions

### Done When

- A hedge recommendation can be converted into paper orders.
- Paper fills update paper positions.
- Hedge P&L can be tracked from paper fills and live marks.

## Phase 7: XTS Interactive API Read-Only First

### Goal

Connect trading/account data safely before enabling live trading.

### Build

Add:

- `spdt/execution/xts.py`
- `tests/test_xts_execution.py`

Start with read-only methods:

```python
class XTSExecutionClient:
    def login(self) -> None: ...
    def orders(self) -> list[OrderState]: ...
    def trades(self) -> list[Trade]: ...
    def positions(self) -> list[Position]: ...
    def margins(self) -> MarginState: ...
```

Then add gated order methods:

```python
def place_order(order: OrderIntent) -> OrderAck: ...
def modify_order(order_id: str, change: OrderChange) -> OrderAck: ...
def cancel_order(order_id: str) -> OrderAck: ...
```

### Safety Controls

Live trading must be disabled by default.

Required controls:

```text
SPDT_EXECUTION_MODE=paper|read_only|live
SPDT_LIVE_TRADING=false
SPDT_MAX_ORDER_NOTIONAL=
SPDT_ALLOWED_INSTRUMENTS=NSEFO:101,NSEFO:202
SPDT_KILL_SWITCH=true|false
```

Rules:

- Default mode is `paper`.
- Read-only mode can fetch broker state but cannot place orders.
- Live mode requires explicit environment flag.
- Every live order must pass risk checks.
- Every live order must be logged.

### Done When

- SPDT can read XTS orders, trades, positions, and margins.
- Live order placement is present only behind explicit gates.
- Paper mode remains the default for demos.

## Phase 8: Hedge Automation

### Goal

Convert SPDT risk into executable hedge recommendations.

### Build

Use:

- `spdt/hedging/delta_vega.py`
- `spdt/replication`
- `spdt/optimization`
- `spdt/decisions/engine.py`
- `spdt/execution`

### Hedge Engines

Start simple:

1. Delta hedge using futures.
2. Delta-vega hedge using options.
3. Semi-static barrier hedge using listed options.
4. Cost-aware hedge optimization.

Each recommendation should include:

- Current exposure
- Target exposure
- Proposed instruments
- Quantities
- Expected Greek reduction
- Estimated spread cost
- Estimated brokerage / taxes
- Expected slippage
- Liquidity score
- Reason code
- Approval state

### Approval States

```text
PROPOSED
APPROVED_FOR_PAPER
APPROVED_FOR_LIVE
REJECTED_LIMIT
REJECTED_LIQUIDITY
REJECTED_STALE_DATA
MANUAL_REVIEW
```

### Done When

- The system recommends a hedge that reduces risk measurably.
- The recommendation can be paper-executed.
- The dashboard shows before/after Greeks and estimated cost.

## Phase 9: P&L and Execution Attribution

### Goal

Explain intraday and daily P&L using model, market, hedge, and execution components.

### Build

Use:

- `spdt/pnl/attribution.py`
- `spdt/pnl/replication_attribution.py`
- `spdt/analytics/replication_history.py`
- `spdt/backtest`
- `spdt/execution`

### Attribution Buckets

- Clean model P&L
- Delta P&L
- Gamma P&L
- Vega P&L
- Theta / carry
- Vol surface movement
- Correlation movement
- Funding movement
- XVA movement
- Hedge P&L
- Slippage
- Spread cost
- Brokerage / taxes
- Residual unexplained P&L

### Execution Quality Analytics

Add:

- Expected fill vs actual fill
- Arrival price slippage
- Spread capture / spread paid
- Latency
- Partial fill rate
- Rejected order rate
- Market impact estimate
- Cost by instrument

### Done When

- Dashboard explains why a note or book made/lost money.
- Hedge execution costs are visible separately from model P&L.
- Residual P&L is tracked and not hidden.

## Phase 10: Structured-Products Desk MVP

### Goal

Package the whole system into an end-to-end desk workflow.

### Workflow

1. Select client objective.
2. Propose product structure.
3. Price the product using live market data.
4. Solve coupon/barrier/strike to target economics.
5. Include XVA and funding.
6. Estimate hedge cost and liquidity.
7. Generate term sheet.
8. Book trade into virtual book.
9. Monitor live risk.
10. Recommend hedges.
11. Paper or live execute hedges.
12. Attribute P&L.
13. Produce risk and client reports.

### Use Existing Modules

- `spdt/structurer`
- `spdt/products`
- `spdt/pricing`
- `integration/all_in_price.py`
- `integration/governance.py`
- `spdt/reporting/termsheet_render.py`
- `spdt/book`
- `spdt/hedging`
- `spdt/pnl`
- `webapp`

### Done When

End-to-end demo:

> Structure a NIFTY autocallable, price it from live XTS data, solve the coupon, include XVA/funding, generate a term sheet, book it, monitor risk, recommend a hedge, paper-execute the hedge, and explain P&L.

## Phase 11: Client-Facing Payoff Explorer

### Goal

Create a client-friendly view of product outcomes while keeping the internal quant stack intact.

### Build

Add a frontend workspace for:

- Payoff diagram
- Scenario returns
- Probability of outcomes
- Downside loss frequency
- Historical replay outcomes
- Barrier breach probability
- Autocall probability
- Coupon schedule
- Live indicative value
- Plain-English risk summary

### Important Boundary

This is an explanatory interface, not financial advice. Keep risk disclosures visible in exports and reports.

### Done When

- A non-quant user can understand payoff, upside, downside, triggers, and scenario behavior.
- The view is fed by the same product/pricing engine as the desk.

## Phase 12: Intraday Risk Alert Engine

### Goal

Detect and surface risk events while the market is live.

### Build

Add:

- `spdt/alerts/__init__.py`
- `spdt/alerts/rules.py`
- `spdt/alerts/engine.py`
- `tests/test_alerts.py`

Alert types:

- Barrier distance below threshold
- Autocall observation approaching
- Delta limit breach
- Vega limit breach
- Gamma spike
- P&L drawdown
- Hedge P&L divergence
- Stale market data
- Liquidity deterioration
- Margin usage threshold
- Failed hedge execution
- XVA charge spike

Alert object:

```python
class Alert:
    id: str
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    category: str
    message: str
    trade_id: str | None
    metric: str
    value: float
    threshold: float
    timestamp: datetime
    status: Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"]
```

### Done When

- Alerts appear in the dashboard.
- Alerts can be acknowledged.
- Alert history is stored.
- Alerts link back to the product, risk, or execution item that triggered them.

## Data Model Additions

### Instrument Identity

SPDT needs a stable internal instrument identity that can map to XTS exchange IDs.

Suggested model:

```python
class InstrumentRef:
    internal_id: str
    exchange: str
    segment: str
    symbol: str
    xts_exchange_instrument_id: str | None
    expiry: date | None
    strike: float | None
    option_type: str | None
```

### Quote

```python
class Quote:
    instrument: InstrumentRef
    timestamp: datetime
    ltp: float | None
    bid: float | None
    ask: float | None
    bid_qty: float | None
    ask_qty: float | None
    volume: float | None
    open_interest: float | None
    source: str
    stale: bool
```

### Hedge Recommendation

```python
class HedgeRecommendation:
    recommendation_id: str
    trade_id: str | None
    portfolio_id: str
    created_at: datetime
    objective: str
    current_greeks: dict[str, float]
    target_greeks: dict[str, float]
    orders: list[OrderIntent]
    estimated_cost: float
    estimated_slippage: float
    expected_risk_reduction: dict[str, float]
    approval_state: str
    reason_codes: list[str]
```

## Security and Operational Rules

### Credentials

- Store credentials only in environment variables or a local secret manager.
- Never commit credentials.
- Add `.env` to `.gitignore` if not already present.
- Mask credentials in logs and errors.

### Live Trading

- Live trading off by default.
- Paper mode should be the default demo mode.
- All live orders must pass:
  - symbol allowlist
  - max notional
  - max quantity
  - market-hours check
  - stale-data check
  - margin check
  - kill-switch check

### Audit

Store:

- Raw order intent
- Risk checks
- Approval state
- API request ID
- Broker order ID
- Fill reports
- Final position impact
- User/action source

## Suggested Milestones

### Milestone 1: Live Data MVP

Deliver:

- XTS market data adapter
- Live quote endpoint
- Snapshot source integration
- Dashboard market overview

Demo:

> Show live NIFTY/BANKNIFTY spot/futures/option quotes inside SPDT.

### Milestone 2: Live Vol and Pricing

Deliver:

- Option chain ingestion
- IV inversion
- SVI/SSVI calibration
- Product repricing
- Greeks refresh

Demo:

> Price a NIFTY autocallable using a live XTS-fed volatility surface.

### Milestone 3: Paper Hedging

Deliver:

- Hedge recommendation engine
- Paper execution
- Paper positions
- Hedge P&L

Demo:

> Reprice a note, recommend a futures/options hedge, paper-execute it, and show before/after Greeks.

### Milestone 4: Broker Read-Only Integration

Deliver:

- XTS interactive API read-only client
- Orders/trades/positions/margins view
- Position reconciliation

Demo:

> Show broker positions and compare them with SPDT's virtual hedge book.

### Milestone 5: Desk MVP

Deliver:

- Product creation
- Live pricing
- XVA/funding inclusion
- Term sheet
- Book/risk dashboard
- Hedge recommendation
- Paper execution
- P&L attribution

Demo:

> Run the full structured-products desk workflow from product design to P&L explanation.

### Milestone 6: Advanced Product Layer

Deliver:

- Client payoff explorer
- Intraday alerts
- Execution quality analytics
- Live autocallable monitor

Demo:

> Show a client-facing payoff view, a trader risk view, and a risk-manager alert view for the same booked note.

## Product Positioning After Completion

If implemented well, SPDT can be described as:

> A live Indian-market structured-products digital twin that combines pricing, volatility calibration, Greeks, XVA, hedging, execution simulation, broker connectivity, and P&L attribution.

Comparable categories:

- Bloomberg OVME-style pricing and scenario analytics
- Numerix/Murex-lite structured-products lifecycle and risk
- Broker-integrated algo/risk terminal
- Internal issuer or wealth-desk product workbench

Important caveat:

This would still be an MVP/prototype, not an institutional production platform. Production would require model validation, security hardening, clean data licensing, failover, proper audit, permissioning, compliance workflows, and operational controls.

## What Not To Build Too Early

Defer these until the core loop works:

- Full live auto-trading without paper mode
- Complex OMS replacement
- Multi-user permissions
- Full regulatory reporting
- Multi-asset global product coverage
- GPU pricing unless performance becomes the bottleneck
- Full tick database
- Overly broad brokerage abstraction before XTS works

Focus first on one convincing live loop:

```text
XTS market data
  -> MarketSnapshot
  -> vol surface
  -> product price and Greeks
  -> hedge recommendation
  -> paper execution
  -> P&L attribution
  -> dashboard
```

## Recommended First Implementation Ticket

Title:

> Add XTS market-data adapter and live quote normalization.

Scope:

- Create `spdt/data/ingest/xts.py`
- Add typed quote/instrument models if missing
- Read XTS credentials from environment variables
- Implement mockable transport
- Normalize quote response into SPDT quote objects
- Add tests using fixture JSON
- Add a small CLI or API endpoint to fetch NIFTY/BANKNIFTY quotes

Acceptance criteria:

- Runs without real credentials in mock mode.
- Can use real credentials when provided.
- No secrets appear in logs.
- No core pricing module imports XTS.
- Test suite covers success, stale data, missing quote, and API error paths.
