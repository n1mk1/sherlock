// The model card drawer (PRD ML-3, ML-5; UI/UX brief §5.9): verdict, data, excluded columns with
// reasons, method, baselines vs the model with its interval, importance, warnings with suggestions,
// the confusion matrix and ROC curve for categories, "Who did it get wrong?" (the misclassified rows in
// the grid), and Re-run when outdated. Compare with Auto is cut (cut 4: Auto is the only method).
// Opened from a chat answer about a run (`open_model_card`).
import { AlertTriangle, Code2, Rows3 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { fmtMetric, METRIC_LABELS, useRun, useRunActions, useRunCode } from "@/api/ml";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/drawer";

const H = ({ children }: { children: React.ReactNode }) => (
  <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{children}</h3>
);

export function ModelCardDrawer({ datasetId, runId: opened, onClose }: {
  datasetId: string; runId: string | null; onClose: () => void;
}) {
  // Re-run swaps the card to the new run; reopening from another answer starts from its own run.
  const [rerunOf, setRerunOf] = useState<{ from: string; to: string } | null>(null);
  const runId = opened && rerunOf?.from === opened ? rerunOf.to : opened;
  const run = useRun(runId);
  const actions = useRunActions(datasetId);
  const navigate = useNavigate();
  const wrong = () =>
    runId && actions.wrongRows.mutate(runId, {
      onSuccess: (sel) => {
        onClose();
        navigate(`/d/${datasetId}?rows=${sel.selection_id}`);
        toast(`${sel.row_count.toLocaleString("en-US")} rows the model predicted wrong`);
      },
      onError: (e) => toast.error((e as Error).message),
    });
  const [showCode, setShowCode] = useState(false);
  const code = useRunCode(runId, showCode);
  const card = run.data?.model_card;
  const label = card ? METRIC_LABELS[card.model.metric] ?? card.model.metric : "";
  const scope = card?.scope.rows.predicate ? `rows where ${card.scope.rows.predicate}` : "all rows";
  return (
    <Drawer open={!!runId} onOpenChange={(o) => !o && onClose()} title="Model card">
      {!card ? (
        <p className="text-[13px] text-muted-foreground">{run.error ? (run.error as Error).message : "The model card is written when the analysis finishes."}</p>
      ) : (
        <div className="flex flex-col gap-5 text-[13px]">
          <section>
            <p className="font-serif text-[20px] font-semibold leading-snug">{card.verdict_text}</p>
            {run.data?.status === "outdated" && (
              <div className="mt-2 flex items-center gap-2 rounded-lg border border-warning p-2 text-warning">
                <AlertTriangle className="size-4 shrink-0" />
                <span className="flex-1">Outdated: the data changed after this ran on v{card.version}.</span>
                <Button size="sm" loading={actions.rerun.isPending} onClick={() => actions.rerun.mutate(run.data!, {
                  onSuccess: (next) => opened && setRerunOf({ from: opened, to: next.id }),
                  onError: (e) => toast.error((e as Error).message),
                })}>Re-run</Button>
              </div>
            )}
          </section>

          <section>
            <H>Data</H>
            <p>
              What drives <span className="font-medium">{card.target}</span> ({card.task}) on version <span className="font-mono">v{card.version}</span>, {scope}:{" "}
              <span className="font-mono">{card.rows.train.toLocaleString("en-US")}</span> rows used of{" "}
              <span className="font-mono">{card.rows.total.toLocaleString("en-US")}</span>
              {card.rows.blank_target ? ` (${card.rows.blank_target.toLocaleString("en-US")} without ${card.target} left out)` : ""}.
              {card.sample && ` A random sample of ${card.sample.n.toLocaleString("en-US")} rows (${card.sample.stratify_column ? `stratified by ${card.sample.stratify_column}, ` : ""}seed ${card.sample.seed}).`}
            </p>
          </section>

          <section>
            <H>Excluded columns</H>
            {card.excluded.length ? (
              <ul className="flex flex-col gap-1">
                {card.excluded.map((e) => (
                  <li key={e.column}><span className="font-mono line-through">{e.column}</span><span className="text-muted-foreground">: {e.reason}</span></li>
                ))}
              </ul>
            ) : <p className="text-muted-foreground">None: every column was used.</p>}
          </section>

          <section>
            <H>Method</H>
            <p>
              Auto picked <span className="font-medium">{labelOf(card.chosen_model)}</span> by{" "}
              {card.split.folds}-fold {card.split.kind.startsWith("stratified") ? "stratified " : ""}cross-validation (seed {card.split.seed})
              {card.split.group ? <>, keeping rows that share a <span className="font-mono">{card.split.group}</span> in one fold.</> : "."}
            </p>
            {card.alternatives.length > 0 && (
              <p className="text-muted-foreground">
                Also tried: {card.alternatives.map((a) => `${a.label} (${fmtMetric(a.metric, a.value)})`).join(", ")}.
              </p>
            )}
            <p className="text-muted-foreground">Folds {card.params.cv_folds}, time budget {card.params.time_budget_s} s.</p>
          </section>

          <section>
            <H>Baselines vs model</H>
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-left text-muted-foreground"><th className="py-1 font-normal">On held-out rows</th><th className="py-1 text-right font-normal">{label}</th><th className="py-1 text-right font-normal">95% interval</th></tr>
              </thead>
              <tbody>
                {card.baselines.map((b) => (
                  <tr key={b.name} className="border-t border-border">
                    <td className="py-1 pr-2">{b.name}</td>
                    <td className="py-1 text-right font-mono">{fmtMetric(b.metric, b.value)}</td>
                    <td />
                  </tr>
                ))}
                <tr className="border-t border-border font-semibold">
                  <td className="py-1 pr-2">Model: {labelOf(card.chosen_model)}</td>
                  <td className="py-1 text-right font-mono">{fmtMetric(card.model.metric, card.model.value)}</td>
                  <td className="py-1 text-right font-mono">{fmtMetric(card.model.metric, card.model.ci[0])} to {fmtMetric(card.model.metric, card.model.ci[1])}</td>
                </tr>
              </tbody>
            </table>
            {(card.model.auc !== undefined || card.model.mae !== undefined) && (
              <p className="mt-1 text-muted-foreground">
                {card.model.auc !== undefined && <>AUC <span className="font-mono">{card.model.auc.toFixed(3)}</span>. </>}
                {card.model.mae !== undefined && <>Mean absolute error <span className="font-mono">{card.model.mae.toFixed(3)}</span>.</>}
              </p>
            )}
          </section>

          <section>
            <H>Importance</H>
            <p className="mb-1 text-muted-foreground">Permutation importance on held-out folds (10 repeats); 1 is the strongest.</p>
            <ol className="flex flex-col gap-0.5">
              {card.importance.map((i) => (
                <li key={i.column} className="flex justify-between"><span>{i.column}</span><span className="font-mono text-muted-foreground">{i.value.toFixed(2)}</span></li>
              ))}
            </ol>
          </section>

          {card.confusion && (
            <section>
              <H>Who it got wrong</H>
              <p className="mb-1.5 text-muted-foreground">Each row predicted by a model that never saw it.</p>
              <ConfusionMatrix labels={card.confusion.labels} matrix={card.confusion.matrix} target={card.target} />
              {card.roc && <div className="mt-2"><RocCurve points={card.roc.points} auc={card.roc.auc} positive={card.roc.positive} /></div>}
              {!!card.misclassified && (
                <Button size="sm" className="mt-2" onClick={wrong} loading={actions.wrongRows.isPending}>
                  <Rows3 /> Who did it get wrong? ({card.misclassified.toLocaleString("en-US")} rows)
                </Button>
              )}
            </section>
          )}

          {card.warnings.length > 0 && (
            <section>
              <H>Warnings</H>
              <ul className="flex flex-col gap-2">
                {card.warnings.map((w) => (
                  <li key={w.code + w.text} className="rounded-lg border border-warning p-2">
                    <p className="flex items-start gap-1.5"><AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" />{w.text}</p>
                    <p className="pl-5 text-muted-foreground">{w.suggestion}</p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <H>Limits</H>
            <p className="text-muted-foreground">{card.limits.join("; ")}.</p>
          </section>

          <section className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => setShowCode((s) => !s)}><Code2 /> {showCode ? "Hide the code" : "Show the code"}</Button>
          </section>
          {showCode && (
            <pre className="max-h-[50vh] overflow-auto whitespace-pre rounded-lg bg-muted p-3 font-mono text-[11px] leading-relaxed">
              {code.data?.python ?? "…"}
            </pre>
          )}
        </div>
      )}
    </Drawer>
  );
}

const LABELS: Record<string, string> = {
  logistic_regression: "Logistic regression", ridge: "Ridge regression", gradient_boosting: "Gradient boosting", random_forest: "Random forest",
};
const labelOf = (m: string) => LABELS[m] ?? m;

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
