// ML setup inside a widget (PRD ML-2, App Flow §9 step 2, UI/UX brief §5.8), generated from the
// recipe manifest: Target (pre-filled), Features (chips; excluded ones struck through with the reason on
// hover; re-including one warns), Rows (the scope chip; the dashboard's filter when one is active),
// Method (Auto only: cut 4), More (the manifest's params), the baselines for this scope, and Run.
import { AlertTriangle } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { fmtMetric, METRIC_LABELS, usePreview, useRecipes, useRunActions, type RunRequest } from "@/api/ml";
import type { Widget } from "@/api/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useGlobalFilter } from "@/state/filters";

const Overline = ({ children }: { children: React.ReactNode }) => (
  <h4 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{children}</h4>
);

/** The target a widget suggests: an analysis's own, else the chart's measure or category when it can be explained. */
function guessTarget(widget: Widget): string | undefined {
  const c = widget.spec.scope.columns as Record<string, unknown>;
  return (c.target ?? c.y ?? c.x ?? undefined) as string | undefined;
}

export function MlSetup({ widget, recipe, onCancel, onStarted }: {
  widget: Widget; recipe: string; onCancel: () => void; onStarted: () => void;
}) {
  const recipes = useRecipes(widget.dataset_id);
  const manifest = recipes.data?.find((r) => r.id === recipe);
  const filter = useGlobalFilter(widget.dataset_id);
  const isMl = widget.spec.op.type === "ml";
  const guess = guessTarget(widget);
  const [target, setTarget] = useState<string | undefined>(
    guess && (!manifest?.targets || manifest.targets.includes(guess)) ? guess : undefined);
  const [chosen, setChosen] = useState<string[] | null>(
    isMl ? ((widget.spec.scope.columns as { features?: string[] | null }).features ?? null) : null);
  const [useFilter, setUseFilter] = useState(!!filter);
  const [params, setParams] = useState<Record<string, number>>(
    isMl && widget.spec.op.type === "ml" ? (widget.spec.op.params as Record<string, number>) : {});
  const [warning, setWarning] = useState<string | null>(null);
  const actions = useRunActions(widget.dataset_id);

  const body: RunRequest = useMemo(() => ({
    recipe,
    method: "auto",
    scope: {
      columns: { target: target && manifest?.targets && !manifest.targets.includes(target) ? undefined : target, features: chosen },
      rows: { predicate: widget.spec.scope.rows.predicate ?? null, selection_id: widget.spec.scope.rows.selection_id ?? null },
    },
    params,
    filters: useFilter && filter ? [filter] : [],
  }), [recipe, target, chosen, widget.spec.scope.rows, params, useFilter, filter, manifest]);
  const preview = usePreview(widget.dataset_id, manifest?.compatible ? body : null);
  const p = preview.data;
  const excluded = new Map((p?.excluded ?? []).map((e) => [e.column, e.reason]));
  const forced = new Map((p?.forced ?? []).map((e) => [e.column, e.reason]));

  const toggle = (col: string) => {
    if (!p) return;
    const on = chosen ?? p.features;
    if (on.includes(col)) {
      setChosen(on.filter((c) => c !== col));
      setWarning(null);
    } else {
      setChosen([...on, col]);
      const reason = excluded.get(col);
      if (reason && reason !== "turned off in the setup") {
        setWarning(`${col} was left out (${reason}). It's back in; the model card will warn about it.`);
      }
    }
  };

  const run = () =>
    actions.start.mutate({ ...body, scope: { ...body.scope, columns: { ...body.scope!.columns, target: p?.target } }, widget_id: widget.id }, {
      onSuccess: (r) => {
        if (r.status === "done") toast("Same settings as an earlier run: showing its result.");
        onStarted();
      },
      onError: (e) => toast.error((e as Error).message),
    });

  if (manifest && !manifest.compatible) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-[13px] text-muted-foreground">
        <p>{manifest.label} isn't available here: {manifest.reason}.</p>
        <Button size="sm" variant="ghost" onClick={onCancel}>Back</Button>
      </div>
    );
  }
  const props = manifest?.params?.properties ?? {};
  return (
    <form
      className="flex h-full flex-col gap-3 overflow-y-auto py-2 text-[13px]"
      aria-label="Set up the analysis"
      onSubmit={(e) => {
        e.preventDefault();
        run();
      }}
    >
      <section className="flex flex-col gap-1.5">
        <Overline>Target</Overline>
        <select
          aria-label="Column to explain"
          className="h-8 w-full max-w-[280px] rounded-md border border-border bg-card px-2 text-[13px]"
          value={p?.target ?? target ?? ""}
          onChange={(e) => {
            setTarget(e.target.value);
            setChosen(null);
            setWarning(null);
          }}
        >
          {(p?.targets ?? manifest?.targets ?? []).map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        {p && <p className="text-muted-foreground">{p.task === "regression" ? "A number" : "Categories"}: scored by {METRIC_LABELS[p.metric] ?? p.metric}.</p>}
      </section>

      <section className="flex flex-col gap-1.5">
        <Overline>Features</Overline>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Features">
          {(p?.columns ?? []).map((col) => {
            const reason = excluded.get(col);
            const on = !reason;
            return (
              <button
                key={col}
                type="button"
                aria-pressed={on}
                title={reason ? `Left out: ${reason}` : forced.has(col) ? `Put back in although it ${forced.get(col)}` : "Used. Click to leave it out."}
                onClick={() => toggle(col)}
                className={cn(
                  "inline-flex h-6 items-center gap-1 rounded-full border px-2.5 text-[12px] focus-visible:outline-2 focus-visible:outline-ring",
                  on ? "border-border-strong bg-card text-foreground" : "border-border bg-muted text-muted-foreground line-through",
                  forced.has(col) && "border-warning",
                )}
              >
                {forced.has(col) && <AlertTriangle className="size-3 text-warning" aria-label="flagged" />}
                {col}
              </button>
            );
          })}
          {!p && preview.isLoading && <span className="text-muted-foreground">Checking the columns…</span>}
        </div>
        {warning && <p className="flex items-start gap-1.5 text-warning"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" />{warning}</p>}
      </section>

      <section className="flex flex-col gap-1.5">
        <Overline>Rows</Overline>
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex h-6 items-center rounded-full border border-border bg-secondary px-2.5 text-[12px] text-muted-foreground">
            {widget.spec.scope.rows.predicate ? "Some rows" : "All rows"}
            {useFilter && filter ? ` · ${filter.col} = ${String(filter.value)}` : ""}
            {p ? ` · ${p.rows.with_target.toLocaleString("en-US")} with ${p.target}` : ""}
          </span>
          {filter && (
            <label className="inline-flex items-center gap-1.5 text-muted-foreground">
              <input type="checkbox" checked={useFilter} onChange={(e) => setUseFilter(e.target.checked)} />
              Only the filtered rows
            </label>
          )}
        </div>
      </section>

      <section className="flex flex-col gap-1">
        <Overline>Method</Overline>
        <p className="text-muted-foreground">
          <span className="font-medium text-foreground">Auto</span>: tries {p?.task === "regression" ? "ridge regression" : "logistic regression"},
          gradient boosting and a random forest on the same folds and keeps the best.
        </p>
      </section>

      <details className="group">
        <summary className="cursor-pointer select-none text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">More</summary>
        <div className="mt-2 flex flex-wrap gap-3">
          {Object.entries(props).map(([name, spec]) => (
            <label key={name} className="flex flex-col gap-1 text-muted-foreground">
              {spec.title ?? name}
              <input
                type="number"
                min={spec.minimum}
                max={spec.maximum}
                value={params[name] ?? spec.default}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  if (Number.isInteger(v) && v >= spec.minimum && v <= spec.maximum) setParams((s) => ({ ...s, [name]: v }));
                }}
                className="h-8 w-24 rounded-md border border-border bg-card px-2 font-mono text-[13px] text-foreground"
              />
            </label>
          ))}
        </div>
      </details>

      <section className="flex flex-col gap-1">
        <Overline>Baselines</Overline>
        {preview.error ? (
          <p className="text-destructive">{(preview.error as Error).message}</p>
        ) : (
          <table className="w-full max-w-[420px] text-[12px]">
            <tbody>
              {(p?.baselines ?? []).map((b) => (
                <tr key={b.name} className="border-b border-border">
                  <td className="py-1 pr-2">{b.name.replace(/^best one-column rule: /, "Best one-column rule: ")}</td>
                  <td className="py-1 text-right font-mono">{fmtMetric(b.metric, b.value)}</td>
                </tr>
              ))}
              <tr>
                <td className="py-1 pr-2 font-semibold">Model</td>
                <td className="py-1 text-right text-muted-foreground">{p?.cached ? "already run" : "pending"}</td>
              </tr>
            </tbody>
          </table>
        )}
      </section>

      <footer className="mt-auto flex items-center gap-2 pt-1">
        <span className="text-muted-foreground">{p ? `about ${p.estimate_s} s` : ""}</span>
        <Button type="button" size="sm" variant="ghost" className="ml-auto" onClick={onCancel}>Cancel</Button>
        <Button type="submit" size="sm" variant="primary" disabled={!p || !!preview.error} loading={actions.start.isPending}>Run</Button>
      </footer>
    </form>
  );
}
