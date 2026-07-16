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

export const compact = (n: number) =>
  Math.abs(n) >= 1000 ? n.toLocaleString("en-US", { maximumFractionDigits: 0 }) : fmt(n, 2);
