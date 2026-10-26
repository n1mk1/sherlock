// An analysis widget's body (App Flow §9 steps 3–5): plain-language progress while the run goes, then
// the verdict line and the importance bars; clicking a factor shows its partial-dependence mini chart.
// A failed or cancelled run says why, with Re-run.
import { Check, Loader2 } from "lucide-react";
import { useState } from "react";
import { fmtMetric, METRIC_LABELS, RUNNING, useRunActions, useRunResults, type Run } from "@/api/ml";
import type { Widget } from "@/api/types";
import { Button } from "@/components/ui/button";
import { formatCell } from "@/lib/format";
import { cn } from "@/lib/utils";

// The runner's progress labels (TRD §7.5), in order.
const STEPS = ["preparing data", "checking for leakage", "setting baselines", "testing models", "explaining", "writing the model card"];

export function MlResult({ widget, run, asTable }: { widget: Widget; run: Run | undefined; asTable?: boolean }) {
  const actions = useRunActions(widget.dataset_id);
  if (!run) return <div role="status" className="h-full w-full animate-pulse rounded-lg bg-muted" aria-label="Loading" />;
  if (RUNNING.includes(run.status)) {
    return <Progress run={run} onCancel={() => actions.cancel.mutate(run.id)} />;
  }
  if (run.status === "failed" || run.status === "cancelled") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
        <p className="max-w-[90%] text-[13px] text-muted-foreground">
          {run.status === "cancelled" ? "The analysis was cancelled." : `The analysis failed: ${run.error ?? "no reason given"}`}
        </p>
        <Button size="sm" onClick={() => actions.rerun.mutate(widget.id)} loading={actions.rerun.isPending}>Re-run</Button>
      </div>
    );
  }
  return <Views run={run} asTable={asTable} initial={widget.spec.view.type} />;
}

const VIEW_NAMES: Record<string, string> = { importance: "Importance", confusion: "Confusion", roc: "ROC" };

/** The view switcher (App Flow §9 step 4): importance, and for categories the confusion matrix and
 * the ROC curve (two classes), all from the run's out-of-fold predictions. */
