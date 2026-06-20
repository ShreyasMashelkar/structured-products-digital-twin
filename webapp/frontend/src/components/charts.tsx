import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";
import { C, MONO, SANS, SURFACE_SCALE } from "../lib/theme";

const Plot = createPlotlyComponent(Plotly as any);

const axis = {
  stroke: C.borderSoft,
  tick: { fill: C.muted, fontSize: 10, fontFamily: MONO },
  tickLine: false,
  axisLine: { stroke: C.borderSoft },
};

function Tip({ active, payload, label, unit }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div
      className="tnum rounded-lg border px-2.5 py-1.5 text-[11px] shadow-xl"
      style={{ background: C.panel2, borderColor: C.border, color: C.ink }}
    >
      {label !== undefined && <div className="text-muted">{label}</div>}
      {payload.map((p: any, i: number) => (
        <div key={i} style={{ color: p.color || p.fill }}>
          {p.name}: {typeof p.value === "number" ? p.value.toFixed(2) : p.value}
          {unit || ""}
        </div>
      ))}
    </div>
  );
}

export function AreaSpark({
  data,
  x,
  y,
  color = C.teal,
  height = 300,
  yDomain,
  xLabel,
  yLabel,
  logX = false,
  yTickFormat,
}: {
  data: any[];
  x: string;
  y: string;
  color?: string;
  height?: number;
  yDomain?: [number, number];
  xLabel?: string;
  yLabel?: string;
  logX?: boolean;
  yTickFormat?: (v: number) => string;
}) {
  const id = `g-${y}-${color.replace("#", "")}`;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 10, right: 16, bottom: 18, left: yLabel ? 16 : 4 }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.28} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={C.grid} strokeDasharray="2 4" vertical={false} />
        <XAxis
          dataKey={x}
          {...axis}
          scale={logX ? "log" : "auto"}
          domain={logX ? ["auto", "auto"] : undefined}
          label={xLabel ? { value: xLabel, position: "insideBottom", offset: -8, fill: C.muted, fontSize: 11 } : undefined}
        />
        <YAxis
          {...axis}
          domain={yDomain ?? ["auto", "auto"]}
          width={58}
          tickFormatter={yTickFormat}
          label={yLabel ? { value: yLabel, angle: -90, position: "left", offset: -2, fill: C.muted, fontSize: 11 } : undefined}
        />
        <Tooltip content={<Tip />} cursor={{ stroke: C.border }} />
        <Area
          type="monotone"
          dataKey={y}
          stroke={color}
          strokeWidth={2.4}
          fill={`url(#${id})`}
          dot={{ r: 2.5, fill: color, strokeWidth: 0 }}
          activeDot={{ r: 4 }}
          name={yLabel || y}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function Lines({
  data, x, series, height = 300, logX = false, xLabel, yLabel,
}: {
  data: any[];
  x: string;
  series: { key: string; name: string; color: string }[];
  height?: number;
  logX?: boolean;
  xLabel?: string;
  yLabel?: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 28, right: 18, bottom: 20, left: 8 }}>
        <CartesianGrid stroke={C.grid} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey={x} {...axis} scale={logX ? "log" : "auto"} domain={logX ? ["auto", "auto"] : undefined}
          label={xLabel ? { value: xLabel, position: "insideBottom", offset: -10, fill: C.muted, fontSize: 11 } : undefined} />
        <YAxis {...axis} width={44}
          label={yLabel ? { value: yLabel, angle: -90, position: "left", offset: -2, fill: C.muted, fontSize: 11 } : undefined} />
        <Tooltip content={<Tip />} cursor={{ stroke: C.border }} />
        <Legend verticalAlign="top" align="right" height={22} wrapperStyle={{ fontSize: 11, color: C.muted }} />
        {series.map((s) => (
          <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={s.color}
            strokeWidth={2.2} dot={{ r: 2, fill: s.color, strokeWidth: 0 }} activeDot={{ r: 4 }} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function Bars({
  data,
  x,
  y,
  color = C.accent,
  height = 300,
  horizontal = false,
  colorBySign = false,
  xLabel,
  yLabel,
}: {
  data: any[];
  x: string;
  y: string;
  color?: string;
  height?: number;
  horizontal?: boolean;
  colorBySign?: boolean;
  xLabel?: string;
  yLabel?: string;
}) {
  const cells = data.map((d, i) => (
    <Cell key={i} fill={colorBySign ? (d[y] >= 0 ? C.up : C.down) : color} radius={3 as any} />
  ));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data}
        layout={horizontal ? "vertical" : "horizontal"}
        margin={{ top: 8, right: 18, bottom: 18, left: 6 }}
      >
        <CartesianGrid stroke={C.grid} strokeDasharray="2 4" vertical={horizontal} horizontal={!horizontal} />
        {horizontal ? (
          <>
            <XAxis type="number" {...axis} />
            <YAxis
              type="category"
              dataKey={x}
              {...axis}
              width={104}
              tickFormatter={(v) => String(v).replace(/_/g, " ")}
            />
          </>
        ) : (
          <>
            <XAxis dataKey={x} {...axis} />
            <YAxis {...axis} width={48} />
          </>
        )}
        <Tooltip content={<Tip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
        <Bar dataKey={y} radius={[3, 3, 0, 0]} maxBarSize={46} name={yLabel || y}>
          {cells}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Waterfall({
  data,
  height = 360,
}: {
  data: { name: string; value: number; total?: boolean }[];
  height?: number;
}) {
  let cum = 0;
  const rows = data.map((d) => {
    if (d.total) return { name: d.name, base: 0, bar: d.value, kind: "total" };
    const base = d.value >= 0 ? cum : cum + d.value;
    const row = { name: d.name, base, bar: Math.abs(d.value), kind: d.value >= 0 ? "up" : "down" };
    cum += d.value;
    return row;
  });
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={{ top: 8, right: 16, bottom: 30, left: 6 }}>
        <CartesianGrid stroke={C.grid} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="name" {...axis} angle={-25} textAnchor="end" height={50} interval={0} />
        <YAxis {...axis} width={52} />
        <Tooltip content={<Tip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
        <Bar dataKey="base" stackId="a" fill="transparent" />
        <Bar dataKey="bar" stackId="a" radius={[3, 3, 0, 0]} maxBarSize={42}>
          {rows.map((r, i) => (
            <Cell key={i} fill={r.kind === "total" ? C.accent : r.kind === "up" ? C.up : C.down} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Histogram({
  values,
  bins = 32,
  color = C.teal,
  marker,
  height = 300,
  xLabel,
}: {
  values: number[];
  bins?: number;
  color?: string;
  marker?: number;
  height?: number;
  xLabel?: string;
}) {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const w = (hi - lo) / bins || 1;
  const buckets = Array.from({ length: bins }, (_, i) => ({
    x: +(lo + (i + 0.5) * w).toFixed(3),
    count: 0,
  }));
  values.forEach((v) => {
    const idx = Math.min(bins - 1, Math.max(0, Math.floor((v - lo) / w)));
    buckets[idx].count++;
  });
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={buckets} margin={{ top: 8, right: 16, bottom: 18, left: 6 }} barGap={0} barCategoryGap={1}>
        <CartesianGrid stroke={C.grid} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="x" {...axis} />
        <YAxis {...axis} width={40} />
        <Tooltip content={<Tip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
        <Bar dataKey="count" fill={color} radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Surface3D({
  z,
  x,
  y,
  height = 460,
  zShift = 0,
}: {
  z: number[][];
  x: number[];
  y: number[];
  height?: number;
  zShift?: number; // parallel vol shift (in IV %) — the live ATM move, applied to the whole surface
}) {
  const zz = zShift ? z.map((row) => row.map((v) => v + zShift)) : z;
  return (
    <Plot
      data={[
        {
          type: "surface",
          z: zz,
          x,
          y,
          colorscale: SURFACE_SCALE,
          showscale: true,
          colorbar: {
            title: { text: "IV %", font: { color: C.muted, size: 11 } },
            thickness: 12,
            len: 0.65,
            outlinewidth: 0,
            tickfont: { family: MONO, size: 9, color: C.muted },
          },
          contours: {
            z: { show: true, usecolormap: true, highlightcolor: C.ink, width: 1, project: { z: true } },
          },
          lighting: { ambient: 0.78, diffuse: 0.6, specular: 0.12, roughness: 0.92 },
          hovertemplate: "k %{x:.2f} · T %{y:.2f}y · IV %{z:.1f}%<extra></extra>",
        } as any,
      ]}
      layout={
        {
          autosize: true,
          height,
          paper_bgcolor: "rgba(0,0,0,0)",
          font: { family: SANS, color: C.muted },
          margin: { l: 0, r: 0, t: 8, b: 0 },
          scene: {
            xaxis: pane("log-moneyness"),
            yaxis: pane("tenor (y)"),
            zaxis: pane("implied vol %"),
            camera: { eye: { x: 1.55, y: -1.65, z: 0.85 } },
            aspectratio: { x: 1.1, y: 1.0, z: 0.62 },
          },
        } as any
      }
      config={{ displayModeBar: false, responsive: true } as any}
      style={{ width: "100%" }}
      useResizeHandler
    />
  );
}

function pane(title: string) {
  return {
    title: { text: title, font: { family: SANS, size: 11, color: C.muted } },
    backgroundcolor: "rgba(0,0,0,0)",
    gridcolor: C.grid,
    zerolinecolor: C.border,
    showbackground: true,
    color: C.muted,
    tickfont: { family: MONO, size: 9, color: C.muted },
  };
}
