"use client";

import * as React from "react";
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
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

export const C = {
  accent: "rgb(59 130 246)",
  cyan: "rgb(34 211 238)",
  violet: "rgb(167 139 250)",
  ok: "rgb(52 211 153)",
  warn: "rgb(251 191 36)",
  danger: "rgb(248 113 113)",
  grid: "rgb(30 41 64)",
  muted: "rgb(134 148 173)",
};
export const SERIES = [C.accent, C.violet, C.cyan, C.ok, C.warn, C.danger];

const axis = { stroke: C.muted, fontSize: 11, tickLine: false, axisLine: { stroke: C.grid } } as const;
const tooltipStyle = {
  contentStyle: { background: "rgb(11 17 30)", border: "1px solid rgb(30 41 64)", borderRadius: 8, fontSize: 12 },
  labelStyle: { color: "rgb(226 232 244)" },
  itemStyle: { color: "rgb(226 232 244)" },
};

export function ChartFrame({ height = 260, children, caption }: { height?: number; children: React.ReactElement; caption?: React.ReactNode }) {
  return (
    <figure>
      <div style={{ height }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      </div>
      {caption && <figcaption className="mt-2 text-xs leading-relaxed text-muted">{caption}</figcaption>}
    </figure>
  );
}

export function RocChart({ points, caption }: { points: { fpr: number; tpr: number }[]; caption?: React.ReactNode }) {
  const data = points.map((p) => ({ fpr: p.fpr, tpr: p.tpr }));
  return (
    <ChartFrame caption={caption}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 16, left: 0 }}>
        <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
        <XAxis dataKey="fpr" type="number" domain={[0, 1]} {...axis} label={{ value: "False-positive rate", position: "insideBottom", offset: -8, fill: C.muted, fontSize: 11 }} />
        <YAxis dataKey="tpr" type="number" domain={[0, 1]} {...axis} label={{ value: "True-positive rate", angle: -90, position: "insideLeft", fill: C.muted, fontSize: 11 }} />
        <Tooltip {...tooltipStyle} formatter={(v: number) => v.toFixed(3)} />
        <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke={C.muted} strokeDasharray="4 4" />
        <ReferenceLine x={0.01} stroke={C.warn} strokeDasharray="2 4" label={{ value: "1% FPR", fill: C.warn, fontSize: 10, position: "top" }} />
        <Line type="stepAfter" dataKey="tpr" stroke={C.accent} strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ChartFrame>
  );
}

export function PrChart({ points }: { points: { recall: number; precision: number }[] }) {
  return (
    <ChartFrame caption="Precision here reflects the evaluation sample's class balance, not a deployment population.">
      <LineChart data={points} margin={{ top: 8, right: 16, bottom: 16, left: 0 }}>
        <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
        <XAxis dataKey="recall" type="number" domain={[0, 1]} {...axis} label={{ value: "Recall", position: "insideBottom", offset: -8, fill: C.muted, fontSize: 11 }} />
        <YAxis domain={[0, 1]} {...axis} />
        <Tooltip {...tooltipStyle} formatter={(v: number) => v.toFixed(3)} />
        <Line type="stepAfter" dataKey="precision" stroke={C.violet} strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ChartFrame>
  );
}

export function PpvCurve({
  series,
  marker,
}: {
  series: { name: string; points: { prevalence: number; ppv: number | null }[] }[];
  marker?: number;
}) {
  const prevs = Array.from(new Set(series.flatMap((s) => s.points.map((p) => p.prevalence)))).sort((a, b) => a - b);
  const data = prevs.map((pv) => {
    const row: Record<string, number | null> = { prevalence: pv };
    series.forEach((s) => (row[s.name] = s.points.find((p) => p.prevalence === pv)?.ppv ?? null));
    return row;
  });
  return (
    <ChartFrame height={280}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 16, left: 0 }}>
        <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
        <XAxis dataKey="prevalence" scale="log" type="number" domain={["dataMin", "dataMax"]} {...axis} tickFormatter={(v) => `${+(v * 100).toPrecision(2)}%`} label={{ value: "Prevalence of AI content (log scale)", position: "insideBottom", offset: -8, fill: C.muted, fontSize: 11 }} />
        <YAxis domain={[0, 1]} {...axis} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
        <Tooltip {...tooltipStyle} formatter={(v: number) => `${(v * 100).toFixed(1)}%`} labelFormatter={(v) => `prevalence ${(Number(v) * 100).toPrecision(3)}%`} />
        <Legend wrapperStyle={{ fontSize: 11, color: C.muted }} />
        {marker != null && <ReferenceLine x={marker} stroke={C.warn} strokeDasharray="3 3" />}
        {series.map((s, i) => (
          <Line key={s.name} type="monotone" dataKey={s.name} stroke={SERIES[i % SERIES.length]} strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
        ))}
      </LineChart>
    </ChartFrame>
  );
}

