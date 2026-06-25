import { useEffect, useState } from "react";
import { Decision, Desk, PriceResult, StructureResult, XvaResult, computeXva, priceTrade, solveStructure } from "./lib/api";
import { TYPE_ABBR, Trade, bookTrades, priceReq, productLabel } from "./lib/trades";
import { Chip, DataTable, Kpi, Panel, SectionTitle } from "./components/ui";
import { AreaSpark, Bars, Histogram, Lines, Surface3D, Waterfall } from "./components/charts";
import { cn } from "./lib/cn";
import { fmt, pct, signed } from "./lib/format";
import { C } from "./lib/theme";

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

/* ======================= Overview ======================= */

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
  const [activeProduct, setActiveProduct] = useState<string | null>(null); // null ⇒ use the recommendation
  const [res, setRes] = useState<StructureResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [staged, setStaged] = useState(false);

  useEffect(() => {
    let cancel = false;
    setLoading(true);
    const id = setTimeout(() => {
      solveStructure({ target_coupon: tc, max_downside: dd, maturity: mat, obs_per_year: obs, fee, objective, prefer_basket: preferBasket, product: activeProduct })
        .then((r) => !cancel && setRes(r)).finally(() => !cancel && setLoading(false));
    }, 250);
    return () => { cancel = true; clearTimeout(id); };
  }, [tc, dd, mat, obs, fee, objective, preferBasket, activeProduct]);

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
          <Slider label="Maturity (years)" value={mat} min={1} max={3} step={1} onChange={setMat} display={`${mat}y`} />
          <Slider label="Observations / year" value={obs} min={2} max={12} step={2} onChange={setObs} display={`${obs}`} />
          <Slider label="Placement fee" value={fee} min={0} max={3} step={0.25} onChange={setFee} display={`${fee.toFixed(2)}`} />
        </div>
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
  );
}

/* ======================= Validate ======================= */

export function Validate({ desk, selectedId }: { desk: Desk; selectedId: string | null }) {
  const rows = [...desk.reserves].sort((a, b) => b.lsv_minus_lv - a.lsv_minus_lv);
  const b = desk.backtest;
  return (
    <div className="space-y-5">
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
          <Slider label="Funding spread" value={fund} min={0} max={150} step={10} onChange={setFund} display={`${fund}bp`} />
          <Slider label="RAROC hurdle" value={hurdle} min={0.05} max={0.25} step={0.01} onChange={setHurdle} display={pct(hurdle, 0)} />
          <Slider label="Structuring margin" value={margin} min={0} max={6} step={0.25} onChange={setMargin} display={fmt(margin, 2)} />
          <Slider label="EAD limit (0=off)" value={eadLimit} min={0} max={400} step={10} onChange={setEadLimit} display={eadLimit > 0 ? fmt(eadLimit, 0) : "off"} />
        </div>
        <div className="mt-4 border-t border-border-soft pt-4">
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
