import { useEffect, useRef, useState } from "react";
import { Blotter as PaperBlotter, BrokerState, ChainRow, Decision, Desk, DeskAlert, ExplorerResult, HedgeRec, LiveQuote, OutcomeResult, PriceResult, SemiStaticResult, AutohedgeStatus, DeskHistoryRow, ResidualResult, StructureResult, VolTrackerData, XvaResult, Market, MarketMeta, Shelf, ackAlert, computeXva, executeRecommendation, explore, getAlerts, getAttribution, getBlotter, getBrokerState, getLiveQuote, getAutohedge, getDeskHistory, getOptionChain, getOutcomes, getRadar, getRecommendations, getResidual, getVolTracker, setAutohedge, getSemiStatic, priceTrade, recommendHedge, solveStructure, getMarket, getMarkets, getShelf } from "./lib/api";
import { TYPE_ABBR, Trade, bookTrades, priceReq, productLabel } from "./lib/trades";
import { Chip, DataTable, Kpi, Panel, SectionTitle } from "./components/ui";
import { AreaSpark, Bars, Histogram, Lines, Surface3D, Waterfall } from "./components/charts";
import { cn } from "./lib/cn";
import { compact, fmt, fmtAge, pct, signed } from "./lib/format";
import { C } from "./lib/theme";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, LineChart, Line, Legend } from "recharts";

/* ======================= shared bits ======================= */

function Slider({
  label, value, min, max, step, onChange, display,
}: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; display: string }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.07em] text-muted">{label}</span>
        <span className="tnum text-[13px] font-semibold text-accent">{display}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="ring-desk h-1.5 w-full cursor-pointer appearance-none rounded-full bg-border accent-accent" />
    </div>
  );
}

