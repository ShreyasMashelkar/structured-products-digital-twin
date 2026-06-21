import { useEffect, useMemo, useState } from "react";
import { Desk, getDesk, priceTrade } from "./lib/api";
import { Trade, bookTrades, priceReq } from "./lib/trades";
import { Kpi, Tabs } from "./components/ui";
import { cn } from "./lib/cn";
import { compact, fmt, signed } from "./lib/format";
import { BookRisk, CounterpartyXva, Originate, Overview, Validate } from "./views";

const WORKSPACES = ["Overview", "Originate", "Book & Risk", "Counterparty & XVA", "Validate"];

// Rough standard normal (sum of uniforms) for the simulated tick.
const gauss = () => Math.random() + Math.random() + Math.random() - 1.5;

interface Market {
  spotMult: number; // live spot = base spot × this
  dVol: number; // additive vol points
}

function Masthead({
  desk, spot, vol, spotChgBp, sim, onToggle,
}: { desk: Desk; spot: number; vol: number; spotChgBp: number; sim: boolean; onToggle: () => void }) {
  const m = desk.model;
  const up = spotChgBp >= 0;
  return (
    <div className="mb-5 flex items-end justify-between border-b border-border-soft pb-4">
      <div>
        <span className="text-display font-extrabold tracking-tight text-ink">
          SPDT <span className="text-accent">//</span> Structuring Desk
        </span>
        <button
          onClick={onToggle}
          title="Toggle the simulated market tick"
          className={cn(
            "ml-2.5 inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 align-middle text-[10px] font-bold uppercase tracking-[0.16em] transition-colors",
            sim ? "border-up/50 bg-up/10 text-up" : "border-border bg-panel2 text-muted",
          )}
        >
          <span className={cn("h-1.5 w-1.5 rounded-full", sim ? "animate-pulse bg-up" : "bg-muted")} />
          {sim ? "sim" : "paused"}
        </button>
      </div>
      <div className="tnum text-right text-[12px] leading-relaxed text-muted">
        {desk.underlying} · spot{" "}
        <b className={cn(sim ? (up ? "text-up" : "text-down") : "text-ink")}>{compact(spot)}</b>
        {sim && <span className={cn("ml-1", up ? "text-up" : "text-down")}>{up ? "▲" : "▼"}{Math.abs(spotChgBp).toFixed(0)}bp</span>} · {desk.as_of}
        <span className="ml-1.5 rounded border border-border px-1 py-px text-[9px] font-bold uppercase tracking-[0.1em] text-faint">
          {desk.data_source}
        </span>
        <br />
        ATM vol <b className={cn(sim ? "text-teal" : "text-ink")}>{(vol * 100).toFixed(1)}%</b> · r{" "}
        <b className="text-ink">{(m.r * 100).toFixed(2)}%</b> · q <b className="text-ink">{(m.q * 100).toFixed(2)}%</b> · funding{" "}
        <b className="text-ink">+{desk.funding_spread_bp}bp</b>
        <br />
        surface <b className="text-ink">{desk.arb_clean ? "arb-free" : "FLAGGED"}</b> · overnight move +{desk.market_move.spot_bp}bp spot
        / +{desk.market_move.vol_pt} vol
      </div>
    </div>
  );
}

function KpiStrip({
  desk, nNotes, nav, cashDelta, vegaPt, sim, markMove,
}: { desk: Desk; nNotes: number; nav: number; cashDelta: number; vegaPt: number; sim: boolean; markMove: number }) {
  const worst = Math.min(...desk.stress.map((s) => s.pnl));
  return (
    <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
      <Kpi
        label="Book NAV"
        value={sim ? fmt(nav, 2) : compact(nav)}
        sub={sim ? `${nNotes} notes · ${signed(markMove, 2)} sim` : `${nNotes} notes`}
        flashKey={Math.round(nav * 100)}
      />
      <Kpi label="Overnight P&L" value={signed(desk.day_pnl, 2)} sub="Taylor explain" tone={desk.day_pnl >= 0 ? "pos" : "neg"} />
      <Kpi label="Net Δ" value={signed(cashDelta, 2)} sub="per +1% spot" tone={cashDelta >= 0 ? "pos" : "neg"} flashKey={Math.round(cashDelta * 100)} />
      <Kpi label="Net Vega" value={signed(vegaPt, 2)} sub="per +1 vol pt" tone={vegaPt >= 0 ? "pos" : "neg"} flashKey={Math.round(vegaPt * 100)} />
      <Kpi label="Model reserve" value={fmt(desk.total_model_reserve, 2)} sub="LSV − LV" tone="accent" />
      <Kpi label="Worst stress" value={compact(worst)} sub="equity crash" tone="neg" />
    </div>
  );
}

