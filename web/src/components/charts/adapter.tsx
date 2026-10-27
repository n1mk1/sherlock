// The Bklit adapter (UI/UX brief §4.4): a chat chart block's view and result (TRD §6.3 ChartSpec) → a
// Bklit chart, a KPI tile or a table. Series use --chart-1; the result's highlighted point gets
// --chart-accent.
import { useState } from "react";
import type { ChartData, ChartSpec } from "@/api/types";
import { formatCell, isPctColumn } from "@/lib/format";
import { AreaChart, Area } from "./area-chart";
import { Bar } from "./bar";
import { BarChart } from "./bar-chart";
import { BarXAxis } from "./bar-x-axis";
import { BoxPlot, Heatmap, Histogram, Scatter } from "./custom";
import { Grid } from "./grid";
import { LineChart, Line } from "./line-chart";
import { PieChart } from "./pie-chart";
import { PieSlice } from "./pie-slice";
import { ChartTooltip } from "./tooltip";
import { XAxis } from "./x-axis";
import { ResultTable } from "./ResultTable";

export { ResultTable };

export interface ChartProps {
  spec: ChartSpec;
  data: ChartData;
  compact?: boolean;
}

const ACCENT = "var(--chart-accent)";
const SERIES = "var(--chart-1)";

function axes(spec: ChartSpec, data: ChartData) {
  const names = data.columns.map((c) => c.name);
  const opt = spec.view.options as { x?: string; y?: string; value?: string };
  const x = opt.x && names.includes(opt.x) ? opt.x : names[0];
  const numeric = data.columns.findIndex((_, i) => i > 0 && data.rows.some((r) => typeof r[i] === "number"));
  const y = opt.y && names.includes(opt.y) ? opt.y : names[numeric > 0 ? numeric : 1];
  return { x, y, xi: names.indexOf(x), yi: names.indexOf(y) };
}

export function ChartView({ spec, data, compact }: ChartProps) {
  const view = spec.view.type;
  if (data.rows.length === 0) {
    return <p className="flex h-full items-center justify-center text-[13px] text-muted-foreground">No rows match</p>;
  }
  if (view === "kpi") return <Kpi spec={spec} data={data} />;
  if (view === "table" || data.columns.length < 2) return <ResultTable data={data} highlight={data.highlight} compact={compact} />;
  const { x, y, xi, yi } = axes(spec, data);
  const pct = isPctColumn(y, data.rows.map((r) => r[yi]));
  const rows = data.rows.map((r) => ({ [x]: r[xi] == null ? "(empty)" : String(r[xi]), [y]: r[yi] as number }));
  const point = data.highlight?.key ?? null;
  const fmt = (v: unknown) => formatCell(v, pct);

  if (view === "line" || view === "area") {
    const dated = data.rows
      .map((r) => ({ date: new Date(String(r[xi])), [y]: r[yi] as number }))
      .filter((d) => !Number.isNaN(d.date.getTime()));
    if (dated.length < 2) return <ResultTable data={data} compact={compact} />;
    const tooltip = <ChartTooltip rows={(p) => [{ color: SERIES, label: y, value: fmt(p[y]) }]} />;
    return view === "line" ? (
      <LineChart data={dated} aspectRatio="auto" className="h-full" margin={{ top: 12, right: 16, bottom: 28, left: 16 }}>
        <Grid horizontal />
        <Line dataKey={y} stroke={SERIES} />
        <XAxis />
        {tooltip}
      </LineChart>
    ) : (
      <AreaChart data={dated} aspectRatio="auto" className="h-full" margin={{ top: 12, right: 16, bottom: 28, left: 16 }}>
        <Grid horizontal />
        <Area dataKey={y} stroke={SERIES} fill={SERIES} />
        <XAxis />
        {tooltip}
      </AreaChart>
    );
  }

  const opt = spec.view.options as { series?: string };
  if (view === "histogram") return <Histogram data={data} x={x} y={y} point={point} />;
  if (view === "heatmap") return <Heatmap data={data} x={x} y={y} series={opt.series ?? data.columns[1]?.name} />;
  if (view === "box") return <BoxPlot data={data} x={x} y={y} point={point} />;
  if (view === "scatter") return <Scatter data={data} x={x} y={y} />;
  if (view === "gauge") return <Kpi spec={spec} data={data} />; // gauges render as a KPI tile in P0 (D6.5)

  if (view === "pie" || view === "ring") {
    return <Pie rows={rows} x={x} y={y} donut={view === "ring"} point={point} fmt={fmt} />;
  }

  return <Bars rows={rows} x={x} y={y} point={point} fmt={fmt} />;
}

