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
  const response = await fetch("/api/semistatic", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error("semi-static analytics failed");
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
  const r = await fetch("/api/outcomes");
  if (!r.ok) throw new Error("outcome study failed");
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
  const r = await fetch("/api/structure", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error("structure solve failed");
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
  const r = await fetch("/api/analytics");
  if (!r.ok) throw new Error("analytics fetch failed");
  return r.json();
}