export default function App() {
  const [desk, setDesk] = useState<Desk | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [ws, setWs] = useState(WORKSPACES[0]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [staged, setStaged] = useState<Trade[]>([]);
  const [tenorFilter, setTenorFilter] = useState<string | null>(null);
  const [sim, setSim] = useState(true);
  const [market, setMarket] = useState<Market>({ spotMult: 1, dVol: 0 });

  useEffect(() => {
    getDesk().then(setDesk).catch((e) => setErr(String(e)));
  }, []);

  // Simulated market tick: a gentle mean-reverting random walk on spot and vol.
  useEffect(() => {
    if (!sim) return;
    const id = setInterval(() => {
      setMarket((mk) => {
        const spotMult = Math.min(1.03, Math.max(0.97, mk.spotMult * (1 + 0.0009 * gauss())));
        const dVol = Math.min(0.03, Math.max(-0.03, mk.dVol + 0.0006 * gauss() - 0.05 * mk.dVol));
        return { spotMult, dVol };
      });
    }, 700);
    return () => clearInterval(id);
  }, [sim]);

  const trades = useMemo(() => (desk ? [...staged, ...bookTrades(desk)] : []), [desk, staged]);

  // Honest aggregates: booked net greeks + staged marks, re-marked through the book's own
  // Greeks for the simulated move (Δ·dS + ½Γ·dS² + ν·dσ) — the desk's Taylor explain, live.
  const agg = useMemo(() => {
    if (!desk) return null;
    const sumStaged = (k: keyof Trade) => staged.reduce((a, t) => a + ((t[k] as number) ?? 0), 0);
    const rawDelta = desk.net_greeks.delta + sumStaged("delta");
    const gamma = desk.net_greeks.gamma + sumStaged("gamma");
    const vega = desk.net_greeks.vega + sumStaged("vega");
    const vanna = desk.net_greeks.vanna; // book cross-greeks (staged not yet re-marked for these)
    const volga = desk.net_greeks.volga;
    const stagedPv = sumStaged("pv");
    const dS = desk.spot * (market.spotMult - 1);
    const dVol = market.dVol;
    // Re-mark the book through its own greeks: PV by Δ/Γ/ν, delta by Γ (spot) + vanna (vol),
    // vega by vanna (spot) + volga (vol). So vega ticks like delta does, not frozen.
    const markMove = sim ? rawDelta * dS + 0.5 * gamma * dS * dS + vega * dVol + vanna * dS * dVol : 0;
    const liveSpot = sim ? desk.spot * market.spotMult : desk.spot;
    const liveVol = sim ? desk.model.atm_vol + market.dVol : desk.model.atm_vol;
    const liveDelta = rawDelta + (sim ? gamma * dS + vanna * dVol : 0);
    const liveVega = vega + (sim ? vanna * dS + volga * dVol : 0);
    return {
      nav: desk.nav + stagedPv + markMove,
      cashDelta: liveDelta * liveSpot * 0.01,
      vegaPt: liveVega / 100,
      markMove,
      liveSpot,
      liveVol,
      spotChgBp: (market.spotMult - 1) * 1e4,
      dS,
      dVol,
    };
  }, [desk, staged, market, sim]);

  if (err) return <div className="grid h-screen place-items-center text-down">Failed to load desk: {err}</div>;
  if (!desk || !agg) return <div className="grid h-screen place-items-center text-muted"><div className="animate-pulse text-[13px] tracking-wide">Marking the book…</div></div>;

  const pickTrade = (id: string) => { setSelectedId(id); setWs("Book & Risk"); };
  const stageTrade = async (t: Trade) => {
    setStaged((s) => [t, ...s]);
    setSelectedId(t.trade_id);
    setWs("Book & Risk");
    try {
      const r = await priceTrade(priceReq(t));
      setStaged((s) =>
        s.map((x) =>
          x.trade_id === t.trade_id
            ? { ...x, pv: r.pv, delta: r.greeks.delta, gamma: r.greeks.gamma, vega: r.greeks.vega, rho: r.greeks.rho, day_pnl: 0 }
            : x,
        ),
      );
    } catch {
      /* leave unpriced */
    }
  };

  return (
    <div data-ws={ws}>
      {/* Ambient washes lean by workspace — gold when originating, teal when validating. */}
      <div className="wash-gold" />
      <div className="wash-teal" />
      <div className="relative z-10 mx-auto max-w-[1560px] px-6 py-5">
        <Masthead desk={desk} spot={agg.liveSpot} vol={agg.liveVol} spotChgBp={agg.spotChgBp} sim={sim} onToggle={() => setSim((s) => !s)} />
        <KpiStrip desk={desk} nNotes={trades.length} nav={agg.nav} cashDelta={agg.cashDelta} vegaPt={agg.vegaPt} sim={sim} markMove={agg.markMove} />
        <Tabs tabs={WORKSPACES} active={ws} onChange={setWs} />
        <div className="pt-5">
          {ws === "Overview" && <Overview desk={desk} onPickTrade={pickTrade} />}
          {ws === "Originate" && <Originate desk={desk} onStage={stageTrade} volShiftPct={Math.round((agg.liveVol - desk.model.atm_vol) * 1000) / 10} />}
          {ws === "Book & Risk" && (
            <BookRisk desk={desk} trades={trades} selectedId={selectedId} setSelectedId={setSelectedId} tenorFilter={tenorFilter} setTenorFilter={setTenorFilter} mk={{ dS: agg.dS, dVol: agg.dVol, liveSpot: agg.liveSpot, sim }} />
          )}
          {ws === "Counterparty & XVA" && <CounterpartyXva trades={trades} selectedId={selectedId} />}
          {ws === "Validate" && <Validate desk={desk} selectedId={selectedId} />}
        </div>
      </div>
    </div>
  );
}
