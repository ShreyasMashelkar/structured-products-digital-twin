import { useEffect, useState } from "react";
import { Desk, PriceResult, StructureResult, priceTrade, solveStructure } from "./lib/api";
import { TYPE_ABBR, Trade, bookTrades, priceReq, productLabel } from "./lib/trades";
import { Chip, DataTable, Kpi, Panel, SectionTitle } from "./components/ui";
import { AreaSpark, Bars, Histogram, Surface3D, Waterfall } from "./components/charts";
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
  const gamma = [...desk.positions].sort((a, b) => a.gamma - b.gamma).slice(0, 8).map((p) => ({ trade: p.trade_id, gamma: p.gamma }));
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
          <SectionTitle>Top gamma concentration</SectionTitle>
          <Bars data={gamma} x="trade" y="gamma" color={C.down} height={300} horizontal />
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

export function Originate({ desk, onStage }: { desk: Desk; onStage: (t: Trade) => void }) {
  const [tc, setTc] = useState(0.12);
  const [dd, setDd] = useState(0.3);
  const [mat, setMat] = useState(1);
  const [obs, setObs] = useState(4);
  const [res, setRes] = useState<StructureResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [staged, setStaged] = useState(false);

  useEffect(() => {
    let cancel = false;
    setLoading(true);
    const id = setTimeout(() => {
      solveStructure({ target_coupon: tc, max_downside: dd, maturity: mat, obs_per_year: obs })
        .then((r) => !cancel && setRes(r)).finally(() => !cancel && setLoading(false));
    }, 250);
    return () => { cancel = true; clearTimeout(id); };
  }, [tc, dd, mat, obs]);

  function addToBook() {
    if (!res?.solved_annual_coupon) return;
    const n = Math.round(mat * obs);
    const step = 1 / obs;
    const observation_times = Array.from({ length: n }, (_, i) => +(((i + 1) * step).toFixed(10)));
    const id = `STG-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
    onStage({
      trade_id: id, product_type: "autocallable", label: productLabel("autocallable"),
      notional: 100, observation_times, maturity: mat, staged: true,
      params: { coupon_rate: res.solved_annual_coupon / obs, autocall_level: 1.0, coupon_barrier: res.knock_in, knock_in: res.knock_in, memory: true },
    });
    setStaged(true);
    setTimeout(() => setStaged(false), 2200);
  }

  const curve = res?.pv_curve ?? [];
  const lo = curve.length ? Math.floor(Math.min(...curve.map((c) => c.pv))) : 90;
  const hi = curve.length ? Math.ceil(Math.max(...curve.map((c) => c.pv))) : 110;

  return (
    <div className="space-y-4">
      <SectionTitle>Client brief → proposed structure → solve to par → book</SectionTitle>
      <Panel className="p-4">
        <div className="grid grid-cols-1 gap-5 md:grid-cols-4">
          <Slider label="Target annual coupon" value={tc} min={0.04} max={0.2} step={0.01} onChange={setTc} display={pct(tc, 0)} />
          <Slider label="Downside they can stomach" value={dd} min={0.1} max={0.5} step={0.05} onChange={setDd} display={pct(dd, 0)} />
          <Slider label="Maturity (years)" value={mat} min={1} max={3} step={1} onChange={setMat} display={`${mat}y`} />
          <Slider label="Observations / year" value={obs} min={2} max={12} step={2} onChange={setObs} display={`${obs}`} />
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <Panel className="p-4 lg:col-span-2">
          <div className="mb-3 flex flex-wrap gap-1.5">
            <Chip hot>Phoenix autocallable</Chip>
            <Chip>knock-in {res ? pct(res.knock_in, 0) : "—"}</Chip>
            <Chip>memory coupon</Chip>
          </div>
          {res?.solved_annual_coupon != null ? (
            <>
              <div className="text-[11px] uppercase tracking-[0.1em] text-muted">Solved coupon to par (1.00 fee)</div>
              <div className="tnum mt-1 text-hero font-bold leading-none text-ink">{pct(res.solved_annual_coupon, 2)}<span className="ml-1.5 text-figure font-medium text-muted">p.a.</span></div>
              <div className="mt-1.5 text-[12px] text-muted">vs indicative {pct(res.indicative_annual_coupon, 2)} · model PV <span className="tnum text-ink">{fmt(res.achieved_pv ?? 0, 2)}</span></div>
              <div className={cn("mt-3 rounded-lg border px-3 py-2 text-[12px]", res.achievable ? "border-up/30 bg-up/5 text-up" : "border-down/30 bg-down/5 text-down")}>
                {res.achievable ? `The client's ${pct(tc, 0)} ask is achievable at this knock-in.` : `The client's ${pct(tc, 0)} ask needs a lower knock-in or more downside sold.`}
              </div>
              <button onClick={addToBook}
                className="ring-desk mt-3 w-full rounded-lg border border-accent/60 bg-accent/15 px-3 py-2 text-body font-semibold text-accent transition-colors hover:bg-accent/25">
                {staged ? "✓ Added to book" : "Add to book →"}
              </button>
            </>
          ) : (<div className="text-[13px] text-muted">{loading ? "Solving…" : "No coupon prices this to par."}</div>)}
        </Panel>
        <Panel className="p-3 lg:col-span-3">
          <AreaSpark data={curve} x="annual_coupon" y="pv" color={C.teal} height={300} yDomain={[lo, hi]} xLabel="annual coupon (%)" yLabel="model PV" yTickFormat={(v) => v.toFixed(0)} />
        </Panel>
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
        <Surface3D z={desk.surface.iv} x={desk.surface.log_moneyness} y={desk.surface.tenors} height={460} />
      </Panel>
    </div>
  );
}

/* ======================= Trade detail (live price) ======================= */

export function TradeDetail({ trade, desk }: { trade: Trade; desk: Desk }) {
  const [r, setR] = useState<PriceResult | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancel = false;
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
        <span className="tnum text-[12px] text-muted">{loading ? "pricing…" : `PV ${fmt(r?.pv ?? 0, 3)} ± ${fmt(r?.std_error ?? 0, 3)}`}</span>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <Chip>{trade.maturity.toFixed(2)}y</Chip>
        {trade.params.coupon_rate != null && <Chip>coupon {fmt(trade.params.coupon_rate * 100, 2)}%</Chip>}
        {trade.params.knock_in != null && <Chip>KI {pct(trade.params.knock_in, 0)}</Chip>}
        {trade.params.autocall_level != null && <Chip>AC {pct(trade.params.autocall_level, 0)}</Chip>}
        {trade.params.protection != null && <Chip>protection {pct(trade.params.protection, 0)}</Chip>}
        {trade.params.participation != null && <Chip>{fmt(trade.params.participation, 2)}× upside</Chip>}
        {trade.params.memory && <Chip hot>memory</Chip>}
      </div>

      {r && (
        <>
          <div className="grid grid-cols-4 gap-2">
            <GreekStat label="Δ / 1%" value={signed(r.greeks.cash_delta, 2)} tone={r.greeks.cash_delta >= 0 ? "pos" : "neg"} />
            <GreekStat label="Γ" value={fmt(r.greeks.gamma, 5)} />
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

function Blotter({ trades, selectedId, onSelect, tenorFilter, onClearFilter }: {
  trades: Trade[]; selectedId: string | null; onSelect: (id: string) => void; tenorFilter: string | null; onClearFilter: () => void;
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
              const cd = t.delta != null ? t.delta * 0 + t.delta : 0; // book delta already cash-ish via marks
              const sel = t.trade_id === selectedId;
              return (
                <tr key={t.trade_id} onClick={() => onSelect(t.trade_id)} tabIndex={0}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(t.trade_id))}
                  className={cn("ring-desk cursor-pointer transition-colors", sel ? "bg-accent/10" : "hover:bg-white/[0.03]")}>
                  <td className={cn("tnum border-b border-border-soft px-2.5 py-1.5", sel ? "text-accent" : "text-ink/90", t.staged && "italic")}>{t.trade_id}</td>
                  <td className="border-b border-border-soft px-2.5 py-1.5 text-small text-muted">
                    {TYPE_ABBR[t.product_type] ?? t.product_type}{t.staged && <span className="ml-1 text-violet">•</span>}
                  </td>
                  <td className="tnum border-b border-border-soft px-2.5 py-1.5 text-right text-ink/80">{t.maturity.toFixed(1)}y</td>
                  <td className="tnum border-b border-border-soft px-2.5 py-1.5 text-right text-ink/80">{t.pv != null ? fmt(t.pv, 1) : "—"}</td>
                  <td className={cn("tnum border-b border-border-soft px-2.5 py-1.5 text-right", (t.delta ?? 0) >= 0 ? "text-up/90" : "text-down/90")}>{t.delta != null ? signed(t.delta, 2) : "—"}</td>
                  <td className={cn("tnum border-b border-border-soft px-2.5 py-1.5 text-right", (t.vega ?? 0) >= 0 ? "text-up/90" : "text-down/90")}>{t.vega != null ? signed(t.vega / 100, 2) : "—"}</td>
                  <td className={cn("tnum border-b border-border-soft px-2.5 py-1.5 text-right", (t.day_pnl ?? 0) >= 0 ? "text-up/90" : "text-down/90")}>{t.day_pnl != null ? signed(t.day_pnl, 2) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BookAggregate({ desk, onPickTenor }: { desk: Desk; onPickTenor: (b: string) => void }) {
  const ladder = Object.entries(desk.vega_ladder).map(([k, v]) => ({ bucket: k, vega: v / 100 }));
  const gamma = [...desk.positions].sort((a, b) => a.gamma - b.gamma).map((p) => ({ trade: p.trade_id, gamma: p.gamma }));
  const g = desk.net_greeks;
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
        <SectionTitle>Gamma concentration</SectionTitle>
        <Bars data={gamma} x="trade" y="gamma" color={C.down} height={300} horizontal />
      </Panel>
      <div className="flex flex-wrap gap-1.5">
        <Chip>net Δ {fmt(g.delta, 4)}</Chip><Chip>net Γ {fmt(g.gamma, 5)}</Chip>
        <Chip>net ν {fmt(g.vega, 1)}</Chip><Chip>net ρ {fmt(g.rho, 1)}</Chip>
      </div>
    </div>
  );
}

export function BookRisk({ desk, trades, selectedId, setSelectedId, tenorFilter, setTenorFilter }: {
  desk: Desk; trades: Trade[]; selectedId: string | null; setSelectedId: (id: string | null) => void;
  tenorFilter: string | null; setTenorFilter: (b: string | null) => void;
}) {
  const selected = trades.find((t) => t.trade_id === selectedId) ?? null;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
      <div className="lg:col-span-2">
        <Blotter trades={trades} selectedId={selectedId} onSelect={(id) => setSelectedId(id === selectedId ? null : id)} tenorFilter={tenorFilter} onClearFilter={() => setTenorFilter(null)} />
      </div>
      <Panel className="p-4 lg:col-span-3">
        {selected ? (
          <TradeDetail trade={selected} desk={desk} />
        ) : (
          <BookAggregate desk={desk} onPickTenor={setTenorFilter} />
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
          <SectionTitle>Dynamic hedge replication error</SectionTitle>
          <AreaSpark data={desk.hedging} x="n_steps" y="std_pnl" color={C.down} height={300} logX xLabel="rebalances" yLabel="hedging P&L std" />
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
