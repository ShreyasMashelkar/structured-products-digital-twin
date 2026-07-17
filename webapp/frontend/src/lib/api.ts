const API_TOKEN = import.meta.env.VITE_SPDT_API_TOKEN as string | undefined;

async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (API_TOKEN) headers.set("X-API-Token", API_TOKEN);
  const response = await fetch(input, { ...init, headers });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // Preserve the HTTP status when the response is not JSON.
    }
    throw new Error(detail);
  }
  return response;
}

export interface Desk {
  as_of: string;
  data_date?: string;
  data_source: string;
  data_source_detail?: string | null;
  data_boundary?: {
    equity: string;
    discount_curve: string;
    funding: string;
    fx_vol?: string | null;
  };
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

export interface StructureCandidate {
  product_type: string;
  label: string;
  rationale: string;
  fit_score: number;
}

export interface StructureResult {
  product_type: string;
  label: string;
  rationale: string;
  solve_for: string; // "coupon" | "participation"
  solved_annual_coupon: number | null;
  solved_participation: number | null;
  solved_display: string | null;
  indicative_annual_coupon: number | null;
  achieved_pv: number | null;
  target_pv: number;
  achievable: boolean;
  knock_in: number | null;
  book_params: Record<string, any>;
  book_observation_times: number[];
  book_maturity: number;
  x_label: string;
  pv_curve: { x: number; pv: number }[];
  alternatives: StructureCandidate[];
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
  all_in?: {
    coupon_base_pa?: number;
    coupon_all_in_pa?: number;
    drop_bp?: number;
    periods_per_year?: number;
    infeasible: boolean;
  } | null;
  collateralised: boolean;
  profile: { t: number; ee: number }[];
  spread_curve: { cds_bp: number; cva: number; total: number }[];
  stress_ladder: { shift_bp: number; cva: number; total: number }[];
  inputs: { cds_spread_bps: number; recovery_rate: number; funding_spread_bp: number; hurdle_rate: number };
}

export async function computeXva(req: XvaRequest): Promise<XvaResult> {
  const r = await apiFetch("/api/xva", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return r.json();
}

export async function priceTrade(req: PriceRequest): Promise<PriceResult> {
  const r = await apiFetch("/api/price", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return r.json();
}

export async function getDesk(): Promise<Desk> {
  const r = await apiFetch("/api/desk");
  return r.json();
}

export interface SemiStaticResult {
  selected_trade_id: string | null;
  message: string | null;
  pre_unwind: {
    trade_id: string; underlying: string; barrier_type: "KI" | "KO"; barrier: number; spot: number;
    distance_pct: number; p_hit: number; lifecycle_action: string;
    target_action_pct: number | null; executed_action_pct: number;
    incremental_action_pct: number; monitoring: string; status: string;
  }[];
  portfolio: {
    instrument: string; maturity: string; strike: number; weight: number; notional: number;
    delta: number; gamma: number; vega: number; purpose: string;
  }[];
  risk_ladder: {
    bucket: string; delta_target: number; delta_hedge: number;
    gamma_target: number; gamma_hedge: number;
    cash_delta_target_1pct: number; cash_delta_hedge_1pct: number;
    cash_gamma_target_1pct: number; cash_gamma_hedge_1pct: number;
  }[];
  tracking: {
    scenario: string; spot: number; target_pv: number; hedge_pv: number; error: number;
  }[];
  summary: {
    total_static_notional: number; residual_delta: number;
    residual_gamma: number; residual_cash_delta_1pct: number;
    residual_cash_gamma_1pct: number; tracking_error: number;
    gross_limit: number; perspective: string; position_label: string;
  };
  methodology?: { model: string; probability: string; strike_grid: string; position_perspective: string };
}

export async function getSemiStatic(body: {
  trades: any[]; spot: number; sigma: number; r: number; q: number;
  selected_trade_id: string | null;
}): Promise<SemiStaticResult> {
  const response = await apiFetch("/api/semistatic", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return response.json();
}

export interface OutcomeResult {
  as_of: string;
  contract_id: string;
  source_trade: { trade_id: string; underlying: string; notional: number; maturity: number;
    booked_coupon_pa_pct: number; knock_in_pct: number; coupon_barrier_pct: number; observation_frequency: string };
  run_metadata: { model: string; currency: string; seed_policy: string };
  issuance: {
    source: string; source_note: string; terms: string; n_issuances: number;
    autocall_rate_pct: number; loss_rate_pct: number; mean_return_pa_pct: number;
    median_life_years: number; tail_return_pct: number; worst_return_pct: number;
    robustness: { autocall_rate_range_pct: number[]; loss_rate_range_pct: number[]; n_paths: number };
    cohorts: { cohort: number; year: number; return_pct: number; life_years: number; outcome: string }[];
    index_path: { month: number; level: number }[];
  };
  hedge: {
    target: string; method: string; best_strategy: string; best_risk_reduction_pct: number; static_instruments: number;
    selection_rule: string; hybrid_static_scale_pct: number;
    strategies: { strategy: string; pnl_std: number; expected_shortfall_95: number; mean_pnl: number;
      turnover: number; transaction_cost: number; risk_reduction_pct: number; eligible: boolean; selection_score: number }[];
  };
  case_study: {
    title: string; brief: { objective: string; target_coupon_pa_pct: number; tenor_years: number; max_downside: string; counterparty_cds_bp: number; counterparty_role: string };
    structure: { product: string; booked_coupon_pa_pct: number; fair_coupon_before_xva_pct: number;
      offered_coupon_after_xva_pct: number; target_shortfall_pct_pt: number; knock_in_pct: number; target_met: boolean };
    investor_outcome: { ensemble_autocall_rate_pct: number; ensemble_loss_rate_pct: number; tail_return_pct: number };
    desk_outcome: { selected_hedge: string; pnl_risk_reduction_pct: number; hedge_cost: number; selection_rule: string };
    ccr_outcome: { xva_total: number; ead: number; economic_capital: number; raroc_pct: number; decision: Decision };
    recommendation: string; restructuring_actions: string[]; decision_reasons: string[]; disclosure: string; contract_id: string;
  };
}

export async function getOutcomes(): Promise<OutcomeResult> {
  const r = await apiFetch("/api/outcomes");
  return r.json();
}

export async function solveStructure(body: {
  target_coupon: number;
  max_downside: number;
  maturity: number;
  obs_per_year: number;
  fee?: number;
  objective?: string;
  prefer_basket?: boolean;
  product?: string | null;
}): Promise<StructureResult> {
  const r = await apiFetch("/api/structure", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

export interface AnalyticsResult {
  health: {
    overall_score: number;
    surface_stability: number;
    smile_regime: string;
    barrier_proximity: string;
  };
  history: {
    ytd_error: number;
    volatility: number;
    chart: { date: string; unexplained: number; cumulative: number }[];
    attribution: { driver: string; pct: number }[];
  };
  netting: {
    delta_pct: number;
    gamma_pct: number;
    vega_pct: number;
  };
}

export async function getAnalytics(): Promise<AnalyticsResult> {
  const r = await apiFetch("/api/analytics");
  return r.json();
}

/* ---- live desk: hedge recommendations, paper execution, alerts (Phase 5) ---- */

export interface HedgeInstrumentIn {
  instrument_id: number;
  segment?: number;
  symbol?: string;
  bid?: number | null;
  ask?: number | null;
  ltp?: number | null;
  quote_timestamp: string;
  lot_size?: number;
  delta?: number;
  vega?: number;
  // option terms — send all three and the server prices the leg's greeks off the desk model
  strike?: number;
  expiry?: string;
  option_type?: "CE" | "PE";
}

export interface HedgeRec {
  recommendation_id: string;
  created_at: string;
  objective: string;
  current_greeks: Record<string, number>;
  expected_greeks: Record<string, number>;
  orders: { instrument_id: number; segment: number; symbol: string; side: "BUY" | "SELL"; qty: number }[];
  estimated_cost: number;
  approval_state: string;
  execution_state?: string;
  reason_codes: string[];
}

export interface Blotter {
  orders: { order_id: string; instrument_id: number; symbol: string; side: string; qty: number; status: string; filled_qty: number }[];
  fills: { order_id: string; instrument_id: number; side: string; qty: number; price: number; fees: number; timestamp: string }[];
  positions: Record<string, { segment: number; instrument_id: number; symbol: string; qty: number; avg_price: number; realized_pnl: number; fees_paid: number }>;
}

export interface DeskAlert {
  id: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  category: string;
  message: string;
  metric: string;
  value: number;
  threshold: number;
  trade_id: string | null;
  status: "OPEN" | "ACKNOWLEDGED" | "RESOLVED";
  timestamp: string | null;
}

export async function recommendHedge(body: {
  future: HedgeInstrumentIn;
  option?: HedgeInstrumentIn;
  book_delta?: number;
  book_vega?: number;
  max_notional?: number;
}): Promise<HedgeRec> {
  const r = await apiFetch("/api/hedges/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

export async function executeRecommendation(recommendation_id: string): Promise<{ orders: { order_id: string; status: string; filled_qty: number }[] }> {
  const r = await apiFetch("/api/execution/execute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ recommendation_id }),
  });
  return r.json();
}

export interface LiveQuote {
  segment: number;
  instrument_id: number;
  symbol: string;
  description: string;
  expiry: string;
  lot_size: number;
  ltp: number | null;
  bid: number | null;
  ask: number | null;
  bid_qty: number | null;
  ask_qty: number | null;
  timestamp: string | null;
  age_s: number | null;
  stale: boolean;
}

export async function getLiveQuote(symbol = "NIFTY"): Promise<LiveQuote> {
  const r = await apiFetch(`/api/live/quote?symbol=${encodeURIComponent(symbol)}`);
  return r.json();
}

export async function getBlotter(): Promise<Blotter> {
  const r = await apiFetch("/api/execution/blotter");
  return r.json();
}

export async function getAlerts(): Promise<{ open: DeskAlert[]; history: DeskAlert[] }> {
  const r = await apiFetch("/api/alerts");
  return r.json();
}

export async function ackAlert(id: string): Promise<void> {
  await apiFetch(`/api/alerts/${encodeURIComponent(id)}/ack`, { method: "POST" });
}

/* ---- payoff explorer, option chain, broker state, attribution ---- */

export interface ExplorerResult {
  pv: number;
  notional: number;
  payoff: { terminal_level: number; payment_pct: number; ki_breached: boolean }[];
  outcomes: {
    n_paths: number;
    prob_autocall_pct: number;
    prob_loss_pct: number;
    mean_return_pa_pct: number;
    median_return_pct: number;
    p5_return_pct: number;
    p95_return_pct: number;
    median_life_years: number;
    autocall_by_period: { time: number; prob_pct: number }[];
  };
  coupon_schedule: { time: number; amount_pct: number }[];
  summary: string[];
  disclaimer: string;
}

export async function explore(req: PriceRequest): Promise<ExplorerResult> {
  const r = await fetch("/api/explorer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw new Error("explorer failed");
  return r.json();
}

export interface ChainRow {
  expiry: string;
  strike: number;
  type: "CE" | "PE";
  price: number;
  moneyness: number;
  iv: number | null;
}

export interface DeskHistoryRow {
  t: string; spot: number; atm_vol: number; nav: number;
  delta: number; gamma: number; vega: number; hedge_pnl: number;
}

export async function getDeskHistory(): Promise<{ rows: DeskHistoryRow[] }> {
  const r = await fetch("/api/desk/history");
  if (!r.ok) throw new Error("desk history fetch failed");
  return r.json();
}

export interface ResidualResult {
  n_notes: number; n_paths: number; dS: number; dvol: number;
  predicted: number; actual: number; residual: number;
  terms: Record<string, number>; note: string;
}

export async function getResidual(spotMult: number, dvol: number): Promise<ResidualResult> {
  const r = await fetch(`/api/desk/residual?spot_mult=${spotMult}&dvol=${dvol}`);
  if (!r.ok) throw new Error((await r.json()).detail ?? "residual check failed");
  return r.json();
}

export interface AutohedgeStatus {
  enabled: boolean;
  delta_threshold: number;
  interval_s: number;
  last_proposal: { recommendation_id: string; book_delta: number; created_at: string;
    orders: { symbol: string; side: string; qty: number }[] } | null;
  last_error: string | null;
}

export async function getAutohedge(): Promise<AutohedgeStatus> {
  const r = await fetch("/api/autohedge");
  if (!r.ok) throw new Error("autohedge status fetch failed");
  return r.json();
}

export async function setAutohedge(enabled: boolean, deltaThreshold?: number): Promise<AutohedgeStatus> {
  const r = await apiFetch("/api/autohedge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled, ...(deltaThreshold ? { delta_threshold: deltaThreshold } : {}) }),
  });
  return r.json();
}

export async function getRecommendations(): Promise<HedgeRec[]> {
  const r = await fetch("/api/hedges/recommendations");
  if (!r.ok) throw new Error("recommendations fetch failed");
  return r.json();
}

export interface VolTrackerData {
  n_samples: number;
  window_minutes: number;
  realized_vol: number | null;
  realized_vol_30m: number | null;
  implied_atm_vol: number | null;
  spread: number | null;
  gamma_carry_per_day?: number | null;
  series: { t: string; spot: number; iv: number | null; rv: number | null }[];
}

export async function getVolTracker(): Promise<VolTrackerData> {
  const r = await fetch("/api/live/vol-tracker");
  if (!r.ok) throw new Error("vol tracker unavailable"); // 409 off the XTS feed
  return r.json();
}

export interface RadarRow {
  trade_id: string;
  product_type: string;
  direction: string;
  years_left: number;
  ki_level?: number;
  ki_distance_pct?: number;
  ki_sigma_distance?: number;
  ki_hit_prob_pct?: number;
  autocall_level?: number;
  next_obs_days?: number;
  autocall_prob_pct?: number;
  severity: "CRITICAL" | "WARNING" | "INFO";
}

export async function getRadar(spot?: number): Promise<{ as_of: string; spot: number; rows: RadarRow[] }> {
  const r = await fetch(`/api/desk/radar${spot && spot > 0 ? `?spot=${spot}` : ""}`);
  if (!r.ok) throw new Error("radar fetch failed");
  return r.json();
}

export async function getOptionChain(): Promise<{
  as_of: string; data_source: string; underlying: string; spot: number; rows: ChainRow[];
}> {
  const r = await fetch("/api/live/option-chain");
  if (!r.ok) throw new Error("option chain fetch failed");
  return r.json();
}

export interface BrokerState {
  connected: boolean;
  reason?: string;
  orders?: Record<string, any>[];
  trades?: Record<string, any>[];
  positions?: { symbol: string; exchange_instrument_id: number; qty: number }[];
  margins?: { cash_available: number; margin_utilized: number; net_margin_available: number };
  reconciliation?: { instrument_id: number; symbol: string; paper_qty: number; broker_qty: number; difference: number }[];
}

export async function getBrokerState(): Promise<BrokerState> {
  const r = await fetch("/api/broker/state");
  if (!r.ok) throw new Error("broker state fetch failed");
  return r.json();
}

export interface AttributionRow {
  segment: number; instrument_id: number; symbol: string; qty: number; avg_price: number;
  realized_pnl: number; unrealized_pnl: number | null; fees: number; spread_cost: number;
  net_pnl: number | null;
}

export async function getAttribution(marks: Record<string, number>): Promise<{
  rows: AttributionRow[];
  totals: { realized_pnl: number; fees: number; spread_cost: number; net_pnl: number | null; unmarked_positions: number };
}> {
  const r = await fetch("/api/execution/attribution", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ marks }),
  });
  if (!r.ok) throw new Error("attribution failed");
  return r.json();
}
