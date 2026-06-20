import { Desk, PriceRequest } from "./api";

export interface Trade {
  trade_id: string;
  product_type: string; // autocallable | brc | reverse_convertible | capital_protected
  label: string;
  notional: number;
  observation_times?: number[];
  maturity: number;
  params: Record<string, any>;
  staged?: boolean;
  // book-only precomputed marks
  pv?: number;
  delta?: number;
  gamma?: number;
  vega?: number;
  rho?: number;
  vanna?: number;
  volga?: number;
  day_pnl?: number;
}

const LABEL: Record<string, string> = {
  autocallable: "Autocallable",
  brc: "Barrier reverse conv.",
  reverse_convertible: "Reverse conv.",
  capital_protected: "Capital protected",
  worst_of: "Worst-of autocallable",
};

export const TYPE_ABBR: Record<string, string> = {
  autocallable: "AC",
  brc: "BRC",
  reverse_convertible: "RC",
  capital_protected: "CPN",
  worst_of: "WO",
};

export function productLabel(t: string): string {
  return LABEL[t] ?? t;
}

export function bookTrades(desk: Desk): Trade[] {
  return desk.positions.map((p) => ({
    trade_id: p.trade_id,
    product_type: p.product_type ?? "autocallable",
    label: productLabel(p.product_type ?? "autocallable"),
    notional: p.notional,
    observation_times: p.observation_times ?? undefined,
    maturity: p.maturity,
    params: p.params ?? {},
    pv: p.pv,
    delta: p.delta,
    gamma: p.gamma,
    vega: p.vega,
    rho: p.rho,
    vanna: p.vanna,
    volga: p.volga,
    day_pnl: p.day_pnl,
  }));
}

export function priceReq(t: Trade): PriceRequest {
  return {
    product_type: t.product_type,
    notional: t.notional,
    observation_times: t.observation_times,
    maturity: t.maturity,
    params: t.params,
  };
}
