// The end-of-run report (App Flow §5, PRD CLEAN-6): what became of each issue (fixed · flagged · checked
// and kept · couldn't fix · not attempted, with marked-not-changed apart) and the first steps, with the full
// report (every step, each skipped issue under its line with its level, the decisions, and "How I worked it
// out": the run's model calls) one click away. The Changes panel links here (D5.4).
import { Check, Flag, Redo2 } from "lucide-react";
import { useState } from "react";
import { useReport } from "@/api/queries";
import type { CleaningReport, Level } from "@/api/types";
import { Receipts } from "@/components/chat/Receipts";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

const ENDED: Record<CleaningReport["ended_by"], string> = {
  done: "Every issue was looked at.",
  steps: "Stopped at the issue budget.",
  time: "Stopped at the time budget.",
  tokens: "Stopped at the model budget.",
  stopped: "You stopped the run.",
  error: "The model service became unavailable.",
};

const LEVEL: Record<Level, string> = {
  breaks: "Breaks answers", skews: "Skews answers", splits: "Splits groups", check: "Worth a look", cosmetic: "Cosmetic",
};
// Each skip's report line, by its kind (`loop.SKIP_KINDS`), in display order.
const LINES: [string, string, string[]][] = [
  ["checked_and_kept", "Checked and kept", ["left_as_is"]],
  ["couldnt_fix", "Couldn't fix", ["failed_checks", "disagreement", "gate", "model_error", "conflict"]],
  ["not_attempted", "Not attempted", ["unticked", "needs_choice"]],
  ["kept_by_design", "Marked, not changed", ["kept_by_design"]],
];

/** The summary's counts: the five outcomes for a run that records why it skipped, else the old four. */
export function reportCounts(c: CleaningReport["counts"]): [string, number][] {
  if (c.checked_and_kept === undefined) {
    return [["found", c.found], ["fixed", c.fixed], ["flagged", c.flagged], ["skipped", c.skipped], ["rows deleted", 0]];
  }
  return [["fixed", c.fixed], ["flagged", c.flagged], ["checked and kept", c.checked_and_kept],
    ["couldn't fix", c.couldnt_fix ?? 0], ["not attempted", c.not_attempted ?? 0]];
}

