// Custom visx charts (UI/UX brief §4.4, Implementation Plan D6.5): histogram, heatmap, box plot and
// scatter, drawn with the same tokens as the Bklit charts: series in --chart-1, the point in
// --chart-accent, labels in --chart-label, grid in --chart-grid. The heatmap is a single-hue grey ramp
// with the accent on the largest cell. Each has a hover readout and an accessible summary.
import { ParentSize } from "@visx/responsive";
import { scaleBand, scaleLinear } from "@visx/scale";
import { useState } from "react";
import type { ChartData } from "@/api/types";
import { formatCell, isPctColumn } from "@/lib/format";

const SERIES = "var(--chart-1)";
const ACCENT = "var(--chart-accent)";
const GRID = "var(--chart-grid)";
const LABEL = "var(--chart-label)";
const M = { top: 10, right: 12, bottom: 26, left: 44 };

type Props = { data: ChartData; x: string; y: string; series?: string; point?: string | null };

const col = (d: ChartData, name: string) => d.columns.findIndex((c) => c.name === name);
const num = (v: unknown) => (typeof v === "number" ? v : Number(v));

function Frame({ label, children }: { label: string; children: (w: number, h: number) => React.ReactNode }) {
  return (
    <div className="relative h-full w-full" role="img" aria-label={label}>
      <ParentSize debounceTime={30}>{({ width, height }) => (width > 0 && height > 0 ? children(width, height) : null)}</ParentSize>
    </div>
  );
}

function YTicks({ scale, width, fmt }: { scale: ReturnType<typeof scaleLinear<number>>; width: number; fmt: (v: number) => string }) {
  return (
    <g>
      {scale.ticks(4).map((t) => (
        <g key={t} transform={`translate(0,${scale(t)})`}>
          <line x1={M.left} x2={width - M.right} stroke={GRID} />
          <text x={M.left - 6} dy="0.32em" textAnchor="end" fontSize={11} fill={LABEL}>{fmt(t)}</text>
        </g>
      ))}
    </g>
  );
}

function Readout({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <div className="pointer-events-none absolute right-2 top-1 rounded-md border border-border bg-popover px-2 py-1 font-mono text-[12px] shadow-[var(--shadow-overlay)]">
      {text}
    </div>
  );
}

export function Histogram({ data, x, y, point }: Props) {
  const xi = col(data, x), yi = col(data, y);
  const bins = data.rows.map((r) => ({ start: num(r[xi]), n: num(r[yi]) })).filter((b) => Number.isFinite(b.start));
  const step = bins.length > 1 ? Math.min(...bins.slice(1).map((b, i) => b.start - bins[i].start).filter((d) => d > 0)) : 1;
  const [hover, setHover] = useState<number | null>(null);
  const peak = bins.reduce((best, b, i) => (b.n > bins[best].n ? i : best), 0);
  return (
    <Frame label={`Histogram of ${x}: ${bins.length} bins, the most common from ${formatCell(bins[peak]?.start)}`}>
      {(w, h) => {
        const lo = Math.min(...bins.map((b) => b.start)), hi = Math.max(...bins.map((b) => b.start)) + (Number.isFinite(step) ? step : 1);
        const xs = scaleLinear<number>({ domain: [lo, hi], range: [M.left, w - M.right] });
        const ys = scaleLinear<number>({ domain: [0, Math.max(1, ...bins.map((b) => b.n))], range: [h - M.bottom, M.top], nice: true });
        const bw = Math.max(1, xs(lo + (Number.isFinite(step) ? step : 1)) - xs(lo) - 1);
        return (
          <>
            <svg width={w} height={h}>
              <YTicks scale={ys} width={w} fmt={(v) => formatCell(v)} />
              {bins.map((b, i) => (
                <rect key={i} x={xs(b.start)} y={ys(b.n)} width={bw} height={h - M.bottom - ys(b.n)} rx={2}
                  fill={(point != null && String(b.start) === point) || (point == null && i === peak) ? ACCENT : SERIES}
                  opacity={hover === null || hover === i ? 1 : 0.6}
                  onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
              ))}
              {xs.ticks(5).map((t) => (
                <text key={t} x={xs(t)} y={h - 8} textAnchor="middle" fontSize={11} fill={LABEL}>{formatCell(t)}</text>
              ))}
            </svg>
            <Readout text={hover !== null ? `${formatCell(bins[hover].start)} – ${formatCell(bins[hover].start + step)}: ${formatCell(bins[hover].n)}` : null} />
          </>
        );
      }}
    </Frame>
  );
}

