export const fmt = (n: number, d = 2) =>
  n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

export const signed = (n: number, d = 2) => (n >= 0 ? "+" : "") + fmt(n, d);

export const pct = (n: number, d = 1) => fmt(n * 100, d) + "%";

export const compact = (n: number) =>
  Math.abs(n) >= 1000 ? n.toLocaleString("en-US", { maximumFractionDigits: 0 }) : fmt(n, 2);
