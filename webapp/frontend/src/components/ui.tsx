import { ReactNode, useEffect, useRef, useState } from "react";
import { cn } from "../lib/cn";

export function Panel({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-panel/70 backdrop-blur-sm shadow-[0_1px_0_0_rgba(255,255,255,0.02)_inset,0_8px_24px_-12px_rgba(0,0,0,0.6)]",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <div className="mb-3 flex items-center gap-2 text-small font-bold uppercase tracking-[0.13em] text-ink">
      <span className="h-[2px] w-3.5 rounded bg-accent" />
      {children}
    </div>
  );
}

type Tone = "" | "pos" | "neg" | "accent";
const barTone: Record<Tone, string> = {
  "": "bg-muted/50",
  pos: "bg-up",
  neg: "bg-down",
  accent: "bg-accent",
};
const valTone: Record<Tone, string> = {
  "": "text-ink",
  pos: "text-up",
  neg: "text-down",
  accent: "text-accent",
};

export function Kpi({
  label,
  value,
  sub,
  tone = "",
  flashKey,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: Tone;
  flashKey?: number; // when this number changes, the tile flashes up/down (live re-mark)
}) {
  const prev = useRef(flashKey);
  const [flash, setFlash] = useState("");
  useEffect(() => {
    if (flashKey === undefined || prev.current === undefined) {
      prev.current = flashKey;
      return;
    }
    if (flashKey !== prev.current) {
      setFlash(flashKey > prev.current ? "flash-up" : "flash-down");
      const t = setTimeout(() => setFlash(""), 600);
      prev.current = flashKey;
      return () => clearTimeout(t);
    }
  }, [flashKey]);
  return (
    <div className="group relative h-full overflow-hidden rounded-xl border border-border bg-gradient-to-br from-panel to-panel2 px-4 py-3 transition-all hover:-translate-y-0.5 hover:border-accent/60">
      {flash && <span className={cn("pointer-events-none absolute inset-0", flash)} />}
      <span className={cn("absolute left-0 top-0 bottom-0 w-[3px]", barTone[tone])} />
      <div className="relative text-label font-semibold uppercase tracking-[0.12em] text-muted">
        {label}
      </div>
      <div className={cn("tnum relative mt-1.5 text-display font-semibold leading-none", valTone[tone])}>
        {value}
      </div>
      {sub && <div className="relative mt-1.5 text-small text-muted">{sub}</div>}
    </div>
  );
}

export function Chip({
  children,
  hot = false,
}: {
  children: ReactNode;
  hot?: boolean;
}) {
  return (
    <span
      className={cn(
        "mr-1.5 inline-block rounded-full border px-2.5 py-0.5 text-small font-medium",
        hot
          ? "border-accent/60 bg-accent/10 text-accent"
          : "border-border bg-panel2 text-muted",
      )}
    >
      {children}
    </span>
  );
}

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: string[];
  active: string;
  onChange: (t: string) => void;
}) {
  return (
    <div className="flex gap-1 border-b border-border">
      {tabs.map((t) => (
        <button
          key={t}
          onClick={() => onChange(t)}
          className={cn(
            "ring-desk rounded-t-lg px-4 py-2.5 text-body font-semibold tracking-[0.04em] transition-colors",
            active === t
              ? "border-b-2 border-accent text-accent"
              : "text-muted hover:bg-white/[0.02] hover:text-ink",
          )}
        >
          {t}
        </button>
      ))}
    </div>
  );
}

export interface Col<T> {
  key: keyof T | string;
  label: string;
  align?: "left" | "right";
  fmt?: (row: T) => ReactNode;
  className?: (row: T) => string;
}

export function DataTable<T extends Record<string, any>>({
  cols,
  rows,
  max = 480,
}: {
  cols: Col<T>[];
  rows: T[];
  max?: number;
}) {
  return (
    <div className="overflow-auto rounded-xl border border-border" style={{ maxHeight: max }}>
      <table className="w-full border-collapse text-body">
        <thead className="sticky top-0 z-10 bg-panel2">
          <tr>
            {cols.map((c) => (
              <th
                key={String(c.key)}
                className={cn(
                  "border-b border-border px-3 py-2.5 text-micro font-bold uppercase tracking-[0.06em] text-muted",
                  c.align === "right" ? "text-right" : "text-left",
                )}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="transition-colors hover:bg-white/[0.025]">
              {cols.map((c) => (
                <td
                  key={String(c.key)}
                  className={cn(
                    "tnum border-b border-border-soft px-3 py-2 text-ink/90",
                    c.align === "right" ? "text-right" : "text-left",
                    c.className?.(row),
                  )}
                >
                  {c.fmt ? c.fmt(row) : String(row[c.key as keyof T])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
