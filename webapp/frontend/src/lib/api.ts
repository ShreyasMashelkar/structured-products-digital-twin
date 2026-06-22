export interface Desk {
  as_of: string;
  data_date?: string;
  data_source: string;
  underlying: string;
  spot: number;
  model: { r: number; q: number; atm_vol: number };
  market_move: { spot_bp: number; vol_pt: number; horizon_days: number };
  nav: number;
  day_pnl: number;
  net_greeks: { delta: number; gamma: number; vega: number; rho: number; vanna: number; volga: number };
  total_reserve: number;
  total_model_reserve: number;
  funding_spread_bp: number;
  positions: any[];
  pnl_explain: Record<string, number>;
  pnl_by_trade: any[];
  stress: { scenario: string; pnl: number; pct: number }[];
  stress_by_trade: Record<string, Record<string, number>>;
  reserves: any[];
  vega_ladder: Record<string, number>;
  surface: { log_moneyness: number[]; tenors: number[]; iv: number[][] };
  arb_clean: boolean;
  hedging: any[];
  backtest: any;
  catalog: any[];
  hedge_capacity: {
    book_face_inr: number;
    hedge_notional_inr: number;
    adv_inr: number;
    participation: number;
    days_to_hedge: number;
    within_capacity: boolean;
  };
  correlation_risk: {
    net_corr_delta: number;
    baskets: { trade_id: string; underlyings: string[]; correlation: number; corr_delta: number; pv: number; coupon: number }[];
  };
}

export interface StructureResult {
  knock_in: number;
  indicative_annual_coupon: number;
  solved_annual_coupon: number | null;
  achieved_pv: number | null;
  target_pv: number;
  pv_curve: { annual_coupon: number; pv: number }[];
  achievable: boolean;
}

export interface PriceRequest {
  product_type: string;
  notional: number;
  observation_times?: number[];
  maturity?: number;
  params: Record<string, any>;
}

export interface PriceResult {
  pv: number;
  std_error: number;
  greeks: { delta: number; gamma: number; vega: number; rho: number; cash_delta: number; vega_pt: number };
  scenarios: { terminal_level: number; ki_breached: boolean; payment_pct: number }[];
  stress: { scenario: string; pnl: number }[];
}

export interface XvaRequest {
  product_type: string;
  notional: number;
  observation_times?: number[];
  maturity?: number;
  params: Record<string, any>;
  counterparty?: string;
  cds_spread_bps: number;
  cds_1y_bps?: number;
  recovery_rate: number;
  funding_spread_bp: number;
  hurdle_rate: number;
  margin?: number;
  ead_limit?: number;
  pfe_limit?: number;
  own_cds_bps?: number;
  cost_of_capital: number;
  include_mva: boolean;
  wwr_beta: number;
  collateralised: boolean;
  single_name: boolean;
}

export type Decision = "APPROVED" | "REJECTED" | "MANUAL_REVIEW";

export interface XvaResult {
  charge: { cva: number; fva: number; dva: number; kva: number; mva: number; total: number };
  metrics: { ead: number; pfe: number; epe: number; ee_peak: number; expected_loss: number };
  sensitivities: { cs01: number; jtd_gross: number; jtd_net: number };
  capital: { economic: number; regulatory_bacva: number; saccr_ead: number; bacva_risk_weight_pct: number };
  decision: Decision;
  reasons: string[];
  limit_status: "PASS" | "WARNING" | "FAIL";
  trade_raroc: number;
  margin: number;
  collateralised: boolean;
  profile: { t: number; ee: number }[];
  spread_curve: { cds_bp: number; cva: number; total: number }[];
  stress_ladder: { shift_bp: number; cva: number; total: number }[];
  inputs: { cds_spread_bps: number; recovery_rate: number; funding_spread_bp: number; hurdle_rate: number };
}

export async function computeXva(req: XvaRequest): Promise<XvaResult> {
  const r = await fetch("/api/xva", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw new Error("xva failed");
  return r.json();
}

export async function priceTrade(req: PriceRequest): Promise<PriceResult> {
  const r = await fetch("/api/price", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw new Error("price failed");
  return r.json();
}

export async function getDesk(): Promise<Desk> {
  const r = await fetch("/api/desk");
  if (!r.ok) throw new Error("desk fetch failed");
  return r.json();
}

export async function solveStructure(body: {
  target_coupon: number;
  max_downside: number;
  maturity: number;
  obs_per_year: number;
  fee?: number;
}): Promise<StructureResult> {
  const r = await fetch("/api/structure", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error("structure solve failed");
  return r.json();
}