function Views({ run, asTable, initial }: { run: Run; asTable?: boolean; initial: string }) {
  const views = run.summary?.views ?? ["importance"];
  const [view, setView] = useState(views.includes(initial) ? initial : "importance");
  return (
    <div className="flex h-full flex-col gap-1">
      {views.length > 1 && (
        <div role="tablist" aria-label="Result view" className="flex gap-1 pt-1">
          {views.map((v) => (
            <button
              key={v}
              type="button"
              role="tab"
              aria-selected={view === v}
              onClick={() => setView(v)}
              className={cn(
                "h-6 rounded-md px-2 text-[12px] focus-visible:outline-2 focus-visible:outline-ring",
                view === v ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {VIEW_NAMES[v] ?? v}
            </button>
          ))}
        </div>
      )}
      <div className="min-h-0 flex-1">
        {view === "confusion" ? <Confusion run={run} /> : view === "roc" ? <Roc run={run} /> : <Importance run={run} asTable={asTable} />}
      </div>
    </div>
  );
}

/** Actual × predicted counts; the diagonal (right) in the accent tint. */
export function ConfusionMatrix({ labels, matrix, target }: { labels: string[]; matrix: number[][]; target?: string | null }) {
  const max = Math.max(1, ...matrix.flat());
  return (
    <table className="w-full max-w-[360px] border-separate border-spacing-1 text-[12px]" aria-label="Confusion matrix: actual by predicted">
      <thead>
        <tr>
          <th className="text-left font-normal text-muted-foreground">{target ?? "actual"} ↓ · predicted →</th>
          {labels.map((l) => <th key={l} className="font-mono font-normal text-muted-foreground">{l}</th>)}
        </tr>
      </thead>
      <tbody>
        {labels.map((a, i) => (
          <tr key={a}>
            <th className="text-left font-mono font-normal text-muted-foreground">{a}</th>
            {labels.map((p, j) => (
              <td
                key={p}
                title={`actual ${a}, predicted ${p}: ${matrix[i][j].toLocaleString("en-US")}`}
                className="h-8 rounded text-center font-mono"
                style={{ background: `color-mix(in srgb, ${i === j ? "var(--chart-accent)" : "var(--chart-1)"} ${Math.round(12 + 50 * matrix[i][j] / max)}%, transparent)` }}
              >
                {matrix[i][j].toLocaleString("en-US")}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Confusion({ run }: { run: Run }) {
  const res = useRunResults(run, "confusion");
  if (!res.data) return <div className="h-full min-h-20 animate-pulse rounded-lg bg-muted" />;
  const rows = res.data.rows as [string, string, number][];
  const labels = [...new Set(rows.map((r) => r[0]))];
  const matrix = labels.map((a) => labels.map((p) => rows.find((r) => r[0] === a && r[1] === p)?.[2] ?? 0));
  const wrong = rows.filter((r) => r[0] !== r[1]).reduce((n, r) => n + r[2], 0);
  return (
    <div className="flex flex-col gap-1.5 pt-1">
      <ConfusionMatrix labels={labels} matrix={matrix} target={run.target} />
      <p className="text-[12px] text-muted-foreground">
        Each row predicted by a model that never saw it; <span className="font-mono">{wrong.toLocaleString("en-US")}</span> predicted wrong.
      </p>
    </div>
  );
}

/** The ROC curve (two classes): true-positive rate against false-positive rate, the diagonal is chance. */
export function RocCurve({ points, auc, positive }: { points: { fpr: number; tpr: number }[]; auc: number; positive: string }) {
  const S = 160;
  const pad = 22;
  const x = (v: number) => pad + v * (S - pad - 6);
  const y = (v: number) => S - pad - v * (S - pad - 6);
  return (
    <figure className="flex flex-col gap-1">
      <svg viewBox={`0 0 ${S} ${S}`} className="size-[170px] max-h-full shrink-0" role="img"
        aria-label={`ROC curve for ${positive}: area under the curve ${auc.toFixed(3)}`}>
        <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} stroke="var(--chart-grid)" strokeDasharray="3 3" />
        <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(0)} stroke="var(--chart-grid)" />
        <line x1={x(0)} y1={y(0)} x2={x(0)} y2={y(1)} stroke="var(--chart-grid)" />
        <polyline fill="none" stroke="var(--chart-accent)" strokeWidth={2} points={points.map((p) => `${x(p.fpr)},${y(p.tpr)}`).join(" ")} />
        <text x={x(0.5)} y={S - 6} textAnchor="middle" fontSize={9} fill="var(--chart-label)">false positives</text>
        <text x={8} y={y(0.5)} textAnchor="middle" fontSize={9} fill="var(--chart-label)" transform={`rotate(-90 8 ${y(0.5)})`}>true positives</text>
      </svg>
      <figcaption className="text-[12px] text-muted-foreground">
        Predicting {positive}: area under the curve <span className="font-mono">{auc.toFixed(3)}</span> (0.5 is chance).
      </figcaption>
    </figure>
  );
}

function Roc({ run }: { run: Run }) {
  const res = useRunResults(run, "roc");
  const card = run.model_card;
  if (!res.data) return <div className="h-full min-h-20 animate-pulse rounded-lg bg-muted" />;
  const points = (res.data.rows as [number, number, number][]).map(([fpr, tpr]) => ({ fpr, tpr }));
  return <RocCurve points={points} auc={card?.roc?.auc ?? 0} positive={card?.roc?.positive ?? ""} />;
}

function Progress({ run, onCancel }: { run: Run; onCancel: () => void }) {
  const label = run.progress?.label ?? (run.status === "queued" ? "waiting to start" : STEPS[0]);
  const at = STEPS.indexOf(label);
  return (
    <div className="flex h-full flex-col justify-center gap-3 px-1" role="status" aria-live="polite">
      <p className="text-[13px]">
        What drives <span className="font-medium">{run.target}</span>: <span className="text-muted-foreground">{label}…</span>
      </p>
      <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full bg-accent transition-[width] duration-500" style={{ width: `${Math.max(4, run.progress?.pct ?? 0)}%` }} />
      </div>
      <ol className="flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-muted-foreground">
        {STEPS.slice(0, 5).map((s, i) => (
          <li key={s} className={cn("inline-flex items-center gap-1", i === at && "text-foreground")}>
            {i < at ? <Check className="size-3" /> : i === at ? <Loader2 className="size-3 animate-spin" /> : null}
            {s}
          </li>
        ))}
      </ol>
      <div>
        <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}

function Importance({ run, asTable }: { run: Run; asTable?: boolean }) {
  const results = useRunResults(run);
  const [factor, setFactor] = useState<string | null>(null);
  const s = run.summary;
  const rows = (results.data?.rows ?? []) as [string, number][];
  const shown = rows.slice(0, 12);
  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto pt-1">
      {s && (
        <p className="text-[13px] leading-snug">
          <span className={cn("font-semibold", s.verdict === "no_signal" && "text-warning")}>{s.verdict_text}</span>{" "}
          <span className="text-muted-foreground">
            {s.chosen_label}: {METRIC_LABELS[s.metric] ?? s.metric} {fmtMetric(s.metric, s.value)} vs {fmtMetric(s.metric, s.best_baseline.value)}.
          </span>
        </p>
      )}
      {results.isLoading ? (
        <div className="min-h-20 flex-1 animate-pulse rounded-lg bg-muted" />
      ) : asTable ? (
        <table className="w-full text-[12px]">
          <thead><tr className="text-left text-muted-foreground"><th className="py-1">Factor</th><th className="py-1 text-right">Importance</th></tr></thead>
          <tbody>{rows.map(([f, v]) => <tr key={f} className="border-t border-border"><td className="py-1">{f}</td><td className="py-1 text-right font-mono">{formatCell(v)}</td></tr>)}</tbody>
        </table>
      ) : (
        <ul className="flex flex-col gap-1" aria-label={`Factors by importance: ${shown.map(([f]) => f).join(", ")}`}>
          {shown.map(([f, v]) => (
            <li key={f}>
              <button
                type="button"
                onClick={() => setFactor(factor === f ? null : f)}
                aria-expanded={factor === f}
                className="group grid w-full grid-cols-[minmax(64px,30%)_1fr_44px] items-center gap-2 rounded text-left text-[12px] hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring"
                title="Show how the prediction changes with this factor"
              >
                <span className="truncate">{f}</span>
                <span className="h-3 rounded-sm bg-muted">
                  <span
                    className="block h-full rounded-sm"
                    style={{ width: `${Math.max(1, v * 100)}%`, background: factor === f || (!factor && f === shown[0]?.[0]) ? "var(--chart-accent)" : "var(--chart-1)" }}
                  />
                </span>
                <span className="text-right font-mono text-muted-foreground">{v.toFixed(2)}</span>
              </button>
              {factor === f && <PartialDependence run={run} feature={f} />}
            </li>
          ))}
          {rows.length > shown.length && <li className="text-[12px] text-muted-foreground">and {rows.length - shown.length} more (Show as table)</li>}
        </ul>
      )}
    </div>
  );
}

/** The partial-dependence mini chart (App Flow §9 step 5): the average prediction as the factor varies. */
function PartialDependence({ run, feature }: { run: Run; feature: string }) {
  const pd = useRunResults(run, "partial_dependence", feature);
  if (pd.error) return <p className="py-1 pl-2 text-[12px] text-muted-foreground">{(pd.error as Error).message}</p>;
  if (!pd.data) return <div className="my-1 h-16 animate-pulse rounded bg-muted" />;
  const pts = pd.data.rows as [string | number, number][];
  const ys = pts.map((p) => p[1]);
  const lo = Math.min(...ys);
  const hi = Math.max(...ys);
  const W = 300;
  const H = 64;
  const y = (v: number) => (hi === lo ? H / 2 : H - 6 - ((v - lo) / (hi - lo)) * (H - 12));
  const x = (i: number) => (pts.length === 1 ? W / 2 : 8 + (i / (pts.length - 1)) * (W - 16));
  const numeric = pd.data.kind === "numeric";
  const fmt = (v: number) => (run.summary?.metric !== "r2" && hi <= 1 && lo >= 0 ? `${(v * 100).toFixed(0)}%` : formatCell(v));
  return (
    <figure className="my-1 rounded-md border border-border p-2">
      <figcaption className="mb-1 text-[11px] text-muted-foreground">{pd.data.of} as {feature} changes ({fmt(lo)} to {fmt(hi)})</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-16 w-full" role="img"
        aria-label={`${pd.data.of} by ${feature}: ${pts.map((p) => `${p[0]} ${fmt(p[1])}`).join(", ")}`}>
        {numeric ? (
          <>
            <polyline fill="none" stroke="var(--chart-1)" strokeWidth={2} points={pts.map((p, i) => `${x(i)},${y(p[1])}`).join(" ")} />
            {pts.map((p, i) => <circle key={i} cx={x(i)} cy={y(p[1])} r={2.5} fill="var(--chart-accent)"><title>{`${formatCell(p[0])}: ${fmt(p[1])}`}</title></circle>)}
          </>
        ) : (
          pts.map((p, i) => {
            const bw = Math.max(6, (W - 16) / pts.length - 4);
            return (
              <rect key={i} x={x(i) - bw / 2} y={y(p[1])} width={bw} height={H - y(p[1])} fill="var(--chart-1)">
                <title>{`${String(p[0])}: ${fmt(p[1])}`}</title>
              </rect>
            );
          })
        )}
      </svg>
      <div className="flex justify-between text-[11px] text-muted-foreground">
        <span>{formatCell(pts[0]?.[0])}</span>
        <span>{formatCell(pts[pts.length - 1]?.[0])}</span>
      </div>
    </figure>
  );
}