export function SimpleLines({
  data,
  x,
  lines,
  xLabel,
  yLabel,
  logX,
  logY,
  height,
  yDomain,
}: {
  data: Record<string, any>[];
  x: string;
  lines: { key: string; name?: string; dashed?: boolean }[];
  xLabel?: string;
  yLabel?: string;
  logX?: boolean;
  logY?: boolean;
  height?: number;
  yDomain?: [number | string, number | string];
}) {
  return (
    <ChartFrame height={height}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 18, left: 4 }}>
        <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
        <XAxis dataKey={x} type="number" scale={logX ? "log" : "auto"} domain={["dataMin", "dataMax"]} {...axis} label={xLabel ? { value: xLabel, position: "insideBottom", offset: -10, fill: C.muted, fontSize: 11 } : undefined} />
        <YAxis scale={logY ? "log" : "auto"} domain={yDomain ?? (logY ? ["auto", "auto"] : [0, "auto"])} {...axis} allowDataOverflow label={yLabel ? { value: yLabel, angle: -90, position: "insideLeft", fill: C.muted, fontSize: 11 } : undefined} />
        <Tooltip {...tooltipStyle} />
        <Legend wrapperStyle={{ fontSize: 11, color: C.muted }} />
        {lines.map((l, i) => (
          <Line key={l.key} dataKey={l.key} name={l.name ?? l.key} stroke={SERIES[i % SERIES.length]} strokeDasharray={l.dashed ? "4 4" : undefined} strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} connectNulls />
        ))}
      </LineChart>
    </ChartFrame>
  );
}

export function Bars({
  data,
  x,
  bars,
  height = 240,
  colorByIndex,
  yLabel,
  horizontal,
}: {
  data: Record<string, any>[];
  x: string;
  bars: { key: string; name?: string }[];
  height?: number;
  colorByIndex?: boolean;
  yLabel?: string;
  horizontal?: boolean;
}) {
  return (
    <ChartFrame height={height}>
      <BarChart data={data} layout={horizontal ? "vertical" : "horizontal"} margin={{ top: 8, right: 16, bottom: 8, left: horizontal ? 24 : 0 }}>
        <CartesianGrid stroke={C.grid} strokeDasharray="3 3" horizontal={!horizontal} vertical={!!horizontal} />
        {horizontal ? (
          <>
            <XAxis type="number" {...axis} />
            <YAxis type="category" dataKey={x} {...axis} width={170} />
          </>
        ) : (
          <>
            <XAxis dataKey={x} {...axis} />
            <YAxis {...axis} allowDecimals={false} label={yLabel ? { value: yLabel, angle: -90, position: "insideLeft", fill: C.muted, fontSize: 11 } : undefined} />
          </>
        )}
        <Tooltip {...tooltipStyle} cursor={{ fill: "rgb(30 41 64 / 0.4)" }} />
        {bars.length > 1 && <Legend wrapperStyle={{ fontSize: 11, color: C.muted }} />}
        {bars.map((b, i) => (
          <Bar key={b.key} dataKey={b.key} name={b.name ?? b.key} fill={SERIES[i % SERIES.length]} radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} isAnimationActive={false}>
            {colorByIndex && data.map((_, j) => <Cell key={j} fill={SERIES[j % SERIES.length]} />)}
          </Bar>
        ))}
      </BarChart>
    </ChartFrame>
  );
}

export function Sparkline({ data, color = C.cyan, height = 60 }: { data: number[]; color?: string; height?: number }) {
  const rows = data.map((v, i) => ({ i, v }));
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="spark" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={color} stopOpacity={0.35} />
              <stop offset="1" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Tooltip {...tooltipStyle} formatter={(v: number) => v.toFixed(3)} labelFormatter={() => ""} />
          <Area type="monotone" dataKey="v" stroke={color} fill="url(#spark)" strokeWidth={1.5} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ReliabilityDiagram({ bins }: { bins: { mean_predicted: number | null; observed_frequency: number | null; count: number }[] }) {
  const data = bins.filter((b) => b.count && b.mean_predicted != null).map((b) => ({ x: b.mean_predicted, y: b.observed_frequency, z: b.count }));
  return (
    <ChartFrame caption="Points on the diagonal indicate calibrated probabilities for this evaluation population only.">
      <ScatterChart margin={{ top: 8, right: 16, bottom: 16, left: 0 }}>
        <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
        <XAxis dataKey="x" type="number" domain={[0, 1]} {...axis} name="mean predicted" />
        <YAxis dataKey="y" type="number" domain={[0, 1]} {...axis} name="observed" />
        <ZAxis dataKey="z" range={[30, 300]} name="n" />
        <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke={C.muted} strokeDasharray="4 4" />
        <Tooltip {...tooltipStyle} />
        <Scatter data={data} fill={C.cyan} isAnimationActive={false} />
      </ScatterChart>
    </ChartFrame>
  );
}
