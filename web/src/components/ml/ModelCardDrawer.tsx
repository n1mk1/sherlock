// The model card drawer (PRD ML-3, ML-5; UI/UX brief §5.9): verdict, data, excluded columns with
// reasons, method, baselines vs the model with its interval, importance, warnings with suggestions,
// and Re-run when outdated. Compare with Auto is cut (cut 4: Auto is the only method).
import { AlertTriangle, Code2 } from "lucide-react";
import { useState } from "react";
import { fmtMetric, METRIC_LABELS, useRun, useRunActions, useRunCode } from "@/api/ml";
import type { Widget } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/drawer";

const H = ({ children }: { children: React.ReactNode }) => (
  <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{children}</h3>
);

export function ModelCardDrawer({ widget, runId, onClose }: { widget: Widget; runId: string | null; onClose: () => void }) {
  const run = useRun(runId);
  const actions = useRunActions(widget.dataset_id);
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
                <Button size="sm" onClick={() => actions.rerun.mutate(widget.id)} loading={actions.rerun.isPending}>Re-run</Button>
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
              {card.sample && ` A random sample of ${card.sample.n.toLocaleString("en-US")} rows (seed ${card.sample.seed}).`}
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
              {card.split.folds}-fold {card.split.kind === "stratified_kfold" ? "stratified " : ""}cross-validation (seed {card.split.seed}).
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
