// Shared colour tokens for charts (mirrors src/index.css @theme).
export const C = {
  bg: "#090b10",
  panel: "#12161f",
  panel2: "#171c27",
  border: "#232a37",
  borderSoft: "#1a202b",
  ink: "#eaeef5",
  muted: "#97a2b4",
  faint: "#5b6678",
  accent: "#e6b34a",
  teal: "#4fc3d7",
  violet: "#9d8df1",
  up: "#3dd68c",
  down: "#fb6a82",
  grid: "#19202c",
};

export const MONO = "'JetBrains Mono', ui-monospace, monospace";
export const SANS = "'Inter', system-ui, sans-serif";

// Dark→gold surface colourscale for the vol surface.
export const SURFACE_SCALE: [number, string][] = [
  [0.0, "#10233a"],
  [0.25, "#1e5c6e"],
  [0.5, "#34a0a4"],
  [0.75, "#c9a227"],
  [1.0, "#f2c14e"],
];