export function Heatmap({ data, x, y, series }: Props) {
  const xi = col(data, x), yi = col(data, y), si = series ? col(data, series) : 1;
  const cells = data.rows.map((r) => ({ a: String(r[xi]), b: String(r[si]), v: num(r[yi]) })).filter((c) => Number.isFinite(c.v));
  const xsKeys = [...new Set(cells.map((c) => c.a))];
  const ysKeys = [...new Set(cells.map((c) => c.b))];
  const max = Math.max(...cells.map((c) => c.v)), min = Math.min(...cells.map((c) => c.v));
  const pct = isPctColumn(y, cells.map((c) => c.v));
  const [hover, setHover] = useState<number | null>(null);
  const top = cells.reduce((best, c, i) => (c.v > cells[best].v ? i : best), 0);
  return (
    <Frame label={`Heatmap of ${y} by ${x} and ${series}: highest at ${cells[top]?.a}, ${cells[top]?.b}`}>
      {(w, h) => {
        const left = 56;
        const xb = scaleBand<string>({ domain: xsKeys, range: [left, w - M.right], padding: 0.06 });
        const yb = scaleBand<string>({ domain: ysKeys, range: [M.top, h - M.bottom], padding: 0.06 });
        const shade = (v: number) => `color-mix(in srgb, var(--chart-1) ${Math.round(15 + 70 * ((v - min) / ((max - min) || 1)))}%, var(--card))`;
        return (
          <>
            <svg width={w} height={h}>
              {cells.map((c, i) => (
                <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                  <rect x={xb(c.a)} y={yb(c.b)} width={xb.bandwidth()} height={yb.bandwidth()} rx={3}
                    fill={i === top ? ACCENT : shade(c.v)} stroke={hover === i ? "var(--foreground)" : "none"} />
                  {xb.bandwidth() > 44 && yb.bandwidth() > 18 && (
                    <text x={(xb(c.a) ?? 0) + xb.bandwidth() / 2} y={(yb(c.b) ?? 0) + yb.bandwidth() / 2} dy="0.32em"
                      textAnchor="middle" fontSize={11} fontFamily="var(--font-mono)"
                      fill={(c.v - min) / ((max - min) || 1) > 0.55 || i === top ? "var(--card)" : "var(--foreground)"}>
                      {formatCell(c.v, pct)}
                    </text>
                  )}
                </g>
              ))}
              {xsKeys.map((k) => <text key={k} x={(xb(k) ?? 0) + xb.bandwidth() / 2} y={h - 8} textAnchor="middle" fontSize={11} fill={LABEL}>{k}</text>)}
              {ysKeys.map((k) => <text key={k} x={left - 6} y={(yb(k) ?? 0) + yb.bandwidth() / 2} dy="0.32em" textAnchor="end" fontSize={11} fill={LABEL}>{k}</text>)}
            </svg>
            <Readout text={hover !== null ? `${cells[hover].a} · ${cells[hover].b}: ${formatCell(cells[hover].v, pct)}` : null} />
          </>
        );
      }}
    </Frame>
  );
}