export function ReportSummary({ datasetId, title = "Cleaning report" }: { datasetId: string; title?: string }) {
  const { data: report } = useReport(datasetId);
  const [open, setOpen] = useState(false);
  if (!report) return null;
  const c = report.counts;
  return (
    <section className="rounded-2xl border border-border bg-card p-6" aria-labelledby="report-title">
      <h3 id="report-title" className="font-serif text-[22px] leading-tight">{title}</h3>
      <p className="mt-1 text-muted-foreground">
        {report.ended_by === "steps" && report.budget.max_steps
          ? `Stopped at the ${report.budget.max_steps}-issue budget.`
          : ENDED[report.ended_by]}{" "}
        v{report.from_version} → v{report.to_version}
        {report.waited_for_model_s > 0 && ` · waited ${Math.round(report.waited_for_model_s)} s for the model`}
      </p>
      <dl className="mt-4 grid grid-cols-5 gap-2 text-center">
        {reportCounts(c).map(
          ([label, n]) => (
            <div key={label} className="rounded-xl bg-muted p-2">
              <dd className="font-serif text-[24px] leading-none">{n}</dd>
              <dt className="mt-1 text-[12px] text-muted-foreground">{label}</dt>
            </div>
          ),
        )}
      </dl>
      {c.kept_by_design !== undefined && (
        <p className="mt-2 text-[13px] text-muted-foreground">
          {c.found.toLocaleString()} found · {c.kept_by_design} marked, not changed (leakage and ID columns) · no rows deleted
        </p>
      )}
      <ul className="mt-4 flex flex-col gap-1.5">
        {report.steps.slice(0, 3).map((s) => <StepLine key={s.step_id} step={s} />)}
      </ul>
      <Button variant="link" className="mt-3" onClick={() => setOpen(true)}>View full report</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-[720px]">
          <div className="border-b border-border px-6 pb-4 pt-5">
            <DialogTitle className="font-serif text-[22px]">{title}</DialogTitle>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
            <FullReport report={report} />
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function StepLine({ step }: { step: CleaningReport["steps"][number] }) {
  return (
    <li className="flex items-start gap-2">
      {step.gate === "flag" ? <Flag className="mt-1 size-4 text-warning" aria-label="flagged" /> : <Check className="mt-1 size-4 text-success" aria-label="committed" />}
      <span>
        <span className="font-mono text-[12.5px] text-muted-foreground">step {step.no}</span> {step.summary}
        <span className="text-muted-foreground"> · {step.impact.cells_changed.toLocaleString()} cells
          {step.impact.quarantined ? ` · ${step.impact.quarantined} rows quarantined` : ""}
        </span>
        {step.flag_reason && <span className="block text-[13px] text-warning">{step.flag_reason}</span>}
      </span>
    </li>
  );
}

function SkipList({ skips }: { skips: CleaningReport["skipped"] }) {
  return (
    <ul className="mt-2 flex flex-col gap-1.5">
      {skips.map((s) => (
        <li key={s.issue_id} className="flex items-start gap-2">
          <Redo2 className="mt-1 size-4 text-muted-foreground" aria-hidden />
          <span>
            <span className="font-mono text-[13px]">{s.column ?? "rows"}</span> · {s.reason}
            {s.level && <span className="text-[12.5px] text-muted-foreground"> · {LEVEL[s.level]}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

const YOURS: Record<string, string> = { fixed: "done", flagged: "done with a flag", skipped: "skipped", not_reached: "not reached" };

export function FullReport({ report }: { report: CleaningReport }) {
  return (
    <div className="flex flex-col gap-5">
      {!!report.your_steps?.length && (
        <section>
          <h4 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Your steps</h4>
          <ul className="mt-2 flex flex-col gap-2">
            {report.your_steps.map((s) => (
              <li key={s.item_id} className="flex items-start gap-2">
                {s.outcome === "fixed" ? <Check className="mt-1 size-4 text-success" aria-hidden />
                  : s.outcome === "flagged" ? <Flag className="mt-1 size-4 text-warning" aria-hidden />
                  : <Redo2 className="mt-1 size-4 text-muted-foreground" aria-hidden />}
                <span>
                  <span className="font-mono text-[13px]">{s.column ?? "rows"}</span> · “{s.instruction}” ·{" "}
                  <span className="font-medium">{YOURS[s.outcome] ?? s.outcome}</span>
                  {s.step_no ? <span className="text-muted-foreground"> (step {s.step_no})</span> : null}
                  {s.reason && <span className="block text-[13px] text-muted-foreground">{s.reason}</span>}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h4 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Steps</h4>
        <ul className="mt-2 flex flex-col gap-2">
          {report.steps.length ? report.steps.map((s) => <StepLine key={s.step_id} step={s} />) : <li className="text-muted-foreground">No steps were committed.</li>}
        </ul>
      </section>
      {LINES.map(([key, title, kinds]) => {
        const skips = report.skipped.filter((s) => s.skip_kind && kinds.includes(s.skip_kind));
        return skips.length > 0 && (
          <section key={key}>
            <h4 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{title}</h4>
            <SkipList skips={skips} />
          </section>
        );
      })}
      {/* A run from before skips recorded their kind lists them together. */}
      {(report.skipped.some((s) => !s.skip_kind) || !report.skipped.length) && (
        <section>
          <h4 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Skipped</h4>
          {report.skipped.length ? <SkipList skips={report.skipped.filter((s) => !s.skip_kind)} />
            : <p className="mt-2 text-muted-foreground">Nothing was skipped.</p>}
        </section>
      )}
      {report.hand_edited_skipped.length > 0 && (
        <section>
          <h4 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Cells you edited (left as they are)</h4>
          <p className="mt-2 text-muted-foreground">{report.hand_edited_skipped.length} cells, for example row {report.hand_edited_skipped[0].row_id} in {report.hand_edited_skipped[0].column}.</p>
        </section>
      )}
      <section>
        <h4 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Decisions</h4>
        <ul className="mt-2 flex flex-col gap-2">
          {report.decisions.map((d, i) => (
            <li key={i}>
              {d.asked && <span className="block text-[13px] text-muted-foreground">You asked: “{d.asked}”</span>}
              <span className="font-medium">{d.question}</span> {d.chosen}.{" "}
              <span className="text-muted-foreground">{d.reason}</span>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <Receipts path={`/api/v1/jobs/${report.job_id}/calls`} />
      </section>
    </div>
  );
}
