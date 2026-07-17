export const fmt = (n: number, d = 2) =>
  n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

// A value that rounds to zero is zero: never render "-0.0" or "+-0.0".
export const signed = (n: number, d = 2) => {
  const r = Number(n.toFixed(d)) + 0; // +0 normalizes -0
  return (r >= 0 ? "+" : "") + fmt(r, d);
};

// Quote/data age: seconds under 2min, minutes under 2h, hours beyond.
export const fmtAge = (s: number) =>
  s < 120 ? `${Math.round(s)}s` : s < 7200 ? `${Math.round(s / 60)}m` : `${(s / 3600).toFixed(1)}h`;

export const pct = (n: number, d = 1) => fmt(n * 100, d) + "%";

// Indian-market compact: crores/lakhs above 1e7/1e5, plain commas below (spot stays 24,229).
export const compact = (n: number) => {
  const a = Math.abs(n);
  if (a >= 1e7) return `${fmt(n / 1e7, 2)} cr`;
  if (a >= 1e5) return `${fmt(n / 1e5, 2)} L`;
  return a >= 1000 ? n.toLocaleString("en-US", { maximumFractionDigits: 0 }) : fmt(n, 2);
};

export const signedCompact = (n: number) => (n >= 0 ? "+" : "") + compact(n);