type Row = Record<string, unknown>;

function Bars({ rows, x, y, point, fmt }: {
  rows: Row[]; x: string; y: string; point: string | null; fmt: (v: unknown) => string;
}) {
  return (
    <div className="h-full w-full">
      <BarChart data={rows} xDataKey={x} aspectRatio="auto" className="h-full" margin={{ top: 12, right: 12, bottom: 28, left: 12 }}>
        <Grid horizontal />
        <Bar
          dataKey={y}
          fill={SERIES}
          lineCap={4}
          getFill={(d) => (point !== null && String(d[x]) === point ? ACCENT : undefined)}
        />
        <BarXAxis />
        <ChartTooltip rows={(p) => [{ color: SERIES, label: y, value: fmt(p[y]) }]} />
      </BarChart>
    </div>
  );
}

function Pie({ rows, x, y, donut, point, fmt }: {
  rows: Row[]; x: string; y: string; donut: boolean; point: string | null; fmt: (v: unknown) => string;
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const shades = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];
  const slices = rows.map((r, i) => ({
    label: String(r[x]),
    value: Math.max(0, Number(r[y]) || 0),
    color: point !== null && String(r[x]) === point ? ACCENT : shades[i % shades.length],
  }));
  const shown = hovered !== null ? rows[hovered] : null;
  return (
    <div className="flex h-full w-full items-center gap-4">
      <div className="relative h-full min-h-0 flex-1">
        {/* Square on the box's height: the chart's own `w-full` square overflowed a wide, short box (a chat
            answer's pie spilled over the buttons under it). */}
        <PieChart className="mx-auto h-full w-auto max-w-full" data={slices} innerRadius={donut ? 48 : 0} padAngle={0.01}
          onHoverChange={setHovered} hoveredIndex={hovered}>
          {slices.map((_, i) => <PieSlice key={i} index={i} />)}
        </PieChart>
      </div>
      <ul className="flex max-w-[45%] flex-col gap-1 text-[12px]">
        {rows.map((r, i) => (
          <li key={i} className="flex items-center gap-2">
            <span className="size-2 shrink-0 rounded-full" style={{ background: slices[i].color }} aria-hidden />
            <span className="truncate text-muted-foreground">{String(r[x])}</span>
            <span className="ml-auto font-mono">{fmt(r[y])}</span>
          </li>
        ))}
        {shown && <li className="sr-only">{`${shown[x]}: ${fmt(shown[y])}`}</li>}
      </ul>
    </div>
  );
}

function Kpi({ spec, data }: { spec: ChartSpec; data: ChartData }) {
  const opt = spec.view.options as { value?: string; sub?: string; format?: string };
  const names = data.columns.map((c) => c.name);
  const vi = opt.value && names.includes(opt.value) ? names.indexOf(opt.value) : 0;
  const si = opt.sub && names.includes(opt.sub) ? names.indexOf(opt.sub) : -1;
  const value = data.rows[0]?.[vi];
  const pct = opt.format === "pct" || isPctColumn(names[vi], [value]);
  return (
    <div className="flex h-full flex-col justify-center gap-1">
      <span className="font-mono text-[28px] font-medium leading-none tracking-tight">{formatCell(value, pct)}</span>
      {si >= 0 && (
        <span className="text-[12px] text-muted-foreground">of {formatCell(data.rows[0]?.[si])} rows</span>
      )}
    </div>
  );
}