export function BoxPlot({ data, x, point }: Props) {
  const i = (n: string) => col(data, n);
  const boxes = data.rows.map((r) => ({
    k: String(r[0]), min: num(r[i("min")]), q1: num(r[i("q1")]), med: num(r[i("median")]), q3: num(r[i("q3")]), max: num(r[i("max")]),
  }));
  const [hover, setHover] = useState<number | null>(null);
  return (
    <Frame label={`Box plot by ${x}: medians from ${formatCell(Math.min(...boxes.map((b) => b.med)))} to ${formatCell(Math.max(...boxes.map((b) => b.med)))}`}>
      {(w, h) => {
        const xb = scaleBand<string>({ domain: boxes.map((b) => b.k), range: [M.left, w - M.right], padding: 0.35 });
        const ys = scaleLinear<number>({ domain: [Math.min(...boxes.map((b) => b.min)), Math.max(...boxes.map((b) => b.max))], range: [h - M.bottom, M.top], nice: true });
        return (
          <>
            <svg width={w} height={h}>
              <YTicks scale={ys} width={w} fmt={(v) => formatCell(v)} />
              {boxes.map((b, j) => {
                const cx = (xb(b.k) ?? 0) + xb.bandwidth() / 2;
                const color = point != null && b.k === point ? ACCENT : SERIES;
                return (
                  <g key={b.k} onMouseEnter={() => setHover(j)} onMouseLeave={() => setHover(null)} opacity={hover === null || hover === j ? 1 : 0.6}>
                    <line x1={cx} x2={cx} y1={ys(b.min)} y2={ys(b.max)} stroke={color} />
                    <rect x={xb(b.k)} y={ys(b.q3)} width={xb.bandwidth()} height={Math.max(1, ys(b.q1) - ys(b.q3))} rx={3}
                      fill="var(--card)" stroke={color} strokeWidth={1.5} />
                    <line x1={xb(b.k)} x2={(xb(b.k) ?? 0) + xb.bandwidth()} y1={ys(b.med)} y2={ys(b.med)} stroke={color} strokeWidth={2} />
                    <text x={cx} y={h - 8} textAnchor="middle" fontSize={11} fill={LABEL}>{b.k}</text>
                  </g>
                );
              })}
            </svg>
            <Readout text={hover !== null ? `${boxes[hover].k}: median ${formatCell(boxes[hover].med)} (${formatCell(boxes[hover].q1)}–${formatCell(boxes[hover].q3)})` : null} />
          </>
        );
      }}
    </Frame>
  );
}

export function Scatter({ data, x, y }: Props) {
  const xi = col(data, x), yi = col(data, y);
  const pts = data.rows.map((r) => ({ a: num(r[xi]), b: num(r[yi]) })).filter((p) => Number.isFinite(p.a) && Number.isFinite(p.b));
  const [hover, setHover] = useState<number | null>(null);
  return (
    <Frame label={`Scatter of ${y} against ${x}, ${pts.length} points`}>
      {(w, h) => {
        const xs = scaleLinear<number>({ domain: [Math.min(...pts.map((p) => p.a)), Math.max(...pts.map((p) => p.a))], range: [M.left, w - M.right], nice: true });
        const ys = scaleLinear<number>({ domain: [Math.min(...pts.map((p) => p.b)), Math.max(...pts.map((p) => p.b))], range: [h - M.bottom, M.top], nice: true });
        return (
          <>
            <svg width={w} height={h}>
              <YTicks scale={ys} width={w} fmt={(v) => formatCell(v)} />
              {pts.map((p, i) => (
                <circle key={i} cx={xs(p.a)} cy={ys(p.b)} r={hover === i ? 4 : 2.5} fill={hover === i ? ACCENT : SERIES} opacity={0.55}
                  onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
              ))}
              {xs.ticks(5).map((t) => <text key={t} x={xs(t)} y={h - 8} textAnchor="middle" fontSize={11} fill={LABEL}>{formatCell(t)}</text>)}
            </svg>
            <Readout text={hover !== null ? `${x} ${formatCell(pts[hover].a)} · ${y} ${formatCell(pts[hover].b)}` : null} />
          </>
        );
      }}
    </Frame>
  );
}