function GreekStat({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  return (
    <div className="rounded-lg border border-border bg-panel2/60 px-3 py-2">
      <div className="text-[10px] uppercase tracking-[0.08em] text-muted">{label}</div>
      <div className={cn("tnum mt-0.5 text-[15px] font-semibold", tone === "pos" ? "text-up" : tone === "neg" ? "text-down" : "text-ink")}>{value}</div>
    </div>
  );
}

/* ======================= How to use ======================= */

const TOUR_STEPS = [
  {
    tab: "Overview",
    kicker: "Start here",
    title: "Read the desk in 30 seconds",
    body: "Book NAV, overnight P&L explain, top movers and worst stresses — plus, on the live feed, realized-vs-implied vol (the desk's carry gauge) and intraday replay charts of NAV, spot and net Δ.",
    checks: ["Confirm the book is live/loaded and note count looks right.", "On the live feed, watch IV − RV and the Γ carry/day it implies for the book.", "Use the waterfall to see whether P&L is explained by Greeks or residual.", "The replay charts show every desk rebuild and paper execution through the day."],
    firstClick: "Top movers list",
  },
  {
    tab: "Originate",
    kicker: "Build a note",
    title: "Turn a client brief into a priced structure",
    body: "Set coupon, protection, maturity and observations. The engine recommends a structure, solves it to par, and lets you stage it into the book.",
    checks: ["Move coupon/protection sliders and watch whether the ask is achievable.", "Compare the recommended product with alternatives ranked by fit.", "Add the solved note to the book to see its risk impact."],
    firstClick: "Target coupon slider",
  },
  {
    tab: "Book & Risk",
    kicker: "Inspect the book",
    title: "Drill into the 15-note portfolio",
    body: "Click a trade to see terms, live re-price, Greeks, stress contribution and how it behaves under the simulated market move. The barrier radar below ranks every note by knock-in/autocall proximity against live spot.",
    checks: ["Select any trade ID to open the live detail pane.", "Use tenor/product filters to see risk concentrations.", "On the radar, watch KI distance in %, in σ's, and the model-implied touch probability — it re-ranks with spot every 30s."],
    firstClick: "Any NOTE-xxx row",
  },
  {
    tab: "Counterparty & XVA",
    kicker: "Capital view",
    title: "See the CCR/XVA layer on the same trades",
    body: "Shows exposure, CVA/FVA/KVA-style charges, RAROC and approval logic from the companion INR CCR/XVA engine integrated at the exposure seam.",
    checks: ["Select a note and see exposure profiles feeding XVA.", "Review whether incremental XVA/RAROC passes governance.", "Use this as the bridge from structuring price to capital-aware approval."],
    firstClick: "Trade selector",
  },
  {
    tab: "Validate",
    kicker: "Model controls",
    title: "Check whether the model output is believable",
    body: "Surface health, pricing checks, explain residuals and validation flags. The Taylor-vs-full-reval panel re-prices the whole book at any market shift you choose and shows what Δ/Γ/ν cannot explain.",
    checks: ["Run the full reval at a 2% move (greeks should explain nearly all of it), then at 10% to watch the Taylor expansion break down.", "Check vol-surface no-arbitrage and model-health flags.", "Look for pricing/explain residuals that are too large."],
    firstClick: "Run full reval",
  },
  {
    tab: "Semi-Static Hedging",
    kicker: "Hedge implementation",
    title: "Replicate barrier risk with listed-style strips",
    body: "For barrier-linked notes, it builds constrained option strips to cover part of the embedded barrier exposure, then shows the residual Greeks left for dynamic hedging.",
    checks: ["Pick a barrier-linked trade from the live book.", "Inspect the option strip, gross notional and policy limits.", "Use the residual ladder to see what the static hedge did not remove."],
    firstClick: "Barrier trade row",
  },
  {
    tab: "Hedge & Execute",
    kicker: "Live hedging loop",
    title: "Recommend, paper-execute and attribute a real hedge",
    body: "Sizes a lot-rounded futures hedge against the book's net delta off the live quote — add an option leg to hedge vega too. Executions land in the paper blotter, fold back into the desk's greeks and NAV, and survive restarts.",
    checks: ["Recommend with Δ override 0 to hedge the book's own delta; after executing, Book net Δ reflects the position — no double-hedging.", "Tick the option leg to run a delta-vega hedge; its greeks are priced off the desk model, not typed in.", "Arm the auto-hedger and it proposes (never executes) whenever |Δ| drifts past the threshold.", "Check the hedge P&L attribution: spread, fees, realized and marked-to-model unrealized."],
    firstClick: "Recommend button",
  },
  {
    tab: "Payoff Explorer",
    kicker: "Client view",
    title: "See a note the way the investor does",
    body: "Pick a product and terms, and get the payoff diagram, coupon schedule and plain-English outcome odds — the same engine as the desk price, worded for a non-quant.",
    checks: ["Sweep the terminal-level payoff to see where capital is protected and where it falls.", "Read the model-implied probabilities of loss and early redemption.", "Check the coupon schedule against the observation dates."],
    firstClick: "Product type selector",
  },
  {
    tab: "Option Chain",
    kicker: "Market data",
    title: "The chain the desk is calibrated on",
    body: "Nearest expiries, priced strikes and inverted implied vols — the raw market the vol surface, barrier radar and option hedges are all marked from.",
    checks: ["Scan IVs across strikes to see the smile the surface is fitted to.", "Compare CE vs PE vols at the same strike.", "Confirm the as-of stamp and data source match the masthead."],
    firstClick: "Any strike row",
  },
  {
    tab: "Broker",
    kicker: "Execution seam",
    title: "Paper desk vs real broker, reconciled",
    body: "Connectivity to the XTS interactive API, margins, and a position-by-position reconciliation of the paper blotter against what the broker actually holds.",
    checks: ["Check the connection state — without interactive credentials it says so explicitly.", "Compare paper vs broker quantity per instrument; differences are the desk's un-mirrored risk.", "Review cash and margin utilisation before sizing anything bigger."],
    firstClick: "Reconciliation table",
  },
  {
    tab: "Outcome Lab",
    kicker: "Outcomes",
    title: "Move from model values to realised-style evidence",
    body: "Synthetic issuance-cohort backtest, hedge comparison, and one client-to-desk case study tied back to the book. This is the ‘so what happened?’ section.",
    checks: ["Read the issuance-cohort backtest as a regime study, not real issued-note history.", "Compare unhedged, delta-only, semi-static and hybrid hedging.", "Use the case study to see coupon, hedge cost, XVA and decision outcome together."],
    firstClick: "Hedge comparison table",
  },
];

export function HowToUse({ onGo }: { onGo: (tab: string) => void }) {
  return (
    <div className="space-y-5">
      <Panel className="relative overflow-hidden p-5">
        <div className="absolute right-0 top-0 h-32 w-72 rounded-bl-full bg-accent/10 blur-2xl" />
        <div className="relative grid gap-5 lg:grid-cols-[1.15fr_0.85fr] lg:items-end">
          <div>
            <div className="text-label font-bold uppercase tracking-[0.16em] text-accent">First-time reviewer guide</div>
            <h2 className="mt-2 text-[1.8rem] font-extrabold tracking-tight text-ink">How to use this structuring desk</h2>
            <p className="mt-2 max-w-4xl text-body leading-relaxed text-muted">
              SPDT is a NIFTY structured-products digital twin: originate client notes, mark a 15-trade book, explain P&amp;L,
              inspect Greeks/stress, pass the same trades into CCR/XVA, validate model health, test semi-static barrier hedges,
              and review outcome-style evidence. On the live XTS feed it also runs a full hedging loop — delta/vega hedge
              tickets paper-executed against real quotes, a barrier radar, realized-vs-implied vol, and an intraday desk replay.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <button onClick={() => onGo("Overview")} className="ring-desk rounded-lg border border-accent/50 bg-accent/15 px-3 py-2 text-body font-semibold text-accent hover:bg-accent/25">
                Start with Overview →
              </button>
              <button onClick={() => onGo("Outcome Lab")} className="ring-desk rounded-lg border border-border bg-panel2/60 px-3 py-2 text-body font-semibold text-ink hover:border-teal/50">
                Jump to outcomes
              </button>
            </div>
          </div>
          <div className="rounded-xl border border-border bg-panel2/55 p-4">
            <div className="text-micro font-bold uppercase tracking-[0.12em] text-muted">Recommended review path</div>
            <div className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-small">
              {["Overview", "Originate", "Book & Risk", "Counterparty & XVA", "Validate", "Semi-Static Hedging", "Hedge & Execute", "Payoff Explorer", "Option Chain", "Broker", "Outcome Lab"].map((tab, i) => (
                <button key={tab} onClick={() => onGo(tab)} className="contents text-left">
                  <span className="tnum rounded border border-border bg-surface px-1.5 py-0.5 text-faint">{String(i + 1).padStart(2, "0")}</span>
                  <span className="text-muted hover:text-accent">{tab}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {TOUR_STEPS.map((step) => (
          <button
            key={step.tab}
            onClick={() => onGo(step.tab)}
            className="ring-desk group rounded-xl border border-border bg-panel2/35 p-4 text-left transition-colors hover:border-accent/55 hover:bg-panel2/70"
          >
            <div className="flex items-center justify-between gap-3">
              <span className="text-micro font-bold uppercase tracking-[0.12em] text-accent">{step.kicker}</span>
              <span className="text-small text-faint group-hover:text-accent">{step.tab} →</span>
            </div>
            <div className="mt-2 text-figure font-semibold text-ink">{step.title}</div>
            <p className="mt-2 text-small leading-relaxed text-muted">{step.body}</p>
            <div className="mt-3 border-t border-border-soft pt-3">
              <div className="text-micro font-bold uppercase tracking-[0.1em] text-muted">What to check</div>
              <ul className="mt-2 space-y-1.5">
                {step.checks.map((item) => (
                  <li key={item} className="flex gap-2 text-small leading-snug text-muted">
                    <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-accent/80" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-3 rounded-md border border-border-soft bg-surface/70 px-2.5 py-2 text-small text-faint">
                Good first click: <span className="font-semibold text-ink">{step.firstClick}</span>
              </div>
            </div>
          </button>
        ))}
      </div>

      <div className="rounded-lg border border-violet/25 bg-violet/[0.06] px-4 py-3 text-small leading-relaxed text-muted">
        <span className="font-semibold text-violet">Data boundary:</span> hosted mode uses synthetic NIFTY equity paths/surfaces unless a live/private data feed is supplied.
        Local mode can use the Bloomberg MIFOR workbook as a funding overlay; the app labels what is real versus synthetic in the masthead.
      </div>
    </div>
  );
}

/* ======================= Overview ======================= */

/** Realized (tick QV) vs implied (live ATM straddle) vol — hidden off the XTS feed. */
function VolTracker() {
  const [v, setV] = useState<VolTrackerData | null>(null);
  useEffect(() => {
    let dead = false;
    const load = () => void getVolTracker().then((r) => { if (!dead) setV(r); }).catch(() => { if (!dead) setV(null); });
    load();
    const id = setInterval(load, 30_000);
    return () => { dead = true; clearInterval(id); };
  }, []);
  if (!v || v.realized_vol == null) return null;
  const chart = v.series
    .filter((p) => p.rv != null)
    .map((p) => ({ time: p.t.slice(11, 16), realized: +(p.rv! * 100).toFixed(2), implied: p.iv != null ? +(p.iv * 100).toFixed(2) : null }));
  const volPct = (x: number | null | undefined) => (x == null ? "—" : `${fmt(x * 100, 2)}%`);
  return (
    <Panel className="p-3">
      <div className="flex items-baseline justify-between">
        <SectionTitle>Realized vs implied vol</SectionTitle>
        <span className="tnum text-[11px] text-muted">{v.n_samples} ticks · {fmt(v.window_minutes, 0)}m window · trading-clock annualized</span>
      </div>
      <div className="mb-3 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <GreekStat label="Realized (session)" value={volPct(v.realized_vol)} />
        <GreekStat label="Realized (30m)" value={volPct(v.realized_vol_30m)} />
        <GreekStat label="Implied ATM" value={volPct(v.implied_atm_vol)} />
        <GreekStat label="IV − RV" value={volPct(v.spread)} tone={v.spread != null && v.spread >= 0 ? "pos" : "neg"} />
        <GreekStat label="Γ carry / day" value={v.gamma_carry_per_day != null ? signed(v.gamma_carry_per_day, 0) : "—"}
          tone={v.gamma_carry_per_day != null && v.gamma_carry_per_day >= 0 ? "pos" : "neg"} />
      </div>
      {chart.length > 3 && (
        <Lines data={chart} x="time" height={220} yLabel="vol %"
          series={[{ key: "realized", name: "realized (trailing 30m)", color: C.teal }, { key: "implied", name: "implied ATM", color: C.accent }]} />
      )}
    </Panel>
  );
}

/** Intraday desk replay: every build and paper execution leaves a timeline row. */
function DeskTimeline() {
  const [rows, setRows] = useState<DeskHistoryRow[]>([]);
  useEffect(() => {
    let dead = false;
    const load = () => void getDeskHistory().then((r) => { if (!dead) setRows(r.rows); }).catch(() => {});
    load();
    const id = setInterval(load, 60_000);
    return () => { dead = true; clearInterval(id); };
  }, []);
  if (rows.length < 3) return null;
  const data = rows.map((r) => ({ time: r.t.slice(11, 16), nav: +r.nav.toFixed(1), spot: +r.spot.toFixed(0), delta: +r.delta.toFixed(1) }));
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Panel className="p-3">
        <SectionTitle>Desk replay · NAV</SectionTitle>
        <Lines data={data} x="time" height={200} series={[{ key: "nav", name: "NAV (incl. hedge P&L)", color: C.up }]} />
      </Panel>
      <Panel className="p-3">
        <SectionTitle>Desk replay · spot & net Δ</SectionTitle>
        <Lines data={data} x="time" height={200} series={[{ key: "spot", name: "spot", color: C.accent }, { key: "delta", name: "net Δ", color: C.teal }]} />
      </Panel>
    </div>
  );
}

export function Overview({ desk, onPickTrade }: { desk: Desk; onPickTrade: (id: string) => void }) {
  const e = desk.pnl_explain;
  const waterfall = [
    { name: "Delta", value: e.delta_pnl }, { name: "Gamma", value: e.gamma_pnl },
    { name: "Theta", value: e.theta_pnl }, { name: "Vega", value: e.vega_pnl },
    { name: "Vanna", value: e.vanna_pnl }, { name: "Residual", value: e.residual },
    { name: "Total", value: e.total, total: true },
  ];
  // Cash gamma (= Γ·S²·1%, the change in ₹-delta per 1% move) — raw ∂²PV/∂S² is ~0 at S≈22k.
  const gamma = [...desk.positions].sort((a, b) => a.gamma - b.gamma).slice(0, 8).map((p) => ({ trade: p.trade_id, gamma: p.gamma * desk.spot * desk.spot * 0.01 }));
  const movers = [...desk.pnl_by_trade].sort((a, b) => Math.abs(b.total) - Math.abs(a.total)).slice(0, 6);
  const worst = [...desk.stress].sort((a, b) => a.pnl - b.pnl);

  return (
    <div className="space-y-4">
      <VolTracker />
      <DeskTimeline />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel className="p-3 lg:col-span-2">
          <SectionTitle>Overnight P&L explain</SectionTitle>
          <Waterfall data={waterfall} height={300} />
          <div className="px-1 pt-1 text-[12px] text-muted">
            Residual <span className="tnum text-ink">{signed(e.residual, 4)}</span> of <span className="tnum text-ink">{signed(e.total, 4)}</span> — small ⇒ Greeks reconcile to full reval.
          </div>
        </Panel>
        <Panel className="p-3">
          <SectionTitle>Top movers (click to inspect)</SectionTitle>
          <div className="space-y-1">
            {movers.map((m) => (
              <button key={m.trade_id} onClick={() => onPickTrade(m.trade_id)}
                className="ring-desk flex w-full items-center justify-between rounded-lg border border-border-soft bg-panel2/40 px-3 py-2 text-left transition-colors hover:border-accent/50 hover:bg-panel2">
                <span className="tnum text-[12.5px] text-ink/90">{m.trade_id}</span>
                <span className={cn("tnum text-[12.5px] font-semibold", m.total >= 0 ? "text-up" : "text-down")}>{signed(m.total, 3)}</span>
              </button>
            ))}
          </div>
        </Panel>
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel className="p-3">
          <SectionTitle>Top gamma concentration · cash Γ /1%</SectionTitle>
          <Bars data={gamma} x="trade" y="gamma" color={C.down} height={300} horizontal yLabel="cash Γ /1%" />
        </Panel>
        <Panel className="p-3">
          <SectionTitle>Worst stress scenarios</SectionTitle>
          <Bars data={worst.map((s) => ({ scenario: s.scenario, pnl: s.pnl }))} x="scenario" y="pnl" height={300} horizontal colorBySign />
        </Panel>
      </div>
    </div>
  );
}

/* ======================= Originate ======================= */

const OBJECTIVES: { key: string; label: string; hint: string }[] = [
  { key: "income", label: "Income", hint: "a coupon, range-bound view, can take some downside" },
  { key: "yield_enhanced", label: "Yield +", hint: "the highest coupon, willing to sell more risk" },
  { key: "protection", label: "Protection", hint: "preserve capital first, upside second" },
];

export function Originate({ desk, onStage, volShiftPct = 0 }: { desk: Desk; onStage: (t: Trade) => void; volShiftPct?: number }) {
  const [tc, setTc] = useState(0.12);
  const [dd, setDd] = useState(0.3);
  const [mat, setMat] = useState(1);
  const [obs, setObs] = useState(4);
  const [fee, setFee] = useState(1);
  const [objective, setObjective] = useState("income");
  const [preferBasket, setPreferBasket] = useState(false);
  // The floor stated directly, the client's own deposit rate, and the mandate. Without these
  // the app could only infer a floor from the risk slider and funded it on the wholesale
  // curve, which is not how the note is actually built.
  const [floorPct, setFloorPct] = useState(0.9);
  const [fdRate, setFdRate] = useState(0.075);
  const [notionalCr, setNotionalCr] = useState(1);
  const [activeProduct, setActiveProduct] = useState<string | null>(null); // null ⇒ use the recommendation
  const [res, setRes] = useState<StructureResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [staged, setStaged] = useState(false);

  useEffect(() => {
    let cancel = false;
    setLoading(true);
    const id = setTimeout(() => {
      solveStructure({ target_coupon: tc, max_downside: dd, maturity: mat, obs_per_year: obs, fee, objective, prefer_basket: preferBasket, product: activeProduct,
        protection: objective === "protection" ? floorPct : null, fd_rate: fdRate, notional: notionalCr * 1e7 })
        .then((r) => !cancel && setRes(r)).finally(() => !cancel && setLoading(false));
    }, 250);
    return () => { cancel = true; clearTimeout(id); };
  }, [tc, dd, mat, obs, fee, objective, preferBasket, activeProduct, floorPct, fdRate, notionalCr]);

  // Changing the objective or basket appetite re-opens the recommendation (drops any manual override).
  function pickObjective(k: string) { setObjective(k); setActiveProduct(null); }
  function toggleBasket() { setPreferBasket((b) => !b); setActiveProduct(null); }

  function addToBook() {
    if (!res || (res.solved_annual_coupon == null && res.solved_participation == null)) return;
    const id = `STG-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
    onStage({
      trade_id: id, product_type: res.product_type, label: productLabel(res.product_type),
      notional: 100, observation_times: res.book_observation_times, maturity: res.book_maturity,
      staged: true, pv: res.achieved_pv ?? undefined, params: res.book_params,
    });
    setStaged(true);
    setTimeout(() => setStaged(false), 2200);
  }

  const curve = res?.pv_curve ?? [];
  const lo = curve.length ? Math.floor(Math.min(...curve.map((c) => c.pv))) : 90;
  const hi = curve.length ? Math.ceil(Math.max(...curve.map((c) => c.pv))) : 110;
  const isCoupon = res?.solve_for === "coupon";
  const solved = isCoupon ? res?.solved_annual_coupon : res?.solved_participation;
  const isRecommended = res != null && activeProduct == null;

  return (
    <div className="space-y-4">
      <SectionTitle>Client brief → recommended structure → solve to par → book</SectionTitle>
      <Panel className="space-y-4 p-4">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <div className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-[0.07em] text-muted">Client objective</div>
            <div className="flex gap-1 rounded-lg border border-border bg-panel2/50 p-1">
              {OBJECTIVES.map((o) => (
                <button key={o.key} onClick={() => pickObjective(o.key)} title={`Wants ${o.hint}`}
                  className={cn("ring-desk rounded-md px-3 py-1.5 text-[12px] font-semibold transition-colors", objective === o.key ? "bg-accent/20 text-accent" : "text-muted hover:text-ink")}>
                  {o.label}
                </button>
              ))}
            </div>
          </div>
          <button onClick={toggleBasket} title="Pitch a worst-of basket to fund a higher coupon"
            className={cn("ring-desk rounded-lg border px-3 py-2 text-[12px] font-semibold transition-colors", preferBasket ? "border-accent/60 bg-accent/15 text-accent" : "border-border text-muted hover:text-ink")}>
            {preferBasket ? "✓ " : ""}Open to a basket (worst-of)
          </button>
        </div>
        <div className="grid grid-cols-2 gap-5 md:grid-cols-5">
          <Slider label="Target annual coupon" value={tc} min={0.04} max={0.2} step={0.01} onChange={setTc} display={pct(tc, 0)} />
          <Slider label="Protection buffer" value={dd} min={0.1} max={0.5} step={0.05} onChange={setDd} display={`${pct(dd, 0)} → KI ${pct(1 - dd, 0)}`} />
          {/* Monthly steps, not yearly: NIFTY's listed expiries sit at 4, 7, 16 and 28 months,
              and a quarter-year step cannot land on any of them. */}
          <Slider label="Maturity" value={mat} min={1 / 12} max={3} step={1 / 12} onChange={setMat}
            display={mat < 1 ? `${Math.round(mat * 12)}m` : `${(mat).toFixed(2)}y`} />
          <Slider label="Observations / year" value={obs} min={2} max={12} step={2} onChange={setObs} display={`${obs}`} />
          <Slider label="Placement fee" value={fee} min={0} max={3} step={0.25} onChange={setFee} display={`${fee.toFixed(2)}`} />
        </div>
        {objective === "protection" && (
          <div className="grid grid-cols-2 gap-5 border-t border-border pt-4 md:grid-cols-3">
            <Slider label="Capital floor" value={floorPct} min={0.7} max={1} step={0.05} onChange={setFloorPct}
              display={`${pct(floorPct, 0)} — risks ${pct(1 - floorPct, 0)}`} />
            <Slider label="Client's own FD rate" value={fdRate} min={0.05} max={0.09} step={0.0025} onChange={setFdRate}
              display={pct(fdRate, 2)} />
            <Slider label="Mandate" value={notionalCr} min={0.25} max={10} step={0.25} onChange={setNotionalCr}
              display={`₹${notionalCr.toFixed(2)} Cr`} />
          </div>
        )}
      </Panel>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <Panel className="p-4 lg:col-span-2">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="text-[15px] font-bold text-ink">{res?.label ?? "—"}</span>
            {isRecommended && <span className="rounded border border-accent/50 bg-accent/10 px-1.5 py-0.5 text-micro font-bold uppercase tracking-wide text-accent">recommended</span>}
            {res != null && !isRecommended && <button onClick={() => setActiveProduct(null)} className="ring-desk text-micro text-muted hover:text-accent">↺ back to recommended</button>}
          </div>
          {res && <div className="mb-3 text-[12px] leading-relaxed text-muted">{res.rationale}</div>}
          {res && solved != null ? (
            <>
              <div className="text-small uppercase tracking-[0.1em] text-muted">Solved to par ({fee.toFixed(2)} fee)</div>
              <div className="tnum mt-1 text-hero font-bold leading-none text-ink">{res.solved_display}</div>
              <div className="mt-1.5 text-[12px] text-muted">
                {isCoupon && res.indicative_annual_coupon != null && <>vs indicative {pct(res.indicative_annual_coupon, 2)} · </>}
                model PV <span className="tnum text-ink">{fmt(res.achieved_pv ?? 0, 2)}</span>
                {res.knock_in != null && <> · KI {pct(res.knock_in, 0)}</>}
              </div>
              <div className={cn("mt-3 rounded-lg border px-3 py-2 text-[12px]", res.achievable ? "border-up/30 bg-up/5 text-up" : "border-down/30 bg-down/5 text-down")}>
                {isCoupon
                  ? (res.achievable ? `The client's ${pct(tc, 0)} ask is achievable at this structure.` : `The solved coupon is below the client's ${pct(tc, 0)} ask — they must sell more downside (a higher knock-in) or take a basket to fund it.`)
                  : `Priced to par at ${res.solved_display} on a ${pct(res.book_params.protection ?? 1, 0)} protected floor.`}
              </div>
              <button onClick={addToBook}
                className="ring-desk mt-3 w-full rounded-lg border border-accent/60 bg-accent/15 px-3 py-2 text-body font-semibold text-accent transition-colors hover:bg-accent/25">
                {staged ? "✓ Added to book" : "Add to book →"}
              </button>
            </>
          ) : (<div className="text-[13px] text-muted">{loading ? "Solving…" : "No parameter prices this to par."}</div>)}
        </Panel>
        <Panel className="p-3 lg:col-span-3">
          <AreaSpark data={curve} x="x" y="pv" color={C.teal} height={300} yDomain={[lo, hi]} xLabel={res?.x_label ?? ""} yLabel="model PV" yTickFormat={(v) => v.toFixed(0)} />
        </Panel>
      </div>

      {(res?.executable || res?.executable_error) && (
        <>
          <SectionTitle>What can actually be bought · live ask, whole lots, client's own deposit</SectionTitle>
          {res?.executable ? (
            <Panel className="p-4">
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div>
                  <div className="text-small uppercase tracking-[0.1em] text-muted">Executable participation</div>
                  <div className="tnum mt-1 text-hero font-bold leading-none text-accent">
                    {res.executable.participation.toFixed(2)}×
                  </div>
                  <div className="mt-1 text-[11.5px] text-muted">
                    against a model solve of {res.solved_display ?? "—"}
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <GreekStat label="Worst case" value={pct(res.executable.worst_case, 2)}
                    tone={res.executable.worst_case >= 0 ? "pos" : "neg"} />
                  <GreekStat label="Breakeven"
                    value={res.executable.capital_protected ? "protected"
                      : `${res.executable.breakeven_pct! >= 0 ? "+" : ""}${pct(res.executable.breakeven_pct!, 1)}`} />
                  <GreekStat label="Lots" value={`${res.executable.lots} × ${res.executable.lot_size}`} />
                  <GreekStat label="Bid-ask"
                    value={res.executable.relative_spread == null ? "—" : pct(res.executable.relative_spread, 1)} />
                </div>
              </div>
              <div className="mt-4 rounded-lg border border-border bg-panel2/60 p-3">
                <div className="text-[10.5px] font-semibold uppercase tracking-[0.07em] text-muted">The order</div>
                <div className="tnum mt-1.5 text-[13px] text-ink">
                  BUY {res.executable.lots} lots ({res.executable.units.toLocaleString("en-IN")} units) NIFTY{" "}
                  {res.executable.expiry} {res.executable.strike.toLocaleString("en-IN")} CE at the ask ₹
                  {res.executable.ask.toFixed(2)}
                </div>
                <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-[11.5px] text-muted sm:grid-cols-4">
                  <span>FD invested <span className="tnum text-ink">₹{Math.round(res.executable.fd_invested).toLocaleString("en-IN")}</span></span>
                  <span>matures to <span className="tnum text-ink">₹{Math.round(res.executable.fd_matures).toLocaleString("en-IN")}</span></span>
                  <span>option cost <span className="tnum text-ink">₹{Math.round(res.executable.option_cost).toLocaleString("en-IN")}</span></span>
                  <span>residual <span className="tnum text-ink">₹{Math.round(res.executable.residual).toLocaleString("en-IN")}</span></span>
                </div>
              </div>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-[11.5px]">
                  <thead>
                    <tr className="text-muted">
                      {res.executable.scenarios.map((sc) => (
                        <th key={sc.pct} className="tnum px-2 py-1 text-right font-semibold">
                          {sc.pct === 0 ? "flat" : `${sc.pct > 0 ? "+" : ""}${Math.round(sc.pct * 100)}%`}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      {res.executable.scenarios.map((sc) => (
                        <td key={sc.pct} className={cn("tnum px-2 py-1.5 text-right font-semibold",
                          sc.ret > 0 ? "text-up" : sc.ret < 0 ? "text-down" : "text-ink")}>
                          {sc.ret >= 0 ? "+" : ""}{pct(sc.ret, 2)}
                        </td>
                      ))}
                    </tr>
                  </tbody>
                </table>
                <div className="mt-1 text-[11px] text-muted">Client return on the mandate, by where NIFTY closes on {res.executable.expiry}.</div>
              </div>
            </Panel>
          ) : (
            <Panel className="p-4">
              <div className="text-[12.5px] text-muted">
                <span className="font-semibold text-ink">No orderable build.</span> {res?.executable_error}
              </div>
            </Panel>
          )}
        </>
      )}

      <SectionTitle>Alternatives the desk could pitch · ranked by fit</SectionTitle>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {(res?.alternatives ?? []).map((c) => {
          const active = c.product_type === res?.product_type;
          return (
            <button key={c.product_type} onClick={() => setActiveProduct(c.product_type)}
              className={cn("ring-desk rounded-xl border p-3 text-left transition-colors", active ? "border-accent/60 bg-accent/10" : "border-border bg-panel2/40 hover:border-accent/40")}>
              <div className="flex items-center justify-between">
                <span className={cn("text-[12.5px] font-semibold", active ? "text-accent" : "text-ink")}>{c.label}</span>
                <span className="tnum text-[11px] text-muted">fit {pct(c.fit_score, 0)}</span>
              </div>
              <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-border">
                <div className="h-full rounded-full" style={{ width: `${Math.round(c.fit_score * 100)}%`, background: active ? C.accent : C.muted }} />
              </div>
              <div className="mt-2 line-clamp-3 text-[11px] leading-snug text-muted">{c.rationale}</div>
            </button>
          );
        })}
      </div>

      <SectionTitle>Income / protection catalog · two-curve discounting</SectionTitle>
      <p className="mb-2 max-w-3xl text-[11.5px] leading-snug text-muted">
        A structured note is the issuer's unsecured funding, so its bond-like legs discount on the funding curve (OIS + spread), not OIS. <span className="text-ink">PV (OIS + funding)</span> is the correct all-in price; <span className="text-ink">PV (OIS only)</span> is the naïve price ignoring funding; <span className="text-ink">Funding impact</span> is the difference — the (negative) dent the issuer's funding cost puts in the note's value.
      </p>
      <Panel className="p-0">
        <DataTable rows={desk.catalog} max={260} cols={[
          { key: "name", label: "Structure" },
          { key: "pv_two_curve", label: "PV (OIS + funding)", align: "right", fmt: (r) => fmt(r.pv_two_curve, 3) },
          { key: "pv_ois_only", label: "PV (OIS only)", align: "right", fmt: (r) => fmt(r.pv_ois_only, 3) },
          { key: "funding_impact", label: "Funding impact", align: "right", fmt: (r) => signed(r.funding_impact, 3), className: (r) => (r.funding_impact >= 0 ? "text-up" : "text-down") },
        ]} />
      </Panel>

      <SectionTitle>Implied-vol surface · SSVI (arb-free)</SectionTitle>
      <Panel className="p-2">
        <Surface3D z={desk.surface.iv} x={desk.surface.log_moneyness} y={desk.surface.tenors} height={460} zShift={volShiftPct} />
      </Panel>
    </div>
  );
}

/* ======================= Trade detail (live price) ======================= */

export function TradeDetail({ trade, desk }: { trade: Trade; desk: Desk }) {
  const isWO = trade.product_type === "worst_of";
  const [r, setR] = useState<PriceResult | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancel = false;
    if (isWO) {
      setLoading(false);
      setR(null);
      return;
    }
    setLoading(true);
    setR(null);
    priceTrade(priceReq(trade)).then((res) => !cancel && setR(res)).finally(() => !cancel && setLoading(false));
    return () => { cancel = true; };
  }, [trade.trade_id]);

  const reserve = desk.reserves.find((x) => x.trade_id === trade.trade_id);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <span className="tnum text-[15px] font-semibold text-ink">{trade.trade_id}</span>
          <span className="ml-2 text-[12px] text-muted">{trade.label}</span>
          {trade.staged && <span className="ml-2 rounded border border-violet/50 bg-violet/10 px-1.5 py-0.5 text-micro font-bold uppercase tracking-wide text-violet">staged</span>}
        </div>
        <span className="tnum text-[12px] text-muted">{isWO ? `PV ${fmt(trade.pv ?? 0, 3)}` : loading ? "pricing…" : `PV ${fmt(r?.pv ?? 0, 3)} ± ${fmt(r?.std_error ?? 0, 3)}`}</span>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <Chip>{trade.maturity.toFixed(2)}y</Chip>
        {trade.params.coupon_rate != null && <Chip>coupon {fmt(trade.params.coupon_rate * 100, 2)}%</Chip>}
        {trade.params.knock_in != null && <Chip>KI {pct(trade.params.knock_in, 0)}</Chip>}
        {trade.params.autocall_level != null && <Chip>AC {pct(trade.params.autocall_level, 0)}</Chip>}
        {trade.params.protection != null && <Chip>protection {pct(trade.params.protection, 0)}</Chip>}
        {trade.params.participation != null && <Chip>{fmt(trade.params.participation, 2)}× upside</Chip>}
        {trade.params.memory && <Chip hot>memory</Chip>}
        {isWO && (trade.params.underlyings ?? []).map((u: string) => <Chip key={u}>{u}</Chip>)}
        {isWO && trade.params.correlation != null && <Chip hot>ρ {fmt(trade.params.correlation, 2)}</Chip>}
      </div>

      {isWO && (
        <>
          <div className="grid grid-cols-4 gap-2">
            <GreekStat label="Δ / 1%" value={signed((trade.delta ?? 0) * desk.spot * 0.01, 2)} tone={(trade.delta ?? 0) >= 0 ? "pos" : "neg"} />
            <GreekStat label="cash Γ /1%" value={fmt((trade.gamma ?? 0) * desk.spot * desk.spot * 0.01, 2)} />
            <GreekStat label="ν / pt" value={signed((trade.vega ?? 0) / 100, 2)} tone={(trade.vega ?? 0) >= 0 ? "pos" : "neg"} />
            <GreekStat label="corr Δ" value={fmt(trade.params.corr_delta ?? 0, 2)} tone={(trade.params.corr_delta ?? 0) >= 0 ? "pos" : "neg"} />
          </div>
          <div className="rounded-lg border border-border-soft bg-panel2/40 px-3 py-2 text-[12px] text-muted">
            Worst-of on {(trade.params.underlyings ?? []).length} names at ρ {fmt(trade.params.correlation ?? 0, 2)} — the desk pays a higher coupon because the investor is short the basket's dispersion. <span className="tnum text-accent">corr Δ {fmt(trade.params.corr_delta ?? 0, 2)}</span> is the value change per +5 correlation points; see the <span className="text-ink">corr_breakdown</span> stress in Validate.
          </div>
        </>
      )}

      {r && (
        <>
          <div className="grid grid-cols-4 gap-2">
            <GreekStat label="Δ / 1%" value={signed(r.greeks.cash_delta, 2)} tone={r.greeks.cash_delta >= 0 ? "pos" : "neg"} />
            <GreekStat label="cash Γ /1%" value={fmt(r.greeks.gamma * desk.spot * desk.spot * 0.01, 2)} />
            <GreekStat label="ν / pt" value={signed(r.greeks.vega_pt, 2)} tone={r.greeks.vega_pt >= 0 ? "pos" : "neg"} />
            <GreekStat label="ρ" value={fmt(r.greeks.rho, 1)} />
          </div>

          <div>
            <SectionTitle>Scenario at maturity</SectionTitle>
            <DataTable rows={r.scenarios} max={240} cols={[
              { key: "terminal_level", label: "Final level", fmt: (s) => pct(s.terminal_level, 0) },
              { key: "ki_breached", label: "Knock-in", fmt: (s) => (s.ki_breached ? "breached" : "safe"), className: (s) => (s.ki_breached ? "text-down" : "text-up") },
              { key: "payment_pct", label: "Payment", align: "right", fmt: (s) => `${fmt(s.payment_pct, 1)}%`, className: (s) => (s.payment_pct < 100 ? "text-down" : "text-ink/90") },
            ]} />
          </div>

          <div>
            <SectionTitle>Stress impact · this trade</SectionTitle>
            <Bars data={r.stress.map((s) => ({ scenario: s.scenario, pnl: s.pnl }))} x="scenario" y="pnl" height={220} horizontal colorBySign />
          </div>

          <div className="rounded-lg border border-border-soft bg-panel2/40 px-3 py-2 text-[12px] text-muted">
            {reserve ? (
              <>Model reserve <span className="tnum text-accent">{fmt(reserve.lsv_minus_lv, 3)}</span> (LSV−LV) · bid-offer <span className="tnum text-ink">{fmt(reserve.bid_offer, 3)}</span> · LV {fmt(reserve.lv_pv, 2)} / LSV {fmt(reserve.lsv_pv, 2)}</>
            ) : (<>Staged trade — reserves computed once booked.</>)}
          </div>
        </>
      )}
    </div>
  );
}

/* ======================= Book & Risk (master-detail) ======================= */

interface MarketCtx {
  dS: number;
  dVol: number;
  liveSpot: number;
  sim: boolean;
}

function Blotter({ trades, selectedId, onSelect, tenorFilter, onClearFilter, mk }: {
  trades: Trade[]; selectedId: string | null; onSelect: (id: string) => void; tenorFilter: string | null; onClearFilter: () => void; mk: MarketCtx;
}) {
  const shown = tenorFilter ? trades.filter((t) => `${t.maturity.toFixed(1)}y` === tenorFilter) : trades;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <SectionTitle>Blotter · {shown.length} notes</SectionTitle>
        {tenorFilter && (
          <button onClick={onClearFilter} className="ring-desk text-small text-accent hover:underline">filter: {tenorFilter} ✕</button>
        )}
      </div>
      <div className="overflow-auto rounded-xl border border-border" style={{ maxHeight: 560 }}>
        <table className="w-full border-collapse text-[12px]">
          <thead className="sticky top-0 z-10 bg-panel2">
            <tr>{["Trade", "Type", "Mat", "PV", "Δ/1%", "ν/pt", "P&L"].map((h, i) => (
              <th key={h} className={cn("border-b border-border px-2.5 py-2 text-[10px] font-bold uppercase tracking-[0.05em] text-muted", i >= 3 ? "text-right" : "text-left")}>{h}</th>
            ))}</tr>
          </thead>
          <tbody>
            {shown.map((t) => {
              const sel = t.trade_id === selectedId;
              // Re-mark each row through its own greeks on the tick (PV ticks like the book NAV;
              // Δ shown as cash per +1% spot, the desk-meaningful figure rather than raw ∂PV/∂S).
              const live = mk.sim && t.delta != null;
              const dMark = live ? (t.delta ?? 0) * mk.dS + 0.5 * (t.gamma ?? 0) * mk.dS * mk.dS + (t.vega ?? 0) * mk.dVol + (t.vanna ?? 0) * mk.dS * mk.dVol : 0;
              const pvLive = t.pv != null ? t.pv + dMark : null;
              const cashD = t.delta != null ? ((t.delta ?? 0) + (live ? (t.gamma ?? 0) * mk.dS + (t.vanna ?? 0) * mk.dVol : 0)) * mk.liveSpot * 0.01 : null;
              const vegaLive = t.vega != null ? (t.vega + (live ? (t.vanna ?? 0) * mk.dS + (t.volga ?? 0) * mk.dVol : 0)) / 100 : null;
              const pnlLive = t.day_pnl != null ? t.day_pnl + dMark : null;
              return (
                <tr key={t.trade_id} onClick={() => onSelect(t.trade_id)} tabIndex={0}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(t.trade_id))}
                  className={cn("ring-desk cursor-pointer transition-colors", sel ? "bg-accent/10" : "hover:bg-white/[0.03]")}>
                  <td className={cn("tnum border-b border-border-soft px-2.5 py-1.5", sel ? "text-accent" : "text-ink/90", t.staged && "italic")}>{t.trade_id}</td>
                  <td className="border-b border-border-soft px-2.5 py-1.5 text-small text-muted">
                    {TYPE_ABBR[t.product_type] ?? t.product_type}{t.staged && <span className="ml-1 text-violet">•</span>}
                  </td>
                  <td className="tnum border-b border-border-soft px-2.5 py-1.5 text-right text-ink/80">{t.maturity.toFixed(1)}y</td>
                  <td className="tnum border-b border-border-soft px-2.5 py-1.5 text-right text-ink/80">{pvLive != null ? fmt(pvLive, 2) : "—"}</td>
                  <td className={cn("tnum border-b border-border-soft px-2.5 py-1.5 text-right", (cashD ?? 0) >= 0 ? "text-up/90" : "text-down/90")}>{cashD != null ? signed(cashD, 2) : "—"}</td>
                  <td className={cn("tnum border-b border-border-soft px-2.5 py-1.5 text-right", (vegaLive ?? 0) >= 0 ? "text-up/90" : "text-down/90")}>{vegaLive != null ? signed(vegaLive, 2) : "—"}</td>
                  <td className={cn("tnum border-b border-border-soft px-2.5 py-1.5 text-right", (pnlLive ?? 0) >= 0 ? "text-up/90" : "text-down/90")}>{pnlLive != null ? signed(pnlLive, 2) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BookAggregate({ desk, onPickTenor, mk }: { desk: Desk; onPickTenor: (b: string) => void; mk: MarketCtx }) {
  // Live per-trade vega (vanna·dS + volga·dσ), aggregated into the ladder and net figures.
  const liveVega = (p: any) => p.vega + (mk.sim ? (p.vanna ?? 0) * mk.dS + (p.volga ?? 0) * mk.dVol : 0);
  const ladderMap: Record<string, number> = {};
  for (const p of desk.positions) {
    const k = `${p.maturity.toFixed(1)}y`;
    ladderMap[k] = (ladderMap[k] ?? 0) + liveVega(p) / 100;
  }
  const ladder = Object.entries(ladderMap)
    .sort((a, b) => parseFloat(a[0]) - parseFloat(b[0]))
    .map(([bucket, vega]) => ({ bucket, vega }));
  const gamma = [...desk.positions].sort((a, b) => a.gamma - b.gamma).map((p) => ({ trade: p.trade_id, gamma: p.gamma * desk.spot * desk.spot * 0.01 }));
  const g = desk.net_greeks;
  const netDelta = desk.positions.reduce((a, p) => a + p.delta + (mk.sim ? p.gamma * mk.dS + (p.vanna ?? 0) * mk.dVol : 0), 0);
  const netVega = desk.positions.reduce((a, p) => a + liveVega(p), 0);
  return (
    <div className="space-y-4">
      <Panel className="p-3">
        <SectionTitle>Vega ladder by tenor · click a bucket to filter the blotter</SectionTitle>
        <Bars data={ladder} x="bucket" y="vega" color={C.teal} height={260} yLabel="vega / vol pt" />
        <div className="mt-2 flex flex-wrap gap-1.5">
          {ladder.map((l) => (
            <button key={l.bucket} onClick={() => onPickTenor(l.bucket)} className="ring-desk rounded-full border border-border bg-panel2 px-2.5 py-0.5 text-small text-muted hover:border-teal hover:text-teal">{l.bucket}</button>
          ))}
        </div>
      </Panel>
      <Panel className="p-3">
        <SectionTitle>Gamma concentration · cash Γ /1%</SectionTitle>
        <Bars data={gamma} x="trade" y="gamma" color={C.down} height={300} horizontal yLabel="cash Γ /1%" />
      </Panel>
      {desk.correlation_risk.baskets.length > 0 && (
        <Panel className="p-3">
          <SectionTitle>Correlation risk · worst-of sub-book</SectionTitle>
          <Bars
            data={desk.correlation_risk.baskets.map((b) => ({ basket: b.trade_id, corr_delta: b.corr_delta }))}
            x="basket" y="corr_delta" height={200} horizontal colorBySign
          />
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Chip hot>net corr Δ {fmt(desk.correlation_risk.net_corr_delta, 2)}</Chip>
            {desk.correlation_risk.baskets.map((b) => (
              <Chip key={b.trade_id}>{b.trade_id} · {b.underlyings.map((u) => u.slice(0, 4)).join("/")} · ρ {fmt(b.correlation, 2)}</Chip>
            ))}
          </div>
          <div className="mt-2 text-[12px] text-muted">
            Value change per +5 correlation points, per basket — the dispersion the desk is short. Sign varies by structure (a high-coupon memory autocallable can fall as names converge); the <span className="text-ink">corr_breakdown</span> stress aggregates the ρ→0.9 P&L.
          </div>
        </Panel>
      )}
      <div className="flex flex-wrap gap-1.5">
        <Chip>net Δ {fmt(netDelta, 4)}</Chip><Chip>net cash Γ/1% {fmt(g.gamma * desk.spot * desk.spot * 0.01, 2)}</Chip>
        <Chip>net ν {fmt(netVega, 1)}</Chip><Chip>net ρ {fmt(g.rho, 1)}</Chip>
        <Chip hot={!desk.hedge_capacity.within_capacity}>
          hedge {desk.hedge_capacity.days_to_hedge < 0.1 ? "<0.1" : fmt(desk.hedge_capacity.days_to_hedge, 1)}d @ {pct(desk.hedge_capacity.participation, 0)} ADV
        </Chip>
      </div>
    </div>
  );
}

export function BookRisk({ desk, trades, selectedId, setSelectedId, tenorFilter, setTenorFilter, mk }: {
  desk: Desk; trades: Trade[]; selectedId: string | null; setSelectedId: (id: string | null) => void;
  tenorFilter: string | null; setTenorFilter: (b: string | null) => void; mk: MarketCtx;
}) {
  const selected = trades.find((t) => t.trade_id === selectedId) ?? null;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="lg:col-span-2">
          <Blotter trades={trades} selectedId={selectedId} onSelect={(id) => setSelectedId(id === selectedId ? null : id)} tenorFilter={tenorFilter} onClearFilter={() => setTenorFilter(null)} mk={mk} />
        </div>
        <Panel className="p-4 lg:col-span-3">
          {selected ? (
            <TradeDetail trade={selected} desk={desk} />
          ) : (
            <BookAggregate desk={desk} onPickTenor={setTenorFilter} mk={mk} />
          )}
        </Panel>
      </div>
      <BarrierRadar liveSpot={mk.liveSpot} />
    </div>
  );
}

/** Barrier proximity radar — re-ranked against the live (or simulated) spot every 30s. */
function BarrierRadar({ liveSpot }: { liveSpot: number }) {
  const [radar, setRadar] = useState<Awaited<ReturnType<typeof getRadar>> | null>(null);
  const spotRef = useRef(liveSpot);
  spotRef.current = liveSpot;
  useEffect(() => {
    let dead = false;
    const load = () => void getRadar(spotRef.current).then((r) => { if (!dead) setRadar(r); }).catch(() => {});
    load();
    const id = setInterval(load, 30_000);
    return () => { dead = true; clearInterval(id); };
  }, []);
  if (!radar || radar.rows.length === 0) return null;
  const pct = (v?: number) => (v == null ? "—" : `${fmt(v, 1)}%`);
  return (
    <Panel className="p-0">
      <div className="flex items-baseline justify-between px-3 pt-3">
        <SectionTitle>Barrier radar</SectionTitle>
        <span className="tnum text-[11px] text-muted">@ spot {fmt(radar.spot, 0)} · model-implied, continuous monitoring</span>
      </div>
      <DataTable
        rows={radar.rows}
        cols={[
          { key: "trade_id", label: "Note" },
          { key: "product_type", label: "Type", fmt: (r) => TYPE_ABBR[r.product_type] ?? r.product_type },
          { key: "ki_level", label: "KI level", align: "right", fmt: (r) => (r.ki_level != null ? fmt(r.ki_level, 0) : "—") },
          { key: "ki_distance_pct", label: "KI dist", align: "right", fmt: (r) => pct(r.ki_distance_pct) },
          { key: "ki_sigma_distance", label: "σ away", align: "right", fmt: (r) => (r.ki_sigma_distance != null ? fmt(r.ki_sigma_distance, 1) : "—") },
          {
            key: "ki_hit_prob_pct", label: "P(touch KI)", align: "right",
            fmt: (r) => pct(r.ki_hit_prob_pct),
            className: (r) => (r.severity === "CRITICAL" ? "text-down" : r.severity === "WARNING" ? "text-accent" : ""),
          },
          { key: "next_obs_days", label: "Next obs", align: "right", fmt: (r) => (r.next_obs_days != null ? `${r.next_obs_days}d` : "—") },
          { key: "autocall_prob_pct", label: "P(autocall)", align: "right", fmt: (r) => pct(r.autocall_prob_pct) },
          {
            key: "severity", label: "", align: "right",
            fmt: (r) => <span className={`rounded border px-1.5 py-0.5 text-[10px] font-bold ${SEVERITY_TONE[r.severity]}`}>{r.severity}</span>,
          },
        ]}
      />
    </Panel>
  );
}

/* ======================= Validate ======================= */

/** Taylor-vs-full-reval residual: how far the greeks' explanation stretches, on demand. */
function ResidualMonitor() {
  const [spotPct, setSpotPct] = useState(2);
  const [dvolPt, setDvolPt] = useState(0.3);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<ResidualResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setRes(await getResidual(1 + spotPct / 100, dvolPt / 100));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel className="p-3">
      <SectionTitle>Taylor vs full reval</SectionTitle>
      <p className="mb-3 text-[12px] leading-relaxed text-muted">
        Re-prices every booked note at a shifted market (same MC seed, so the difference is clean) and
        compares against the greeks' Taylor prediction. The residual is what Δ/Γ/ν cannot explain.
      </p>
      <div className="mb-3 grid grid-cols-3 gap-3">
        <NumField label="Spot move %" value={spotPct} onChange={setSpotPct} />
        <NumField label="Vol move (pts)" value={dvolPt} onChange={setDvolPt} />
        <div className="flex items-end">
          <button onClick={() => void run()} disabled={busy}
            className="ring-desk w-full rounded-lg border border-teal/60 bg-teal/10 px-4 py-1.5 text-[12px] font-bold uppercase tracking-[0.1em] text-teal transition-colors hover:bg-teal/20 disabled:opacity-40">
            {busy ? "Repricing…" : "Run full reval"}
          </button>
        </div>
      </div>
      {error && <p className="text-[12px] text-down" role="alert">{error}</p>}
      {res && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
          <GreekStat label="Δ term" value={signed(res.terms.delta, 2)} />
          <GreekStat label="½Γ term" value={signed(res.terms.gamma, 2)} />
          <GreekStat label="ν term" value={signed(res.terms.vega, 2)} />
          <GreekStat label="Taylor total" value={signed(res.predicted, 2)} />
          <GreekStat label="Full reval" value={signed(res.actual, 2)} />
          <GreekStat label="Residual" value={signed(res.residual, 2)}
            tone={Math.abs(res.residual) <= 0.1 * Math.max(Math.abs(res.actual), 1e-9) ? "pos" : "neg"} />
        </div>
      )}
      {res && <p className="mt-2 text-[11px] text-muted">{res.n_notes} notes · {res.n_paths.toLocaleString()} paths · {res.note}</p>}
    </Panel>
  );
}

export function Validate({ desk, selectedId }: { desk: Desk; selectedId: string | null }) {
  const rows = [...desk.reserves].sort((a, b) => b.lsv_minus_lv - a.lsv_minus_lv);
  const b = desk.backtest;
  return (
    <div className="space-y-5">
      <ResidualMonitor />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <Panel className="p-0 lg:col-span-2">
          <div className="px-3 pt-3"><SectionTitle>Model reserves · LSV − LV</SectionTitle></div>
          <DataTable rows={rows} max={300} cols={[
            { key: "trade_id", label: "Trade" },
            { key: "lv_pv", label: "LV", align: "right", fmt: (r) => fmt(r.lv_pv, 2) },
            { key: "lsv_pv", label: "LSV", align: "right", fmt: (r) => fmt(r.lsv_pv, 2) },
            { key: "lsv_minus_lv", label: "LSV−LV", align: "right", fmt: (r) => fmt(r.lsv_minus_lv, 3), className: () => "text-accent" },
          ]} />
        </Panel>
        <Panel className="p-3 lg:col-span-3">
          <SectionTitle>Reserve by trade</SectionTitle>
          <Bars data={rows.map((r) => ({ trade: r.trade_id, reserve: r.lsv_minus_lv }))} x="trade" y="reserve" color={C.accent} height={300} horizontal />
          <div className="px-1 pt-1 text-[12px] text-muted">Total LSV−LV reserve <span className="tnum text-ink">{fmt(desk.total_model_reserve, 2)}</span> · bid-offer <span className="tnum text-ink">{fmt(desk.total_reserve, 2)}</span>.</div>
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel className="p-3">
          <SectionTitle>Coherent stress · {selectedId ? selectedId : "book"}</SectionTitle>
          <Bars
            data={(selectedId
              ? desk.stress.map((s) => ({ scenario: s.scenario, pnl: desk.stress_by_trade[s.scenario]?.[selectedId] ?? 0 }))
              : desk.stress.map((s) => ({ scenario: s.scenario, pnl: s.pnl }))
            )}
            x="scenario" y="pnl" height={300} horizontal colorBySign />
          <div className="px-1 pt-1 text-[12px] text-muted">Multi-factor shocks (a crash also spikes vol). {selectedId ? "Showing the selected trade's contribution." : "Select a trade in Book & Risk to decompose."}</div>
        </Panel>
        <Panel className="p-3">
          <SectionTitle>Hedge error vs gap risk</SectionTitle>
          <Lines
            data={desk.hedging}
            x="n_steps"
            logX
            xLabel="rebalances"
            yLabel="hedging P&L (₹)"
            series={[
              { key: "std_pnl", name: "diffusion error (std)", color: C.teal },
              { key: "tail_gap", name: "gap-loss tail (5%)", color: C.down },
            ]}
            height={300}
          />
          <div className="px-1 pt-1 text-[12px] text-muted">
            Rebalancing more tightens the <span className="text-teal">diffusion error</span> (~1/√N) but leaves the <span className="text-down">overnight gap-loss tail</span> ~flat — gap risk can't be delta-hedged away, the structural tail of a short-gamma autocallable book.
          </div>
        </Panel>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Kpi label="Autocall rate" value={pct(b.autocall_rate, 0)} sub={`${b.n_issuances} issuances`} />
        <Kpi label="Mean return" value={pct(b.mean_total_return, 1)} sub="of notional" />
        <Kpi label="Loss rate" value={pct(b.loss_rate, 0)} sub="capital loss" tone={b.loss_rate > 0 ? "neg" : "pos"} />
        <Kpi label="Mean loss" value={fmt(b.mean_capital_loss, 1)} sub="when lost" tone="neg" />
        <Kpi label="Worst 5%" value={pct(b.worst_5pct_return, 0)} sub="tail return" tone="neg" />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <Panel className="p-3 lg:col-span-3">
          <SectionTitle>Backtest · per-issuance return distribution</SectionTitle>
          <Histogram values={b.returns} bins={40} color={C.teal} height={280} />
        </Panel>
        <Panel className="p-3 lg:col-span-2">
          <SectionTitle>Realised underlying (10y)</SectionTitle>
          <AreaSpark data={b.series.map((v: number, i: number) => ({ m: i, level: v }))} x="m" y="level" color={C.accent} height={280} xLabel="month" />
        </Panel>
      </div>
    </div>
  );
}

/* ======================= Counterparty & XVA ======================= */

// The integration seam handles single-asset notes; worst-of baskets aren't wired to the tab yet.
const XVA_PRODUCTS = new Set(["autocallable", "brc", "reverse_convertible", "capital_protected"]);

// Round axis ticks (0, 0.25, 0.5, …) for the exposure profile — the compute grid lands on odd
// fractions (0.1125, 0.3375, …), so we label by clean intervals rather than one tick per point.
function timeTicks(maxT: number): number[] {
  const step = maxT <= 1.6 ? 0.25 : maxT <= 3.2 ? 0.5 : 1.0;
  const out: number[] = [];
  for (let t = 0; t <= maxT + 1e-9; t += step) out.push(+t.toFixed(2));
  return out;
}

const DECISION_STYLE: Record<Decision, { cls: string; text: string; dot: string; label: string }> = {
  APPROVED: { cls: "border-up/40 bg-up/10", text: "text-up", dot: "bg-up", label: "Approved" },
  REJECTED: { cls: "border-down/40 bg-down/10", text: "text-down", dot: "bg-down", label: "Rejected" },
  MANUAL_REVIEW: { cls: "border-accent/40 bg-accent/10", text: "text-accent", dot: "bg-accent", label: "Manual review" },
};

function Toggle({ label, on, onClick }: { label: string; on: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "ring-desk rounded-lg border px-3 py-2 text-[12px] font-semibold transition-colors",
        on ? "border-accent/60 bg-accent/15 text-accent" : "border-border bg-panel2 text-muted hover:text-ink",
      )}
    >
      {on ? "● " : "○ "}{label}
    </button>
  );
}

export function CounterpartyXva({ trades, selectedId }: { trades: Trade[]; selectedId: string | null }) {
  const eligible = trades.filter((t) => XVA_PRODUCTS.has(t.product_type));
  const [tradeId, setTradeId] = useState<string | null>(null);
  const [cds, setCds] = useState(200);
  const [rec, setRec] = useState(0.4);
  const [fund, setFund] = useState(50);
  const [hurdle, setHurdle] = useState(0.1);
  const [margin, setMargin] = useState(1.0);
  const [eadLimit, setEadLimit] = useState(0); // 0 ⇒ no limit
  // XVA depth knobs
  const [ownCds, setOwnCds] = useState(0); // 0 ⇒ no DVA
  const [coc, setCoc] = useState(0); // cost of capital; 0 ⇒ no KVA
  const [wwr, setWwr] = useState(0); // wrong-way-risk tilt
  const [mva, setMva] = useState(false);
  const [collat, setCollat] = useState(false);
  const [res, setRes] = useState<XvaResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Default to the desk-selected note when it's chargeable, else the first eligible one.
  const activeId =
    tradeId && eligible.some((t) => t.trade_id === tradeId)
      ? tradeId
      : selectedId && eligible.some((t) => t.trade_id === selectedId)
        ? selectedId
        : eligible[0]?.trade_id ?? null;
  const trade = eligible.find((t) => t.trade_id === activeId) ?? null;

  useEffect(() => {
    if (!trade) { setRes(null); return; }
    let cancel = false;
    setLoading(true);
    setErr(null);
    const id = setTimeout(() => {
      computeXva({
        product_type: trade.product_type, notional: trade.notional,
        observation_times: trade.observation_times, maturity: trade.maturity, params: trade.params,
        counterparty: "CP-0", cds_spread_bps: cds, recovery_rate: rec, funding_spread_bp: fund,
        hurdle_rate: hurdle, margin, ead_limit: eadLimit > 0 ? eadLimit : undefined,
        own_cds_bps: ownCds > 0 ? ownCds : undefined, cost_of_capital: coc, wwr_beta: wwr,
        include_mva: mva, collateralised: collat, single_name: true,
      })
        .then((r) => !cancel && setRes(r))
        .catch((e) => !cancel && setErr(String(e)))
        .finally(() => !cancel && setLoading(false));
    }, 250);
    return () => { cancel = true; clearTimeout(id); };
  }, [activeId, cds, rec, fund, hurdle, margin, eadLimit, ownCds, coc, wwr, mva, collat]);

  if (eligible.length === 0)
    return <div className="text-[13px] text-muted">No single-asset notes in the book to charge — worst-of baskets aren't wired to the XVA tab yet.</div>;

  const ds = res ? DECISION_STYLE[res.decision] : null;
  const ccyPct = (v: number) => (trade ? pct(v / trade.notional, 2) : "—");

  return (
    <div className="space-y-4">
      <SectionTitle>Per-trade XVA charge → counterparty limits → RAROC → governance decision</SectionTitle>

      <Panel className="p-4">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <span className="text-[10.5px] font-semibold uppercase tracking-[0.07em] text-muted">Note</span>
          <select
            value={activeId ?? ""}
            onChange={(e) => setTradeId(e.target.value)}
            className="ring-desk rounded-lg border border-border bg-panel2 px-3 py-1.5 text-[13px] text-ink"
          >
            {eligible.map((t) => (
              <option key={t.trade_id} value={t.trade_id}>
                {t.trade_id} · {productLabel(t.product_type)} · {t.maturity.toFixed(1)}y
              </option>
            ))}
          </select>
          {trade?.staged && <Chip hot>staged</Chip>}
        </div>
        <div className="grid grid-cols-2 gap-5 md:grid-cols-3 lg:grid-cols-6">
          <Slider label="Counterparty CDS" value={cds} min={25} max={800} step={25} onChange={setCds} display={`${cds}bp`} />
          <Slider label="Recovery rate" value={rec} min={0.2} max={0.7} step={0.05} onChange={setRec} display={pct(rec, 0)} />
          <Slider label="XVA funding scenario" value={fund} min={0} max={150} step={10} onChange={setFund} display={`${fund}bp`} />
          <Slider label="RAROC hurdle" value={hurdle} min={0.05} max={0.25} step={0.01} onChange={setHurdle} display={pct(hurdle, 0)} />
          <Slider label="Structuring margin" value={margin} min={0} max={6} step={0.25} onChange={setMargin} display={fmt(margin, 2)} />
          <Slider label="EAD limit (0=off)" value={eadLimit} min={0} max={400} step={10} onChange={setEadLimit} display={eadLimit > 0 ? fmt(eadLimit, 0) : "off"} />
        </div>
        <div className="mt-4 border-t border-border-soft pt-4">
          <div className="mb-3 rounded-md border border-border-soft bg-panel2/60 px-3 py-2 text-[12px] text-muted">
            The funding slider is the XVA/FVA scenario spread for this hedge counterparty run. It is separate from the masthead's issuer funding overlay.
          </div>
          <div className="mb-3 text-[10.5px] font-semibold uppercase tracking-[0.07em] text-muted">XVA depth · CVA + FVA + KVA + MVA − DVA</div>
          <div className="grid grid-cols-2 items-end gap-5 md:grid-cols-3 lg:grid-cols-5">
            <Slider label="Own CDS → DVA (0=off)" value={ownCds} min={0} max={600} step={25} onChange={setOwnCds} display={ownCds > 0 ? `${ownCds}bp` : "off"} />
            <Slider label="Cost of capital → KVA" value={coc} min={0} max={0.2} step={0.01} onChange={setCoc} display={coc > 0 ? pct(coc, 0) : "off"} />
            <Slider label="Wrong-way β" value={wwr} min={-1} max={1} step={0.1} onChange={setWwr} display={wwr.toFixed(1)} />
            <Toggle label="Initial margin → MVA" on={mva} onClick={() => setMva((x) => !x)} />
            <Toggle label="Collateralise (CSA/MPoR)" on={collat} onClick={() => setCollat((x) => !x)} />
          </div>
        </div>
      </Panel>

      {err && <div className="rounded-lg border border-down/30 bg-down/5 px-3 py-2 text-[12px] text-down">Charge failed: {err}</div>}

      {res && ds && trade && (
        <>
          <Panel className={cn("flex flex-wrap items-center justify-between gap-3 border px-4 py-3", ds.cls)}>
            <div className="flex items-center gap-3">
              <span className={cn("h-2.5 w-2.5 rounded-full", ds.dot)} />
              <div>
                <div className={cn("text-figure font-bold leading-none", ds.text)}>{ds.label}</div>
                <div className="mt-1 text-[12px] text-muted">{res.reasons.join(" · ") || "—"}</div>
              </div>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Chip hot={res.limit_status !== "PASS"}>limit {res.limit_status.toLowerCase()}</Chip>
              <Chip>RAROC {pct(res.trade_raroc, 1)} vs {pct(res.inputs.hurdle_rate, 0)} hurdle</Chip>
              {res.collateralised && <Chip hot>collateralised</Chip>}
            </div>
          </Panel>

          {/* All-in coupon — the punchline: base (no XVA) → net of XVA */}
          {res.all_in && !res.all_in.infeasible && (
            <Panel className="p-4">
              <SectionTitle>All-in coupon · what the desk can offer this counterparty</SectionTitle>
              <div className="flex flex-wrap items-baseline gap-x-5 gap-y-2">
                <div>
                  <div className="text-label uppercase tracking-[0.12em] text-muted">Base · no XVA</div>
                  <div className="tnum text-hero font-bold leading-none text-ink">{pct(res.all_in.coupon_base_pa ?? 0, 2)}<span className="ml-1 text-figure font-medium text-muted">p.a.</span></div>
                </div>
                <div className="text-figure text-muted">→</div>
                <div>
                  <div className="text-label uppercase tracking-[0.12em] text-muted">All-in · net of XVA</div>
                  <div className="tnum text-hero font-bold leading-none text-accent">{pct(res.all_in.coupon_all_in_pa ?? 0, 2)}<span className="ml-1 text-figure font-medium text-muted">p.a.</span></div>
                </div>
                <div className="self-center rounded-lg border border-down/30 bg-down/5 px-3 py-1.5 text-[12px] font-semibold text-down">
                  −{Math.round(res.all_in.drop_bp ?? 0)}bp from XVA
                </div>
              </div>
              <div className="px-1 pt-2 text-[12px] text-muted">
                The coupon re-solved to <span className="tnum text-ink">par − fee − XVA</span>: carrying the {res.inputs.cds_spread_bps}bp counterparty's CVA + FVA + KVA + MVA cuts what the desk can fairly offer. Widen the spread and it falls further.
              </div>
            </Panel>
          )}
          {res.all_in?.infeasible && (
            <Panel className="border border-down/30 bg-down/5 p-3 text-[12px] text-down">
              XVA exceeds the note's value — no positive coupon prices this fairly at this counterparty. The trade can't be done without charging above par or tightening the counterparty.
            </Panel>
          )}

          {/* Charge breakdown: CVA + FVA + KVA + MVA − DVA = Total */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
            <Kpi label="CVA" value={fmt(res.charge.cva, 3)} sub="credit" tone="neg" flashKey={Math.round(res.charge.cva * 1000)} />
            <Kpi label="FVA" value={fmt(res.charge.fva, 3)} sub="funding" tone="neg" flashKey={Math.round(res.charge.fva * 1000)} />
            <Kpi label="KVA" value={fmt(res.charge.kva, 3)} sub="capital" tone="neg" flashKey={Math.round(res.charge.kva * 1000)} />
            <Kpi label="MVA" value={fmt(res.charge.mva, 3)} sub="init. margin" tone="neg" flashKey={Math.round(res.charge.mva * 1000)} />
            <Kpi label="DVA" value={fmt(res.charge.dva, 3)} sub="own-credit benefit" tone="pos" flashKey={Math.round(res.charge.dva * 1000)} />
            <Kpi label="Total XVA" value={fmt(res.charge.total, 3)} sub={`${ccyPct(res.charge.total)} of notional`} tone="accent" flashKey={Math.round(res.charge.total * 1000)} />
          </div>

          {/* Risk & capital */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
            <Kpi label="CS01" value={fmt(res.sensitivities.cs01, 4)} sub="ΔCVA / +1bp" flashKey={Math.round(res.sensitivities.cs01 * 1e5)} />
            <Kpi label="Jump-to-default" value={fmt(res.sensitivities.jtd_net, 2)} sub="loss net of CVA" tone="neg" />
            <Kpi label="EAD" value={fmt(res.metrics.ead, 2)} sub="α·EEPE (econ.)" />
            <Kpi label="SA-CCR EAD" value={fmt(res.capital.saccr_ead, 1)} sub="regulatory" />
            <Kpi label="Economic capital" value={fmt(res.capital.economic, 2)} sub="ASRF 99.9%" tone="accent" />
            <Kpi label="Reg. capital" value={fmt(res.capital.regulatory_bacva, 2)} sub={`BA-CVA · RW ${fmt(res.capital.bacva_risk_weight_pct, 1)}%`} tone="accent" />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Panel className="p-3">
              <SectionTitle>Expected-exposure profile · EE(t)</SectionTitle>
              <AreaSpark
                data={res.profile}
                x="t"
                y="ee"
                color={C.teal}
                height={260}
                xLabel="time (years)"
                yLabel="EE"
                yTickFormat={(v) => v.toFixed(0)}
                xNumeric
                xTicks={timeTicks(res.profile.length ? res.profile[res.profile.length - 1].t : trade.maturity)}
                xTickFormat={(v) => `${v}y`}
              />
              <div className="px-1 pt-1 text-[12px] text-muted">
                {res.collateralised
                  ? "Collateralised (residual) exposure — only the close-out gap over the MPoR survives a CSA, so the profile sits far below the uncollateralised mark."
                  : trade.product_type === "autocallable"
                    ? "Mark-to-future positive exposure. The step-downs are autocall dates — redeemed paths leave the book, collapsing the exposure."
                    : "Mark-to-future positive exposure. With no early redemption, it stays elevated across the note's life — no autocall cliff."}
              </div>
            </Panel>
            <Panel className="p-3">
              <SectionTitle>XVA charge vs counterparty spread</SectionTitle>
              <Lines
                data={res.spread_curve}
                x="cds_bp"
                xLabel="counterparty CDS (bp)"
                yLabel="charge"
                series={[{ key: "cva", name: "CVA", color: C.down }, { key: "total", name: "total XVA", color: C.accent }]}
                height={260}
                refX={cds}
                refLabel={`${cds}bp`}
              />
              <div className="px-1 pt-1 text-[12px] text-muted">
                CVA scales with the counterparty's default risk; the gap up to total is the credit-independent FVA/KVA/MVA. The <span className="text-accent">dashed marker</span> is the selected spread.
              </div>
            </Panel>
          </div>

          <Panel className="p-3">
            <SectionTitle>CVA stress ladder · total charge under CDS shocks</SectionTitle>
            <Bars data={res.stress_ladder.map((s) => ({ shock: `${s.shift_bp > 0 ? "+" : ""}${s.shift_bp}bp`, total: s.total }))}
              x="shock" y="total" color={C.accent} height={220} yLabel="total XVA" />
            <div className="px-1 pt-1 text-[12px] text-muted">
              The charge re-struck under a parallel CDS shift — the CVA desk's daily stress view. CS01 above is the slope of this ladder at the current spread.
            </div>
          </Panel>
        </>
      )}
      {loading && !res && <div className="text-[13px] text-muted">Charging…</div>}
    </div>
  );
}

/* ======================= Outcome Lab ======================= */

export function OutcomeLab() {
  const [data, setData] = useState<OutcomeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getOutcomes().then(setData).catch((reason) => setError(String(reason)));
  }, []);

  if (error) return <Panel className="p-5 text-down">Unable to build outcome studies: {error}</Panel>;
  if (!data) return <div className="mt-8 animate-pulse text-muted">Running issuance, hedge and CCR studies…</div>;

  const { issuance, hedge, case_study: cs } = data;
  const decisionTone = cs.ccr_outcome.decision === "APPROVED" ? "text-up border-up/40 bg-up/10" : cs.ccr_outcome.decision === "REJECTED" ? "text-down border-down/40 bg-down/10" : "text-accent border-accent/40 bg-accent/10";
  const sampledCohorts = issuance.cohorts.filter((_, i) => i % 3 === 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 border-b border-border-soft pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="text-label font-bold uppercase tracking-[0.16em] text-accent">Evidence, not another feature</div>
          <h2 className="mt-1 text-[1.65rem] font-extrabold tracking-tight text-ink">Outcome Lab</h2>
          <p className="mt-1 max-w-3xl text-body text-muted">Book trade <span className="tnum text-ink">{data.contract_id}</span> from the 15-trade blotter, carried through issuance evidence, hedge implementation and hedge-counterparty approval.</p>
        </div>
        <div className="text-right text-small text-muted"><Chip hot>{data.as_of}</Chip><br className="hidden lg:block" />Reproducible fixed-seed studies</div>
      </div>

      <section>
        <div className="mb-3 flex items-start justify-between gap-4">
          <div><SectionTitle>01 · Rolling issuance backtest</SectionTitle><div className="text-body text-muted">{issuance.terms}</div></div>
          <span className="rounded-md border border-violet/30 bg-violet/10 px-2 py-1 text-small text-violet">{issuance.source}</span>
        </div>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <Kpi label="Issuances" value={String(issuance.n_issuances)} sub="monthly cohorts" />
          <Kpi label="Autocalled" value={`${issuance.autocall_rate_pct.toFixed(1)}%`} sub={`median life ${issuance.median_life_years.toFixed(2)}y`} tone="pos" />
          <Kpi label="Mean return" value={`${issuance.mean_return_pa_pct.toFixed(1)}%`} sub="annualised" tone="accent" />
          <Kpi label="Capital loss" value={`${issuance.loss_rate_pct.toFixed(1)}%`} sub="cohort frequency" tone="neg" />
          <Kpi label="5% tail" value={`${signed(issuance.tail_return_pct, 1)}%`} sub={`worst ${signed(issuance.worst_return_pct, 1)}%`} tone="neg" />
        </div>
        <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-5">
          <Panel className="p-3 lg:col-span-3">
            <SectionTitle>Cohort total return · every third issuance</SectionTitle>
            <Bars data={sampledCohorts} x="cohort" y="return_pct" color={C.accent} colorBySign height={260} yLabel="return %" />
          </Panel>
          <Panel className="p-3 lg:col-span-2">
            <SectionTitle>Underlying regime path</SectionTitle>
            <AreaSpark data={issuance.index_path} x="month" y="level" color={C.violet} height={260} xNumeric xLabel="month" yLabel="index" />
          </Panel>
        </div>
        <div className="mt-2 rounded-lg border border-violet/20 bg-violet/[0.06] px-3 py-2 text-small text-muted"><span className="font-semibold text-violet">Data boundary · </span>{issuance.source_note} Autocall range {issuance.robustness.autocall_rate_range_pct[0].toFixed(1)}–{issuance.robustness.autocall_rate_range_pct[1].toFixed(1)}%; loss range {issuance.robustness.loss_rate_range_pct[0].toFixed(1)}–{issuance.robustness.loss_rate_range_pct[1].toFixed(1)}%.</div>
      </section>

      <section>
        <SectionTitle>02 · Hedge comparison</SectionTitle>
        <div className="mb-3 text-body text-muted">{hedge.target}<br /><span className="text-small text-faint">{hedge.method}</span></div>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-5">
          <Panel className="overflow-hidden lg:col-span-3">
            <table className="w-full text-body">
              <thead className="bg-panel2 text-micro font-bold uppercase tracking-[0.08em] text-muted"><tr>
                <th className="px-3 py-3 text-left">Strategy</th><th className="px-3 py-3 text-right">P&amp;L σ</th><th className="px-3 py-3 text-right">ES 95</th><th className="px-3 py-3 text-right">Risk cut</th><th className="px-3 py-3 text-right">Turnover /100</th><th className="px-3 py-3 text-right">Cost /100</th><th className="px-3 py-3 text-right">Policy</th>
              </tr></thead>
              <tbody>{hedge.strategies.map((row) => <tr key={row.strategy} className={cn("border-t border-border-soft tnum", row.strategy === hedge.best_strategy && "bg-up/[0.06]")}>
                <td className="px-3 py-3 font-sans font-semibold text-ink">{row.strategy}{row.strategy === hedge.best_strategy && <span className="ml-2 text-micro uppercase text-up">recommended</span>}</td>
                <td className="px-3 py-3 text-right">{row.pnl_std.toFixed(2)}</td><td className="px-3 py-3 text-right text-down">{row.expected_shortfall_95.toFixed(2)}</td><td className="px-3 py-3 text-right text-up">{row.risk_reduction_pct.toFixed(1)}%</td><td className="px-3 py-3 text-right">{row.turnover.toFixed(1)}</td><td className="px-3 py-3 text-right">{row.transaction_cost.toFixed(3)}</td><td className={cn("px-3 py-3 text-right", row.strategy === "Unhedged" ? "text-muted" : row.eligible ? "text-up" : "text-down")}>{row.strategy === "Unhedged" ? "BASE" : row.eligible ? "PASS" : "FAIL"}</td>
              </tr>)}</tbody>
            </table>
          </Panel>
          <Panel className="p-3 lg:col-span-2">
            <SectionTitle>Variance reduction vs unhedged</SectionTitle>
            <Bars data={hedge.strategies} x="strategy" y="risk_reduction_pct" color={C.teal} height={255} yLabel="risk cut %" />
          </Panel>
        </div>
        <div className="mt-2 text-small text-muted">Policy: {hedge.selection_rule}. The {hedge.static_instruments}-line strip is constrained to listed-style strikes and 5× face gross; hybrid static allocation is {hedge.hybrid_static_scale_pct.toFixed(1)}%.</div>
      </section>

      <section>
        <SectionTitle>03 · Client-to-desk case study</SectionTitle>
        <Panel className="overflow-hidden">
          <div className="flex flex-col gap-3 border-b border-border bg-gradient-to-r from-panel2 to-panel px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
            <div><div className="text-figure font-bold text-ink">{cs.title}</div><div className="mt-1 text-body text-muted">Client target <span className="tnum text-accent">{cs.brief.target_coupon_pa_pct.toFixed(2)}% p.a.</span> · {cs.brief.tenor_years}Y · hedge CP CDS {cs.brief.counterparty_cds_bp}bp</div><div className="mt-1 text-small text-faint">Source: live blotter terms for {data.source_trade.trade_id} · {data.source_trade.underlying} · {data.source_trade.observation_frequency} observations · {cs.brief.counterparty_role}</div></div>
            <div className={cn("rounded-lg border px-4 py-2 text-right", decisionTone)}><div className="text-micro font-bold uppercase tracking-[0.12em]">{cs.ccr_outcome.decision}</div><div className="mt-0.5 font-semibold">{cs.recommendation}</div></div>
          </div>
          <div className="grid grid-cols-1 divide-y divide-border lg:grid-cols-3 lg:divide-x lg:divide-y-0">
            <div className="p-5"><div className="text-label font-bold uppercase tracking-[0.12em] text-accent">Investor</div><div className="mt-3 text-figure font-semibold">{cs.structure.product}</div><div className="mt-4 grid grid-cols-2 gap-3"><GreekStat label="Booked coupon" value={`${cs.structure.booked_coupon_pa_pct.toFixed(2)}%`} /><GreekStat label="Fair coupon · pre-XVA" value={`${cs.structure.fair_coupon_before_xva_pct.toFixed(2)}%`} /><GreekStat label="Offerable · post-XVA" value={`${cs.structure.offered_coupon_after_xva_pct.toFixed(2)}%`} tone={cs.structure.target_met ? "pos" : "neg"} /><GreekStat label="Target shortfall" value={`${cs.structure.target_shortfall_pct_pt.toFixed(2)}pt`} tone={cs.structure.target_met ? "pos" : "neg"} /></div><div className="mt-4 rounded-md border border-accent/20 bg-accent/[0.05] px-3 py-2 text-small text-muted"><span className="font-semibold text-accent">Restructuring menu · </span>{cs.restructuring_actions.join(" · ")}</div></div>
            <div className="p-5"><div className="text-label font-bold uppercase tracking-[0.12em] text-teal">Trading desk</div><div className="mt-3 text-figure font-semibold">{cs.desk_outcome.selected_hedge}</div><div className="mt-4 grid grid-cols-2 gap-3"><GreekStat label="P&L risk cut" value={`${cs.desk_outcome.pnl_risk_reduction_pct.toFixed(1)}%`} tone="pos" /><GreekStat label="Hedge cost /100" value={fmt(cs.desk_outcome.hedge_cost, 3)} /></div><p className="mt-4 text-body text-muted">{cs.desk_outcome.selection_rule}</p></div>
            <div className="p-5"><div className="text-label font-bold uppercase tracking-[0.12em] text-violet">CCR / capital</div><div className="mt-3 text-figure font-semibold">RAROC {cs.ccr_outcome.raroc_pct.toFixed(2)}%</div><div className="mt-4 grid grid-cols-2 gap-3"><GreekStat label="Total XVA" value={cs.ccr_outcome.xva_total.toFixed(3)} /><GreekStat label="EAD" value={cs.ccr_outcome.ead.toFixed(1)} /><GreekStat label="Economic capital" value={cs.ccr_outcome.economic_capital.toFixed(1)} /></div><p className="mt-4 text-body text-muted">{cs.decision_reasons.join(" ") || "All governance checks passed."}</p></div>
          </div>
          <div className="border-t border-border px-5 py-3 text-small text-faint">{cs.disclosure}</div>
        </Panel>
      </section>
    </div>
  );
}

/* ======================= Semi-Static Hedging ======================= */

export function SemiStaticHedging({
  trades, selectedId, setSelectedId, market,
}: {
  trades: Trade[];
  selectedId: string | null;
  setSelectedId: (id: string) => void;
  market: { spot: number; sigma: number; r: number; q: number };
}) {
  const [data, setData] = useState<SemiStaticResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setError(null);
    getSemiStatic({
      trades: trades.map((trade) => ({
        ...priceReq(trade),
        trade_id: trade.trade_id,
        underlying: trade.params.underlying ?? "NIFTY",
        direction: trade.direction ?? 1,
        initial_fixing: trade.initial_fixing ?? market.spot,
        barrier_breached: trade.barrier_breached,
        unwound_fraction: trade.unwound_fraction ?? 0,
        elapsed_years: trade.elapsed_years ?? 0,
      })),
      ...market,
      selected_trade_id: selectedId,
    })
      .then((result) => { if (active) setData(result); })
      .catch((reason) => { if (active) setError(String(reason)); });
    return () => { active = false; };
  }, [trades, selectedId, market.spot, market.sigma, market.r, market.q]);

  if (error) return <Panel className="p-5 text-down">Unable to build semi-static analytics: {error}</Panel>;
  if (!data) return <div className="mt-8 animate-pulse text-muted">Building live replication portfolios…</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <SectionTitle>Barrier Lifecycle Monitor · Live Book</SectionTitle>
          <div className="mt-1 text-[12px] text-muted">
            The same {trades.length} signed positions shown in Book &amp; Risk, re-marked on the live simulated spot and volatility. Select a barrier trade to inspect its constrained listed-grid strip.
          </div>
        </div>
        {data.selected_trade_id && <Chip>{data.selected_trade_id}</Chip>}
      </div>
      {data.message && <div className="rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-[12px] text-accent">{data.message}</div>}
      <div className="overflow-hidden rounded-md border border-border-soft bg-surface">
        <table className="w-full text-sm text-left">
          <thead className="bg-border-soft/30 text-muted uppercase text-[10px] tracking-wider">
            <tr>
              <th className="px-4 py-2">Trade ID</th>
              <th className="px-4 py-2">Underlying</th>
              <th className="px-4 py-2">Type</th>
              <th className="px-4 py-2">Barrier</th>
              <th className="px-4 py-2 text-right">Spot</th>
              <th className="px-4 py-2 text-right">Dist %</th>
              <th className="px-4 py-2 text-right">RN P(hit)</th>
              <th className="px-4 py-2">Monitoring</th>
              <th className="px-4 py-2">Lifecycle action</th>
              <th className="px-4 py-2 text-right">Target</th>
              <th className="px-4 py-2 text-right">Executed</th>
              <th className="px-4 py-2">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-soft font-mono">
            {data.pre_unwind.map((row) => (
              <tr
                key={row.trade_id}
                onClick={() => setSelectedId(row.trade_id)}
                className={cn("cursor-pointer transition-colors hover:bg-border-soft/30", data.selected_trade_id === row.trade_id && "bg-teal/10")}
              >
                <td className="px-4 py-2 text-ink">{row.trade_id}</td>
                <td className="px-4 py-2 text-teal">{row.underlying}</td>
                <td className="px-4 py-2">
                  <span className={cn("rounded border px-1.5 py-0.5 text-[9px] font-bold tracking-[0.08em]", row.barrier_type === "KI" ? "border-accent/40 bg-accent/10 text-accent" : "border-teal/40 bg-teal/10 text-teal")}>{row.barrier_type}</span>
                </td>
                <td className="px-4 py-2">{row.barrier.toFixed(2)}</td>
                <td className="px-4 py-2 text-right">{row.spot.toFixed(2)}</td>
                <td className={cn("px-4 py-2 text-right", row.distance_pct < 5 ? "text-down" : "text-up")}>{signed(row.distance_pct, 2)}%</td>
                <td className="px-4 py-2 text-right text-accent">{row.p_hit.toFixed(1)}%</td>
                <td className="px-4 py-2 font-sans text-[11px] text-muted">{row.monitoring}</td>
                <td className="px-4 py-2 font-sans text-[11px] text-ink">{row.lifecycle_action}</td>
                <td className="px-4 py-2 text-right">{row.target_action_pct === null ? <span className="text-faint">—</span> : `${row.target_action_pct.toFixed(1)}%`}</td>
                <td className="px-4 py-2 text-right">{row.executed_action_pct.toFixed(1)}%</td>
                <td className="px-4 py-2">
                  <span className={cn("rounded px-2 py-0.5 text-[10px]", row.status === "ACTION_REQD" || row.status === "KNOCKED_IN" || row.status === "KNOCKED_OUT" ? "bg-down/20 text-down" : row.status === "WATCH" || row.status === "STATE_UNKNOWN" ? "bg-accent/15 text-accent" : "bg-border-soft text-muted")}>{row.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <SectionTitle>Barrier Hedge Strip · {data.selected_trade_id ?? "—"}</SectionTitle>
          <div className="overflow-hidden rounded-md border border-border-soft bg-surface h-[300px] overflow-y-auto">
            <table className="w-full text-xs text-left">
              <thead className="bg-border-soft/30 text-muted uppercase text-[9px] tracking-wider sticky top-0">
                <tr>
                  <th className="px-3 py-2">Instrument</th>
                  <th className="px-3 py-2">Mat</th>
                  <th className="px-3 py-2 text-right">Wgt</th>
                  <th className="px-3 py-2 text-right">Δ-eq notional</th>
                  <th className="px-3 py-2 text-right">Δ</th>
                  <th className="px-3 py-2 text-right">Γ</th>
                  <th className="px-3 py-2 text-right">ν</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-soft font-mono">
                {data.portfolio.map((row) => (
                  <tr key={`${row.instrument}-${row.purpose}`} className="hover:bg-border-soft/20">
                    <td className="px-3 py-2 text-ink">{row.instrument}</td>
                    <td className="px-3 py-2">{row.maturity}</td>
                    <td className="px-3 py-2 text-right">{row.weight.toFixed(4)}</td>
                    <td className="px-3 py-2 text-right">{fmt(row.notional, 0)}</td>
                    <td className="px-3 py-2 text-right">{fmt(row.delta, 4)}</td>
                    <td className="px-3 py-2 text-right">{fmt(row.gamma, 7)}</td>
                    <td className="px-3 py-2 text-right">{fmt(row.vega, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-2 text-small text-muted"><span className="mr-2 rounded border border-teal/30 bg-teal/10 px-1.5 py-0.5 text-micro font-bold text-teal">{data.summary.position_label}</span> Gross Δ-equivalent <span className="tnum text-ink">{fmt(data.summary.total_static_notional, 1)}</span> / policy limit <span className="tnum text-ink">{fmt(data.summary.gross_limit, 1)}</span>. Indicative BS component hedge; execution still requires live chain liquidity.</div>
        </div>

        <div>
          <SectionTitle>Barrier-Component Tracking · Fixed Inception Barrier</SectionTitle>
          <Panel className="p-4 h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.tracking} margin={{ top: 5, right: 5, left: 20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#1a202b" />
                <XAxis dataKey="scenario" tick={{ fill: "#97a2b4", fontSize: 10 }} minTickGap={20} axisLine={false} tickLine={false} />
                <YAxis domain={['auto', 'auto']} tick={{ fill: "#97a2b4", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(val) => Number(val).toFixed(2)} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#12161f", borderColor: "#232a37", fontSize: 12, color: "#eaeef5" }}
                  itemStyle={{ color: "#e6b34a" }}
                  formatter={(value) => fmt(Number(value ?? 0), 2)}
                />
                <Line type="monotone" dataKey="target_pv" name="Barrier component PV" stroke={C.up} strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="hedge_pv" name="Constrained strip PV" stroke={C.teal} strokeWidth={2} dot={false} strokeDasharray="4 4" />
              </LineChart>
            </ResponsiveContainer>
          </Panel>
        </div>
      </div>

          <SectionTitle>Strike-Bucketed Residual Cash Risk</SectionTitle>
      <div className="overflow-hidden rounded-md border border-border-soft bg-surface p-4">
        <div className="flex justify-between items-center mb-6">
            <div className="text-sm text-muted">Target and static hedge grouped by contractual barrier. Delta is P&amp;L for +1% spot; gamma is ½Γ(1% spot)². Values are per ₹100 face.</div>
            <div className="flex space-x-6 text-sm font-mono">
                <div><span className="text-muted text-[10px] uppercase block">Net Δ / +1%</span><span className="text-ink">{signed(data.summary.residual_cash_delta_1pct, 4)}</span></div>
                <div><span className="text-muted text-[10px] uppercase block">Net Γ P&amp;L / 1%²</span><span className="text-ink">{signed(data.summary.residual_cash_gamma_1pct, 4)}</span></div>
            </div>
        </div>
        <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.risk_ladder} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#1a202b" />
                    <XAxis dataKey="bucket" tick={{ fill: "#97a2b4", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis yAxisId="left" orientation="left" stroke={C.teal} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => Number(v).toFixed(2)} />
                    <YAxis yAxisId="right" orientation="right" stroke={C.accent} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => Number(v).toFixed(3)} />
                    <Tooltip
                        contentStyle={{ backgroundColor: "#12161f", borderColor: "#232a37", fontSize: 12, color: "#eaeef5" }}
                    />
                    <Legend wrapperStyle={{ fontSize: 12, paddingTop: 10 }} />
                    <Bar yAxisId="left" dataKey="cash_delta_target_1pct" name="Target Δ P&L / +1%" fill={C.teal} opacity={0.6} />
                    <Bar yAxisId="left" dataKey="cash_delta_hedge_1pct" name="Hedge Δ P&L / +1%" fill={C.teal} />
                    <Bar yAxisId="right" dataKey="cash_gamma_target_1pct" name="Target Γ P&L / 1%²" fill={C.accent} opacity={0.6} />
                    <Bar yAxisId="right" dataKey="cash_gamma_hedge_1pct" name="Hedge Γ P&L / 1%²" fill={C.accent} />
                </BarChart>
            </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

/* ======================= Hedge & Execute (Phase 5) ======================= */

function NumField({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  const [text, setText] = useState(String(value));
  useEffect(() => {
    setText((t) => ((parseFloat(t) || 0) === value ? t : String(value)));
  }, [value]);
  return (
    <label className="block">
      <span className="text-[10.5px] font-semibold uppercase tracking-[0.07em] text-muted">{label}</span>
      <input
        type="number"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          onChange(parseFloat(e.target.value) || 0);
        }}
        className="ring-desk tnum mt-1 w-full rounded-lg border border-border bg-panel2 px-2.5 py-1.5 text-[13px] text-ink"
      />
    </label>
  );
}

const SEVERITY_TONE: Record<string, string> = {
  CRITICAL: "border-down/50 bg-down/10 text-down",
  WARNING: "border-accent/50 bg-accent/10 text-accent",
  INFO: "border-teal/50 bg-teal/10 text-teal",
};

export function HedgeExecute({ desk, onExecuted }: { desk: Desk; onExecuted?: () => void }) {
  const [bid, setBid] = useState(Math.round(desk.spot) - 1);
  const [ask, setAsk] = useState(Math.round(desk.spot) + 1);
  const [lot, setLot] = useState(75); // NIFTY futures lot (overwritten by the live master)
  const [deltaOverride, setDeltaOverride] = useState(0); // 0 = hedge the actual book delta
  const [optOn, setOptOn] = useState(false); // add an option leg → delta-vega hedge
  const [optStrike, setOptStrike] = useState(0);
  const [optExpiry, setOptExpiry] = useState("");
  const [optType, setOptType] = useState<"CE" | "PE">("CE");
  const [optBid, setOptBid] = useState(0);
  const [optAsk, setOptAsk] = useState(0);
  const [vegaOverride, setVegaOverride] = useState(0); // 0 = hedge the actual book vega
  const [live, setLive] = useState<LiveQuote | null>(null);
  const [rec, setRec] = useState<HedgeRec | null>(null);
  const [blotter, setBlotter] = useState<PaperBlotter | null>(null);
  const [alerts, setAlerts] = useState<DeskAlert[]>([]);
  const [attribution, setAttribution] = useState<Awaited<ReturnType<typeof getAttribution>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [executed, setExecuted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autohedge, setAutohedgeState] = useState<AutohedgeStatus | null>(null);
  const refreshSequence = useRef(0);

  useEffect(() => {
    let dead = false;
    const load = () => void getAutohedge().then((s) => { if (!dead) setAutohedgeState(s); }).catch(() => {});
    load();
    const id = setInterval(load, 30_000);
    return () => { dead = true; clearInterval(id); };
  }, []);

  const toggleAutohedge = async () => {
    if (!autohedge) return;
    try {
      setAutohedgeState(await setAutohedge(!autohedge.enabled));
    } catch (e) {
      setError(String(e));
    }
  };

  const loadProposal = async (id: string) => {
    try {
      const found = (await getRecommendations()).find((r) => r.recommendation_id === id);
      if (found) {
        setRec(found);
        setExecuted(found.execution_state === "EXECUTED");
      }
    } catch (e) {
      setError(String(e));
    }
  };

  // Ref, not state: the mount-time refresh() runs from a closure where `live` is still
  // null, which used to send the placeholder mark key and leave the future "no mark".
  const liveRef = useRef<LiveQuote | null>(null);

  const refresh = async () => {
    const sequence = ++refreshSequence.current;
    try {
      const q = liveRef.current;
      const markKey = q ? `${q.segment}:${q.instrument_id}` : "2:1";
      const mid = q?.bid != null && q?.ask != null ? (q.bid + q.ask) / 2 : q?.ltp ?? (bid + ask) / 2;
      const [nextBlotter, nextAlerts, nextAttribution] = await Promise.all([
        getBlotter(), getAlerts(), getAttribution({ [markKey]: mid }),
      ]);
      if (sequence === refreshSequence.current) {
        setBlotter(nextBlotter);
        setAlerts(nextAlerts.open);
        setAttribution(nextAttribution);
      }
    } catch (e) {
      if (sequence === refreshSequence.current) setError(String(e));
    }
  };
  const loadLiveQuote = async () => {
    try {
      const q = await getLiveQuote(desk.underlying);
      liveRef.current = q;
      setLive(q);
      if (q.bid != null) setBid(q.bid);
      if (q.ask != null) setAsk(q.ask);
      if (q.bid == null && q.ask == null && q.ltp != null) { setBid(q.ltp); setAsk(q.ltp); }
      if (q.lot_size > 0) setLot(q.lot_size);
    } catch {
      liveRef.current = null;
      setLive(null); // not on the XTS feed — the manual ticket still works
    }
  };
  useEffect(() => {
    void loadLiveQuote().then(refresh);
    return () => { refreshSequence.current += 1; };
  }, []);
  useEffect(() => {
    if (live) return; // connected — stop retrying
    const id = setInterval(() => void loadLiveQuote(), 30_000);
    return () => clearInterval(id);
  }, [live]);

  // First enable: prefill the ticket from the desk's own calibrated chain (nearest-ATM CE,
  // front expiry). Everything stays editable; if the chain is unavailable, type it in.
  const toggleOptionLeg = async () => {
    const next = !optOn;
    setOptOn(next);
    if (!next || optStrike > 0) return;
    try {
      const chain = await getOptionChain();
      const front = chain.rows.map((r) => r.expiry).sort()[0];
      const calls = chain.rows.filter((r) => r.type === "CE" && r.expiry === front);
      if (!calls.length) return;
      const atm = calls.reduce((a, b) => (Math.abs(a.strike - chain.spot) < Math.abs(b.strike - chain.spot) ? a : b));
      setOptStrike(atm.strike);
      setOptExpiry(atm.expiry);
      setOptBid(+(atm.price * 0.995).toFixed(2));
      setOptAsk(+(atm.price * 1.005).toFixed(2));
    } catch {
      /* chain unavailable — manual entry still works */
    }
  };

  const recommend = async () => {
    setBusy(true);
    setExecuted(false);
    setError(null);
    try {
      setRec(await recommendHedge({
        ...(deltaOverride !== 0 ? { book_delta: deltaOverride } : {}),
        ...(optOn ? {
          // deterministic paper id: same option → same position, different options never collide
          option: {
            instrument_id: Number(optExpiry.replaceAll("-", "")) * 1e6 + Math.round(optStrike * 10) * 10 + (optType === "CE" ? 1 : 2),
            segment: 2, symbol: `${desk.underlying} ${fmt(optStrike, 0)} ${optType}`,
            bid: optBid || null, ask: optAsk || null, ltp: (optBid + optAsk) / 2 || null,
            quote_timestamp: new Date().toISOString(), lot_size: lot,
            strike: optStrike, expiry: optExpiry, option_type: optType,
          },
          ...(vegaOverride !== 0 ? { book_vega: vegaOverride } : {}),
        } : {}),
        future: live ? {
          instrument_id: live.instrument_id, segment: live.segment, symbol: live.description,
          bid, ask, ltp: live.ltp ?? (bid + ask) / 2,
          quote_timestamp: live.timestamp ?? new Date().toISOString(), lot_size: lot,
          expiry: live.expiry, // lets the server carry-adjust the position's mark
        } : {
          instrument_id: 1, segment: 2, symbol: `${desk.underlying}-FUT`, bid, ask,
          ltp: (bid + ask) / 2, quote_timestamp: new Date().toISOString(), lot_size: lot,
        },
      }));
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const execute = async () => {
    if (!rec) return;
    setBusy(true);
    setError(null);
    try {
      await executeRecommendation(rec.recommendation_id);
      setExecuted(true);
      onExecuted?.();
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const positions = blotter ? Object.entries(blotter.positions).map(([id, p]) => ({ id, ...p })) : [];

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="space-y-4">
        <Panel>
          <SectionTitle>Recommend a hedge</SectionTitle>
          <p className="mb-3 text-[12px] leading-relaxed text-muted">
            Sizes a lot-rounded futures order against the book's net delta, estimates spread + fee cost, and
            paper-executes it against the quote below. Add an option leg to hedge vega too — the option is
            sized on the desk model's own greeks and re-marked with the book after execution.
          </p>
          <div className="mb-3 flex items-center gap-2">
            {live ? (
              <>
                <Chip hot={!live.stale}>{live.stale ? "LIVE · STALE" : "LIVE"}</Chip>
                <span className="tnum text-[11px] text-muted">
                  {live.description} · exp {live.expiry}
                  {live.age_s != null && ` · quote ${fmtAge(live.age_s)} old`}
                </span>
                <button
                  onClick={() => { setError(null); void loadLiveQuote(); }}
                  className="ring-desk rounded border border-border px-2 py-1 text-[10px] font-bold uppercase tracking-[0.08em] text-muted hover:text-ink"
                >
                  Refresh quote
                </button>
              </>
            ) : (
              <>
                <Chip>MANUAL</Chip>
                <span className="text-[11px] text-muted">no broker feed — type the futures quote</span>
                <button
                  onClick={() => { setError(null); void loadLiveQuote(); }}
                  className="ring-desk rounded border border-border px-2 py-1 text-[10px] font-bold uppercase tracking-[0.08em] text-muted hover:text-ink"
                >
                  Try live
                </button>
              </>
            )}
          </div>
          <div className="mb-3 grid grid-cols-3 gap-3">
            <GreekStat label="Book net Δ" value={signed(desk.net_greeks.delta, 1)} tone={desk.net_greeks.delta >= 0 ? "pos" : "neg"} />
            <GreekStat label="Book net vega" value={signed(desk.net_greeks.vega, 1)} />
            <GreekStat label="Spot" value={fmt(desk.spot, 0)} />
          </div>
          <div className="mb-3 grid grid-cols-3 gap-3">
            <NumField label="Fut bid" value={bid} onChange={setBid} />
            <NumField label="Fut ask" value={ask} onChange={setAsk} />
            <NumField label="Lot size" value={lot} onChange={(v) => setLot(Math.max(1, Math.round(v)))} />
          </div>
          <div className="mb-3 grid grid-cols-3 gap-3">
            <NumField label="Δ to hedge (0 = book's own)" value={deltaOverride} onChange={setDeltaOverride} />
            {optOn && <NumField label="ν to hedge (0 = book's own)" value={vegaOverride} onChange={setVegaOverride} />}
          </div>
          <label className="mb-3 flex cursor-pointer items-center gap-2 text-[12px] text-muted">
            <input type="checkbox" checked={optOn} onChange={() => void toggleOptionLeg()} />
            Add an option leg — hedges vega too; leg greeks are priced off the desk model
          </label>
          {optOn && (
            <>
              <div className="mb-3 grid grid-cols-3 gap-3">
                <NumField label="Strike" value={optStrike} onChange={setOptStrike} />
                <label className="block">
                  <span className="text-[10.5px] font-semibold uppercase tracking-[0.07em] text-muted">Expiry</span>
                  <input
                    type="date"
                    value={optExpiry}
                    onChange={(e) => setOptExpiry(e.target.value)}
                    className="ring-desk tnum mt-1 w-full rounded-lg border border-border bg-panel2 px-2.5 py-1.5 text-[13px] text-ink"
                  />
                </label>
                <label className="block">
                  <span className="text-[10.5px] font-semibold uppercase tracking-[0.07em] text-muted">Type</span>
                  <select
                    value={optType}
                    onChange={(e) => setOptType(e.target.value as "CE" | "PE")}
                    className="ring-desk mt-1 w-full rounded-lg border border-border bg-panel2 px-2.5 py-1.5 text-[13px] text-ink"
                  >
                    <option value="CE">CE (call)</option>
                    <option value="PE">PE (put)</option>
                  </select>
                </label>
              </div>
              <div className="mb-3 grid grid-cols-3 gap-3">
                <NumField label="Opt bid" value={optBid} onChange={setOptBid} />
                <NumField label="Opt ask" value={optAsk} onChange={setOptAsk} />
              </div>
            </>
          )}
          {Math.abs(desk.net_greeks.delta) < 1 && deltaOverride === 0 && (
            <p className="mb-3 text-[11px] text-muted">
              The book is currently delta-flat, so a recommendation will propose no orders.
              Enter a Δ to hedge (say 500) to walk the full recommend, execute and attribution loop.
            </p>
          )}
          <button
            onClick={recommend}
            disabled={busy || (optOn && (optStrike <= 0 || !optExpiry))}
            className="ring-desk rounded-lg border border-accent/60 bg-accent/10 px-4 py-2 text-[12px] font-bold uppercase tracking-[0.1em] text-accent transition-colors hover:bg-accent/20 disabled:opacity-40"
          >
            {busy ? "…" : "Recommend"}
          </button>
          {error && <p className="mt-2 text-[12px] text-down" role="alert">{error}</p>}
          {autohedge && (
            <div className="mt-4 rounded-lg border border-border-soft bg-panel2/40 px-3 py-2">
              <div className="flex flex-wrap items-center gap-2 text-[12px]">
                <span className="font-semibold uppercase tracking-[0.07em] text-muted">Auto-hedger</span>
                <Chip hot={autohedge.enabled}>{autohedge.enabled ? "ARMED" : "OFF"}</Chip>
                <span className="tnum text-muted">|Δ| ≥ {fmt(autohedge.delta_threshold, 0)} · every {fmt(autohedge.interval_s, 0)}s · proposes only, never executes</span>
                <button onClick={() => void toggleAutohedge()}
                  className="ring-desk ml-auto rounded border border-border px-2 py-1 text-[10px] font-bold uppercase tracking-[0.08em] text-muted hover:text-ink">
                  {autohedge.enabled ? "Disarm" : "Arm"}
                </button>
              </div>
              {autohedge.last_proposal && (
                <div className="mt-1 flex flex-wrap items-center gap-2 text-[11.5px] text-muted">
                  <span className="tnum">
                    {autohedge.last_proposal.recommendation_id} · Δ {fmt(autohedge.last_proposal.book_delta, 0)} →{" "}
                    {autohedge.last_proposal.orders.map((o) => `${o.side} ${fmt(o.qty, 0)} ${o.symbol}`).join(", ") || "no orders"}
                  </span>
                  <button onClick={() => void loadProposal(autohedge.last_proposal!.recommendation_id)}
                    className="ring-desk rounded border border-accent/50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] text-accent hover:bg-accent/10">
                    Review
                  </button>
                </div>
              )}
              {autohedge.last_error && <p className="mt-1 text-[11px] text-down">watcher: {autohedge.last_error}</p>}
            </div>
          )}
        </Panel>

        {rec && (
          <Panel>
            <SectionTitle>Recommendation {rec.recommendation_id}</SectionTitle>
            <div className="mb-2">
              <Chip hot={rec.approval_state === "PROPOSED"}>{rec.approval_state}</Chip>
              {rec.reason_codes.map((c) => <Chip key={c}>{c.replace(/_/g, " ").toLowerCase()}</Chip>)}
              {executed && <Chip hot>EXECUTED</Chip>}
            </div>
            {rec.orders.length > 0 ? (
              <DataTable
                rows={rec.orders}
                cols={[
                  { key: "symbol", label: "Instrument" },
                  { key: "side", label: "Side", fmt: (o) => <span className={o.side === "BUY" ? "text-up" : "text-down"}>{o.side}</span> },
                  { key: "qty", label: "Qty", align: "right", fmt: (o) => fmt(o.qty, 0) },
                ]}
              />
            ) : (
              <p className="text-[12px] text-muted">No orders — book delta is within tolerance.</p>
            )}
            <div className="mt-3 grid grid-cols-3 gap-3">
              <GreekStat label="Δ before" value={signed(rec.current_greeks.delta, 1)} />
              <GreekStat label="Δ after" value={signed(rec.expected_greeks.delta, 1)} tone={Math.abs(rec.expected_greeks.delta) < Math.abs(rec.current_greeks.delta) ? "pos" : undefined} />
              <GreekStat label="Est. cost" value={fmt(rec.estimated_cost, 0)} />
            </div>
            {rec.objective === "delta_vega_neutral" && (
              <div className="mt-3 grid grid-cols-3 gap-3">
                <GreekStat label="ν before" value={signed(rec.current_greeks.vega, 1)} />
                <GreekStat label="ν after" value={signed(rec.expected_greeks.vega, 1)} tone={Math.abs(rec.expected_greeks.vega) < Math.abs(rec.current_greeks.vega) ? "pos" : undefined} />
              </div>
            )}
            {rec.orders.length > 0 && (
              <button
                onClick={execute}
                disabled={busy || executed || rec.approval_state !== "PROPOSED"}
                className="ring-desk mt-3 rounded-lg border border-up/60 bg-up/10 px-4 py-2 text-[12px] font-bold uppercase tracking-[0.1em] text-up transition-colors hover:bg-up/20 disabled:opacity-40"
              >
                Paper execute
              </button>
            )}
          </Panel>
        )}
      </div>

      <div className="space-y-4">
        <Panel>
          <SectionTitle>Paper blotter</SectionTitle>
          {positions.length > 0 && (
            <DataTable
              rows={positions}
              cols={[
                { key: "symbol", label: "Position" },
                { key: "qty", label: "Qty", align: "right", fmt: (p) => signed(p.qty, 0) },
                { key: "avg_price", label: "Avg px", align: "right", fmt: (p) => fmt(p.avg_price, 1) },
                { key: "realized_pnl", label: "Realized", align: "right", fmt: (p) => <span className={p.realized_pnl >= 0 ? "text-up" : "text-down"}>{signed(p.realized_pnl, 0)}</span> },
                { key: "fees_paid", label: "Fees", align: "right", fmt: (p) => fmt(p.fees_paid, 0) },
              ]}
            />
          )}
          <div className="mt-3">
            {blotter && blotter.orders.length > 0 ? (
              <DataTable
                max={260}
                rows={[...blotter.orders].reverse()}
                cols={[
                  { key: "order_id", label: "Order" },
                  { key: "symbol", label: "Instrument" },
                  { key: "side", label: "Side", fmt: (o) => <span className={o.side === "BUY" ? "text-up" : "text-down"}>{o.side}</span> },
                  { key: "qty", label: "Qty", align: "right", fmt: (o) => fmt(o.qty, 0) },
                  { key: "status", label: "Status" },
                ]}
              />
            ) : (
              <p className="text-[12px] text-muted">No paper orders yet — recommend and execute a hedge.</p>
            )}
          </div>
        </Panel>

        {attribution && attribution.rows.length > 0 && (
          <Panel>
            <SectionTitle>Hedge P&L attribution</SectionTitle>
            <DataTable max={220} rows={attribution.rows}
              cols={[
                { key: "symbol", label: "Instrument" },
                { key: "realized_pnl", label: "Realized", align: "right", fmt: (r) => signed(r.realized_pnl, 0) },
                { key: "unrealized_pnl", label: "Unrealized", align: "right", fmt: (r) => r.unrealized_pnl != null ? signed(r.unrealized_pnl, 0) : "no mark" },
                { key: "spread_cost", label: "Spread", align: "right", fmt: (r) => fmt(r.spread_cost, 0) },
                { key: "fees", label: "Fees", align: "right", fmt: (r) => fmt(r.fees, 0) },
                { key: "net_pnl", label: "Net", align: "right", fmt: (r) => r.net_pnl != null ? <span className={r.net_pnl >= 0 ? "text-up" : "text-down"}>{signed(r.net_pnl, 0)}</span> : "—" },
              ]} />
            <p className="mt-2 text-[10.5px] text-faint">
              Marked at the mid of the quote inputs. Spread cost is already inside the P&L — shown for visibility, not double-counted.
            </p>
          </Panel>
        )}

        <Panel>
          <SectionTitle>Alerts</SectionTitle>
          {alerts.length === 0 ? (
            <p className="text-[12px] text-muted">No open alerts. Greek-limit rules re-evaluate on every recommendation.</p>
          ) : (
            <ul className="space-y-2">
              {alerts.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-3 rounded-lg border border-border bg-panel2/60 px-3 py-2">
                  <div>
                    <span className={cn("mr-2 rounded border px-1.5 py-px text-[9px] font-bold uppercase tracking-[0.1em]", SEVERITY_TONE[a.severity])}>{a.severity}</span>
                    <span className="text-[12px] text-ink/90">{a.message}</span>
                  </div>
                  {a.status === "OPEN" ? (
                    <button onClick={async () => {
                      setError(null);
                      try {
                        await ackAlert(a.id);
                        await refresh();
                      } catch (e) {
                        setError(String(e));
                      }
                    }} className="ring-desk shrink-0 rounded border border-border px-2 py-1 text-[10px] font-bold uppercase tracking-[0.08em] text-muted hover:text-ink">
                      Ack
                    </button>
                  ) : (
                    <span className="shrink-0 text-[10px] font-bold uppercase tracking-[0.08em] text-faint">{a.status}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}

/* ======================= Payoff Explorer (Phase 11) ======================= */

const EXPLORER_PRODUCTS = [
  { key: "autocallable", label: "Autocallable (Phoenix)" },
  { key: "brc", label: "Barrier Reverse Convertible" },
  { key: "capital_protected", label: "Capital-Protected Note" },
] as const;

export function PayoffExplorer({ desk }: { desk: Desk }) {
  const [productType, setProductType] = useState<string>("autocallable");
  const [couponPa, setCouponPa] = useState(0.10);
  const [knockIn, setKnockIn] = useState(0.70);
  const [maturity, setMaturity] = useState(2);
  const [participation, setParticipation] = useState(1.2);
  const [result, setResult] = useState<ExplorerResult | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      const obs = Array.from({ length: maturity * 4 }, (_, i) => (i + 1) / 4);
      const params: Record<string, any> =
        productType === "capital_protected"
          ? { protection: 1.0, participation, strike: 1.0 }
          : productType === "brc"
            ? { coupon_rate: couponPa / 4, knock_in: knockIn, strike: 1.0 }
            : { coupon_rate: couponPa / 4, knock_in: knockIn, autocall_level: 1.0, coupon_barrier: knockIn, memory: true };
      setResult(await explore({
        product_type: productType, notional: 100,
        observation_times: productType === "capital_protected" ? undefined : obs,
        maturity: productType === "capital_protected" ? maturity : undefined,
        params,
      }));
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => { run(); /* eslint-disable-line */ }, [productType]);

  const o = result?.outcomes;
  return (
    <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
      <div className="space-y-4">
        <Panel>
          <SectionTitle>Pick a product</SectionTitle>
          <div className="mb-3 flex flex-wrap gap-1.5">
            {EXPLORER_PRODUCTS.map((p) => (
              <button key={p.key} onClick={() => setProductType(p.key)}
                className={cn("ring-desk rounded-lg border px-3 py-1.5 text-[12px] font-semibold transition-colors",
                  productType === p.key ? "border-accent/60 bg-accent/10 text-accent" : "border-border bg-panel2 text-muted hover:text-ink")}>
                {p.label}
              </button>
            ))}
          </div>
          <div className="space-y-3">
            {productType !== "capital_protected" && (
              <>
                <Slider label="Coupon (p.a.)" value={couponPa} min={0.02} max={0.25} step={0.005}
                  onChange={setCouponPa} display={`${(couponPa * 100).toFixed(1)}%`} />
                <Slider label="Barrier / knock-in" value={knockIn} min={0.4} max={0.95} step={0.05}
                  onChange={setKnockIn} display={`${(knockIn * 100).toFixed(0)}%`} />
              </>
            )}
            {productType === "capital_protected" && (
              <Slider label="Participation" value={participation} min={0.5} max={2.5} step={0.05}
                onChange={setParticipation} display={`${participation.toFixed(2)}×`} />
            )}
            <Slider label="Maturity (years)" value={maturity} min={1} max={4} step={1}
              onChange={(v) => setMaturity(Math.round(v))} display={`${maturity}Y`} />
          </div>
          <button onClick={run} disabled={busy}
            className="ring-desk mt-4 rounded-lg border border-accent/60 bg-accent/10 px-4 py-2 text-[12px] font-bold uppercase tracking-[0.1em] text-accent transition-colors hover:bg-accent/20 disabled:opacity-40">
            {busy ? "Pricing…" : "Update"}
          </button>
        </Panel>
        {result && (
          <Panel>
            <SectionTitle>In plain English</SectionTitle>
            <ul className="space-y-2 text-[12.5px] leading-relaxed text-ink/90">
              {result.summary.map((s, i) => <li key={i}>• {s}</li>)}
            </ul>
            <p className="mt-3 border-t border-border-soft pt-2 text-[10.5px] leading-relaxed text-faint">{result.disclaimer}</p>
          </Panel>
        )}
      </div>

      <div className="space-y-4">
        {result && o && (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Kpi label="Fair value" value={fmt(result.pv, 2)} sub={`per ${result.notional} notional`} />
              <Kpi label="Chance of early redemption" value={`${o.prob_autocall_pct.toFixed(0)}%`} sub={`median life ${o.median_life_years.toFixed(2)}y`} tone="accent" />
              <Kpi label="Chance of losing money" value={`${o.prob_loss_pct.toFixed(1)}%`} sub="model-implied" tone={o.prob_loss_pct > 15 ? "neg" : "pos"} />
              <Kpi label="Worst 5% return" value={`${o.p5_return_pct.toFixed(1)}%`} sub={`best 5%: ${o.p95_return_pct.toFixed(1)}%`} tone="neg" />
            </div>
            <Panel>
              <SectionTitle>Payment at maturity vs where the index ends</SectionTitle>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={result.payoff.map((p) => ({ level: Math.round(p.terminal_level * 100), pay: p.payment_pct }))}>
                  <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
                  <XAxis dataKey="level" tick={{ fontSize: 11 }} label={{ value: "index at maturity (% of start)", position: "insideBottom", offset: -4, fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 11 }} label={{ value: "payment %", angle: -90, position: "insideLeft", fontSize: 10 }} />
                  <Tooltip formatter={(v: number) => [`${v.toFixed(1)}%`, "payment"]} labelFormatter={(l) => `index at ${l}%`} />
                  <Line type="monotone" dataKey="pay" stroke={C.accent} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </Panel>
            <div className="grid gap-4 md:grid-cols-2">
              <Panel>
                <SectionTitle>When does it redeem?</SectionTitle>
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={o.autocall_by_period.map((p) => ({ t: `${p.time}y`, pct: p.prob_pct }))}>
                    <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
                    <XAxis dataKey="t" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} />
                    <Tooltip formatter={(v: number) => [`${v.toFixed(1)}%`, "chance"]} />
                    <Bar dataKey="pct" fill={C.accent} />
                  </BarChart>
                </ResponsiveContainer>
              </Panel>
              <Panel>
                <SectionTitle>Coupon schedule</SectionTitle>
                {result.coupon_schedule.length ? (
                  <DataTable max={180} rows={result.coupon_schedule}
                    cols={[
                      { key: "time", label: "Observation", fmt: (r) => `${r.time}y` },
                      { key: "amount_pct", label: "Coupon", align: "right", fmt: (r) => `${r.amount_pct.toFixed(2)}%` },
                    ]} />
                ) : (
                  <p className="text-[12px] text-muted">No coupons — this note pays through upside participation at maturity.</p>
                )}
              </Panel>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ======================= Option Chain ======================= */

export function OptionChainView() {
  const [chain, setChain] = useState<Awaited<ReturnType<typeof getOptionChain>> | null>(null);
  const [expiry, setExpiry] = useState<string | null>(null);
  useEffect(() => { getOptionChain().then((c) => { setChain(c); setExpiry(c.rows[0]?.expiry ?? null); }).catch(() => {}); }, []);
  if (!chain) return <div className="text-[12px] text-muted">Loading chain…</div>;

  const expiries = [...new Set(chain.rows.map((r) => r.expiry))];
  const rows = chain.rows.filter((r) => r.expiry === expiry);
  const byStrike = new Map<number, { strike: number; ce?: ChainRow; pe?: ChainRow }>();
  rows.forEach((r) => {
    const e = byStrike.get(r.strike) ?? { strike: r.strike };
    if (r.type === "CE") e.ce = r; else e.pe = r;
    byStrike.set(r.strike, e);
  });
  const table = [...byStrike.values()].sort((a, b) => a.strike - b.strike);
  // The liquid smile is the OTM side: puts below spot, calls above. ITM quotes are mostly
  // stale settlement prints whose IVs don't invert cleanly — plotting them draws spikes.
  const smile = table
    .map((r) => {
      const otm = r.strike <= chain.spot ? r.pe : r.ce;
      return { strike: r.strike, iv: otm?.iv != null ? otm.iv * 100 : null };
    })
    .filter((r) => r.iv != null);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel>
        <div className="mb-2 flex items-center justify-between">
          <SectionTitle>Chain · {chain.underlying} · spot {fmt(chain.spot, 0)}</SectionTitle>
          <span className="text-[10px] uppercase tracking-[0.1em] text-faint">{chain.data_source} · {chain.as_of}</span>
        </div>
        <div className="mb-3 flex flex-wrap gap-1.5">
          {expiries.map((e) => (
            <button key={e} onClick={() => setExpiry(e)}
              className={cn("ring-desk rounded-lg border px-2.5 py-1 text-[11px] font-semibold",
                expiry === e ? "border-accent/60 bg-accent/10 text-accent" : "border-border bg-panel2 text-muted hover:text-ink")}>
              {e}
            </button>
          ))}
        </div>
        <DataTable max={430} rows={table}
          cols={[
            { key: "ce_price", label: "Call px", align: "right", fmt: (r) => r.ce ? fmt(r.ce.price, 1) : "—" },
            { key: "ce_iv", label: "Call IV", align: "right", fmt: (r) => r.ce?.iv != null ? `${(r.ce.iv * 100).toFixed(1)}%` : "—" },
            { key: "strike", label: "Strike", align: "right", className: (r) => (Math.abs(r.strike / chain.spot - 1) < 0.01 ? "font-bold text-accent" : ""), fmt: (r) => fmt(r.strike, 0) },
            { key: "pe_iv", label: "Put IV", align: "right", fmt: (r) => r.pe?.iv != null ? `${(r.pe.iv * 100).toFixed(1)}%` : "—" },
            { key: "pe_price", label: "Put px", align: "right", fmt: (r) => r.pe ? fmt(r.pe.price, 1) : "—" },
          ]} />
      </Panel>
      <Panel>
        <SectionTitle>Implied-vol smile · {expiry}</SectionTitle>
        <ResponsiveContainer width="100%" height={420}>
          <LineChart data={smile}>
            <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
            <XAxis dataKey="strike" tick={{ fontSize: 10 }} domain={["dataMin", "dataMax"]} type="number" />
            <YAxis tick={{ fontSize: 10 }} unit="%" domain={["auto", "auto"]} />
            <Tooltip formatter={(v: number) => [`${v.toFixed(2)}%`, "IV"]} labelFormatter={(l) => `strike ${l}`} />
            <Line type="monotone" dataKey="iv" name="OTM IV" stroke={C.teal} strokeWidth={2} dot={{ r: 2 }} connectNulls />
          </LineChart>
        </ResponsiveContainer>
        <p className="mt-2 text-[10.5px] text-faint">
          Broker-chain mids (last print when one side is missing). The smile shows the liquid OTM side:
          puts below spot, calls above. ITM rows in the table are often stale prints, which is why their IVs are blank.
        </p>
      </Panel>
    </div>
  );
}

/* ======================= Broker (Phase 7 UI) ======================= */

export function BrokerView() {
  const [state, setState] = useState<BrokerState | null>(null);
  useEffect(() => { getBrokerState().then(setState).catch(() => {}); }, []);
  if (!state) return <div className="text-[12px] text-muted">Checking broker connection…</div>;

  if (!state.connected) {
    return (
      <Panel>
        <SectionTitle>Broker · not connected</SectionTitle>
        <p className="mb-2 text-[13px] text-ink/90">
          The read-only broker view lights up when XTS interactive credentials are configured.
        </p>
        <p className="text-[12px] text-muted">{state.reason}</p>
        <p className="mt-3 text-[11px] text-faint">
          Set <code>SPDT_XTS_INTERACTIVE_APP_KEY</code> / <code>SPDT_XTS_INTERACTIVE_SECRET</code> in
          .env (see .env.example). This tab only ever reads orders, positions and margins — order
          placement stays paper unless explicitly enabled.
        </p>
      </Panel>
    );
  }

  const m = state.margins!;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Kpi label="Cash available" value={compact(m.cash_available)} />
        <Kpi label="Margin used" value={compact(m.margin_utilized)} tone="accent" />
        <Kpi label="Net margin free" value={compact(m.net_margin_available)} tone="pos" />
      </div>
      <Panel>
        <SectionTitle>Paper vs broker reconciliation</SectionTitle>
        {state.reconciliation?.length ? (
          <DataTable rows={state.reconciliation}
            cols={[
              { key: "symbol", label: "Instrument" },
              { key: "paper_qty", label: "Paper", align: "right", fmt: (r) => signed(r.paper_qty, 0) },
              { key: "broker_qty", label: "Broker", align: "right", fmt: (r) => signed(r.broker_qty, 0) },
              { key: "difference", label: "Diff", align: "right", fmt: (r) => <span className={r.difference === 0 ? "text-up" : "text-down"}>{signed(r.difference, 0)}</span> },
            ]} />
        ) : (
          <p className="text-[12px] text-muted">No positions on either side yet.</p>
        )}
      </Panel>
      <Panel>
        <SectionTitle>Broker orders</SectionTitle>
        {state.orders?.length ? (
          <DataTable max={280} rows={state.orders}
            cols={[
              { key: "order_id", label: "Order" },
              { key: "symbol", label: "Instrument" },
              { key: "side", label: "Side" },
              { key: "qty", label: "Qty", align: "right" },
              { key: "status", label: "Status" },
            ]} />
        ) : (
          <p className="text-[12px] text-muted">No broker orders today.</p>
        )}
      </Panel>
    </div>
  );
}

/* ======================= Markets: what each source can actually support ======================= */

/** Cross-market surface comparison.
 *
 * The point of this view is not to draw a prettier smile — it is to make the *limit* of each
 * data source visible. A surface plotted alone always looks authoritative; plotted next to its
 * fit error and its longest trustworthy tenor, it tells you which products it can price. The
 * Indian broker feed fits beautifully and spans weeks; the US chain fits slightly worse and
 * spans years. That difference decides whether a 3-year note is priceable at all, and it is
 * invisible on any single-market screen.
 */
export function Markets() {
  const [markets, setMarkets] = useState<MarketMeta[]>([]);
  const [symbol, setSymbol] = useState("SPX");
  const [data, setData] = useState<Market | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getMarkets().then((r) => setMarkets(r.markets)).catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    let live = true;
    setBusy(true);
    setErr(null);
    getMarket(symbol)
      .then((m) => live && setData(m))
      .catch((e) => live && setErr(String(e.message ?? e)))
      .finally(() => live && setBusy(false));
    return () => {
      live = false;
    };
  }, [symbol]);

  const fit = data?.fit;
  // A tenor the surface cannot reach is the binding constraint on the product shelf, so it is
  // shown as a headline number rather than buried in the per-slice table.
  const reachTone: "" | "pos" | "neg" = !fit
    ? ""
    : fit.max_reliable_tenor >= 2
      ? "pos"
      : fit.max_reliable_tenor >= 0.75
        ? ""
        : "neg";
  const smileRows = (data?.smile ?? []).flatMap((s) =>
    s.points.map((p) => ({ k: p.k, [`T${s.tau.toFixed(2)}`]: p.vol * 100 })),
  );
  const merged = Object.values(
    smileRows.reduce<Record<string, any>>((acc, row) => {
      const key = String(row.k);
      acc[key] = { ...(acc[key] ?? { k: row.k }), ...row };
      return acc;
    }, {}),
  ).sort((a: any, b: any) => a.k - b.k);
  const tenorKeys = (data?.smile ?? []).map((s) => `T${s.tau.toFixed(2)}`);

  return (
    <div className="space-y-4">
      <Panel>
        <SectionTitle>Market</SectionTitle>
        <div className="mt-3 flex flex-wrap gap-2">
          {markets.map((m) => (
            <button
              key={m.symbol}
              onClick={() => setSymbol(m.symbol)}
              className={cn(
                "rounded-lg border px-3 py-1.5 text-small transition-colors",
                m.symbol === symbol
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border text-muted hover:border-accent/50",
              )}
            >
              <span className="font-semibold">{m.symbol}</span>
              <span className="ml-2 opacity-70">{m.region} · {m.source}</span>
            </button>
          ))}
        </div>
        {busy && <div className="mt-3 text-small text-muted">calibrating {symbol}…</div>}
        {err && <div className="mt-3 text-small text-down">{err}</div>}
      </Panel>

      {data && fit && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Kpi label="Spot" value={fmt(data.spot, 2)} sub={`${data.meta.ccy ?? ""} · ${data.as_of}`} />
            <Kpi
              label="Longest reliable tenor"
              value={`${data.fit.max_reliable_tenor.toFixed(2)}y`}
              sub="slice still inside 200bps"
              tone={reachTone}
            />
            <Kpi
              label="Surface fit"
              value={fit.rmse_bps == null ? "—" : `${fit.rmse_bps.toFixed(0)} bps`}
              sub={`${fit.slices} slices · ${fit.reliable_pct ?? 0}% usable`}
            />
            <Kpi
              label="Quotes used"
              value={compact(data.calibrated_on)}
              sub={`of ${compact(data.contracts)} listed`}
            />
          </div>

          <Panel>
            <SectionTitle>Chain quality</SectionTitle>
            <div className="mt-3 grid grid-cols-2 gap-4 text-small lg:grid-cols-4">
              <div>
                <div className="text-muted">Traded today</div>
                <div className="tnum mt-1 text-[15px]">
                  {compact(data.traded_today)}{" "}
                  <span className="text-muted">({Math.round((100 * data.traded_today) / Math.max(data.contracts, 1))}%)</span>
                </div>
              </div>
              <div>
                <div className="text-muted">With open interest</div>
                <div className="tnum mt-1 text-[15px]">
                  {compact(data.with_open_interest)}{" "}
                  <span className="text-muted">({Math.round((100 * data.with_open_interest) / Math.max(data.contracts, 1))}%)</span>
                </div>
              </div>
              <div>
                <div className="text-muted">Two-sided quotes</div>
                <div className="tnum mt-1 text-[15px]">
                  {compact(data.two_sided)}{" "}
                  <span className="text-muted">({Math.round((100 * data.two_sided) / Math.max(data.contracts, 1))}%)</span>
                </div>
              </div>
              <div>
                <div className="text-muted">Arbitrage-free</div>
                <div className={cn("mt-1 text-[15px]", fit.arbitrage_clean ? "text-up" : "text-down")}>
                  {fit.arbitrage_clean ? "clean" : "violations"}
                </div>
              </div>
            </div>
            <p className="mt-3 text-small text-muted">
              A settlement price is published for every listed contract whether or not it traded.
              The gap between “listed” and “traded / with open interest” is how much of this chain
              is an exchange computation rather than a market — those quotes are screened out
              before calibration.
            </p>
          </Panel>

          <Panel>
            <SectionTitle>Smile by tenor</SectionTitle>
            {merged.length > 0 ? (
              <Lines
                data={merged}
                x="k"
                xLabel="log-moneyness  k = log(K/F)"
                yLabel="implied vol (%)"
                height={320}
                series={tenorKeys.slice(0, 6).map((key, i) => ({
                  key,
                  name: `${key.slice(1)}y`,
                  color: [C.accent, C.teal, C.violet, C.up, C.down, C.muted][i] ?? C.accent,
                }))}
              />
            ) : (
              <div className="mt-3 text-small text-muted">no calibrated slices</div>
            )}
          </Panel>

          <Panel>
            <SectionTitle>Per-slice fit</SectionTitle>
            <DataTable
              rows={fit.per_slice.map((s) => ({
                tenor: `${s.tau.toFixed(3)}y`,
                quotes: s.n,
                rmse: `${s.rmse_bps.toFixed(0)} bps`,
                usable: s.rmse_bps <= 200 ? "yes" : "no",
              }))}
              cols={[
                { key: "tenor", label: "Tenor" },
                { key: "quotes", label: "Quotes", align: "right" },
                { key: "rmse", label: "Fit RMSE", align: "right" },
                { key: "usable", label: "Priceable" },
              ]}
            />
          </Panel>
        </>
      )}
    </div>
  );
}

/* ======================= US shelf: real filed notes and the issuer's own price ======================= */

/** Products actually issued in the US market, from SEC 424B2 pricing supplements.
 *
 * Every other screen in this app shows the model's own output. This one shows somebody else's:
 * since 2012 an issuer must disclose the note's *initial estimated value* — its own model price
 * — alongside the price it sold at. That single number is the only external benchmark the
 * project has, and the gap between it and the offering price is the dealer's fee and funding
 * load, typically 2–5 points of par.
 *
 * The shelf's *shape* matters as much as any individual note: most issuance is worst-of on
 * single stocks, which is short correlation — an input with no liquid market. That is why
 * correlation, not volatility, is the binding unknown when pricing this shelf.
 */
export function UsShelf() {
  const [shelf, setShelf] = useState<Shelf | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [kind, setKind] = useState<"all" | "worst-of" | "basket" | "single">("all");

  useEffect(() => {
    getShelf()
      .then(setShelf)
      .catch((e) => setErr(String(e.message ?? e)));
  }, []);

  if (err) {
    return (
      <Panel>
        <SectionTitle>US shelf</SectionTitle>
        <div className="mt-3 text-small text-down">{err}</div>
        <p className="mt-2 text-small text-muted">
          Needs network access to SEC EDGAR, and SPDT_SEC_USER_AGENT set to a contact string —
          SEC asks automated clients to identify themselves.
        </p>
      </Panel>
    );
  }
  if (!shelf) {
    return (
      <Panel>
        <SectionTitle>US shelf</SectionTitle>
        <div className="mt-3 text-small text-muted">
          reading SEC filings… the first fetch walks the full-text index and one document per hit,
          rate-limited to SEC's ceiling, so it takes a few minutes.
        </div>
      </Panel>
    );
  }

  const s = shelf.stats;
  const rows = shelf.filings.filter((f) => kind === "all" || f.kind === kind);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Notes on the shelf" value={String(s.n ?? 0)} sub="benchmarkable, deduped" />
        <Kpi
          label="Worst-of"
          value={`${s.worst_of_pct ?? 0}%`}
          sub={`${s.worst_of ?? 0} of ${s.n ?? 0} — short correlation`}
        />
        <Kpi
          label="Mean disclosed load"
          value={s.mean_load_pct == null ? "—" : `${s.mean_load_pct.toFixed(2)} pts`}
          sub="offering price − issuer's own value"
        />
        <Kpi label="Mean tenor" value={`${(s.mean_tenor ?? 0).toFixed(2)}y`} sub="to maturity" />
      </div>

      <Panel>
        <SectionTitle>Why this is a benchmark</SectionTitle>
        <p className="mt-2 text-small text-muted">
          The <span className="text-ink">estimated value</span> is the issuer's own model price,
          published in the prospectus. A model that reproduces the <em>offering</em> price of 100
          has not validated — it has absorbed the dealer's fee into a risk-neutral value. Matching
          the estimated value is the real test, and the gap between the two columns is the fee and
          funding load being charged.
        </p>
        <p className="mt-2 text-small text-muted">
          Most of these are worst-of, whose value turns on correlation between the legs. Each leg's
          volatility is observable from listed options; correlation is not — so it is the one free
          parameter, and it can be solved for from the disclosed value. That is what
          <span className="text-ink"> spdt.validation.run_correlation</span> does.
        </p>
      </Panel>

      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <SectionTitle>Filed notes</SectionTitle>
          <div className="flex gap-1.5">
            {(["all", "worst-of", "basket", "single"] as const).map((k) => (
              <button
                key={k}
                onClick={() => setKind(k)}
                className={cn(
                  "rounded-lg border px-2.5 py-1 text-small transition-colors",
                  k === kind
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-border text-muted hover:border-accent/50",
                )}
              >
                {k}
              </button>
            ))}
          </div>
        </div>
        <div className="mt-3">
          <DataTable
            rows={rows.map((f) => ({
              issuer: f.issuer.replace(/\s+(INC|LLC|CORP).*$/i, ""),
              kind: f.kind,
              names: f.underlyings.slice(0, 3).join("/") || "—",
              tenor: f.tenor_years == null ? "—" : `${f.tenor_years.toFixed(2)}y`,
              barrier: f.knock_in == null ? "—" : `${Math.round(f.knock_in * 100)}%`,
              coupon: `${f.coupon_per_period_pct.toFixed(2)}%`,
              ev: f.estimated_value_pct == null ? "—" : f.estimated_value_pct.toFixed(2),
              load: f.disclosed_load_pct == null ? "—" : f.disclosed_load_pct.toFixed(2),
              _url: f.url,
            }))}
            cols={[
              { key: "issuer", label: "Issuer" },
              { key: "kind", label: "Type" },
              { key: "names", label: "Underlyings" },
              { key: "tenor", label: "Tenor", align: "right" },
              { key: "barrier", label: "Knock-in", align: "right" },
              { key: "coupon", label: "Coupon / period", align: "right" },
              { key: "ev", label: "Issuer value", align: "right" },
              { key: "load", label: "Load (pts)", align: "right" },
              {
                key: "_url",
                label: "Filing",
                fmt: (r: any) => (
                  <a className="text-accent hover:underline" href={r._url} target="_blank" rel="noreferrer">
                    SEC
                  </a>
                ),
              },
            ]}
          />
        </div>
      </Panel>

      <Panel>
        <SectionTitle>Most-referenced underlyings</SectionTitle>
        <p className="mt-2 text-small text-muted">
          These drive the single-name entries in the Markets tab — the list is read off the shelf
          rather than chosen, so it follows whatever dealers are currently issuing against.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {shelf.names.map((n) => (
            <span key={n.symbol} className="rounded-lg border border-border px-2.5 py-1 text-small">
              <span className="font-semibold text-ink">{n.symbol}</span>
              <span className="ml-1.5 text-muted">{n.notes}</span>
            </span>
          ))}
        </div>
      </Panel>
    </div>
  );
}
