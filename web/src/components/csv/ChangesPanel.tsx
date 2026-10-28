// The Changes panel (App Flow §8.5, UI/UX brief §5.7): the right panel on a dataset. "Unsaved
// (yours)" lists the pending edits, each removable; "Steps" lists every step newest first, with
// Undo on the ones in the current data. Expanding a step shows its code (cleaning) or its edit list,
// its impact and its decisions. Undo of an earlier step asks first and replays the later steps;
// undoing the typing step warns first. Footer: the full cleaning report and Export notebook.
import { useQuery } from "@tanstack/react-query";
import { BookOpen, ChevronDown, ChevronRight, FileText, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { request, type ApiError } from "@/api/client";
import { useUndo, type StepDetail } from "@/api/csv";
import { useCancelJob, useDataset, useJobs, useSteps } from "@/api/queries";
import type { Dataset, Step } from "@/api/types";
import { ReportSummary } from "@/components/dataset/CleaningReport";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Drawer } from "@/components/ui/drawer";
import { Pill } from "@/components/ui/pill";
import { displayValue } from "@/lib/cells";
import { cn } from "@/lib/utils";
import { pendingCount, useEdits } from "@/state/edits";
import { useUi } from "@/state/ui";

export function ChangesPanel({ datasetId }: { datasetId: string }) {
  const { data: dataset } = useDataset(datasetId);
  const { data: steps } = useSteps(datasetId);
  const [report, setReport] = useState(false);
  const setExportOpen = useUi((s) => s.setExportOpen);
  if (!dataset) return null;
  const latestActive = steps?.find((s) => s.active && s.kind !== "undo" && s.kind !== "redo");
  const active = steps?.filter((s) => s.active && s.kind !== "undo" && s.kind !== "redo").length ?? 0;
  return (
    <section aria-labelledby="changes-title" className="flex h-full flex-col">
      <div className="flex h-14 shrink-0 items-center gap-2 px-5">
        <h2 id="changes-title" className="type-heading">Changes</h2>
        {active > 0 && <Pill tone="teal" size="sm">{active} {active === 1 ? "step" : "steps"}</Pill>}
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-3 pb-4">
        <RunningClean dataset={dataset} />
        <Unsaved datasetId={datasetId} />
        {steps?.length === 0 && (
          <p className="px-2 text-[13px] text-muted-foreground">Nothing yet. Saved edits and cleaning fixes show up here, and each one can be undone.</p>
        )}
        {!!steps?.length && (
          <ol className="flex flex-col">
            {steps.map((s) => (
              <StepCard key={s.id} step={s} dataset={dataset} latest={s.id === latestActive?.id} />
            ))}
          </ol>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1 border-t border-border px-3 py-2.5">
        <Button variant="ghost" size="sm" onClick={() => setReport(true)}><FileText /> Cleaning report</Button>
        <Button variant="ghost" size="sm" onClick={() => setExportOpen(true)}><BookOpen /> Export notebook</Button>
      </div>
      <Drawer open={report} onOpenChange={setReport} title="Cleaning report">
        <ReportSummary datasetId={datasetId} title="Last cleaning report" />
      </Drawer>
    </section>
  );
}

function RunningClean({ dataset }: { dataset: Dataset }) {
  const { data: jobs } = useJobs(dataset.id);
  const progress = useUi((s) => s.progress[dataset.id]);
  const cancel = useCancelJob(dataset.id);
  const job = jobs?.find((j) => j.kind === "clean" && (j.status === "running" || j.status === "queued"));
  if (!job) return null;
  const live = progress?.job_id === job.id ? progress : job.progress;
  return (
    <div className="rounded-2xl bg-violet-soft p-3.5 text-[13px]" role="status">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 font-medium text-violet-ink"><Sparkles className="size-3.5" aria-hidden /> Cleaning…</span>
        <Button size="sm" variant="ghost" className="h-7" onClick={() => cancel.mutate(job.id)}>Stop</Button>
      </div>
      <p className="mt-1 text-foreground-2">{live?.label || "Starting"}</p>
      <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--violet)_18%,transparent)]">
        <div className="h-full rounded-full bg-violet transition-[width] duration-[var(--duration-base)]" style={{ width: `${live?.pct ?? 0}%` }} />
      </div>
    </div>
  );
}

function Unsaved({ datasetId }: { datasetId: string }) {
  const buffer = useEdits((s) => s.buffers[datasetId]);
  const { removeEdit, removeNewRow } = useEdits();
  const n = pendingCount(buffer);
  if (!buffer || n === 0) return null;
  const lines: { key: string; text: string; remove: () => void }[] = [
    ...buffer.newRows.map((r) => ({
      key: r.temp_id, text: `New row${Object.keys(r.cells).length ? `: ${Object.entries(r.cells).map(([c, v]) => `${c} = ${v}`).join(", ")}` : ""}`,
      remove: () => removeNewRow(datasetId, r.temp_id),
    })),
    ...Object.entries(buffer.edits).map(([k, e]) => ({
      key: k, text: `Row ${e.row_id} · ${e.column}: ${displayValue(e.old) || "—"} → ${e.value || "—"}`, remove: () => removeEdit(datasetId, k),
    })),
    ...buffer.deleted.map((r) => ({ key: `d${r}`, text: `Delete row ${r}`, remove: () => removeEdit(datasetId, `deleted:${r}`) })),
    ...buffer.restored.map((r) => ({ key: `r${r}`, text: `Restore row ${r} from quarantine`, remove: () => removeEdit(datasetId, `restored:${r}`) })),
  ];
  return (
    <div className="rounded-2xl bg-accent-soft p-3.5">
      <p className="flex items-center gap-2 text-[13px] font-semibold">Not saved yet <Pill tone="accent" size="sm">{n}</Pill></p>
      <ul className="mt-2 flex max-h-[220px] flex-col gap-1 overflow-y-auto">
        {lines.map((l) => (
          <li key={l.key} className="flex items-center gap-2 text-[12.5px]">
            <span className="min-w-0 flex-1 truncate" title={l.text}>{l.text}</span>
            <button type="button" aria-label={`Remove: ${l.text}`} onClick={l.remove}
              className="rounded-full p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"><X className="size-3.5" /></button>
          </li>
        ))}
      </ul>
    </div>
  );
}

const WHO: Record<string, string> = { system: "Automatic", cleaner: "Sherlock", user: "You", chat: "From chat" };

function detailLine(s: Step): string {
  const parts: string[] = [];
  if (s.column_targets?.length) parts.push(s.column_targets.slice(0, 3).join(", ") + (s.column_targets.length > 3 ? "…" : ""));
  if (s.impact.cells_changed) parts.push(`${s.impact.cells_changed.toLocaleString()} cells`);
  if (s.impact.rows_added) parts.push(`${s.impact.rows_added} added`);
  if (s.impact.rows_deleted) parts.push(`${s.impact.rows_deleted} deleted`);
  if (s.impact.quarantined) parts.push(`${s.impact.quarantined} quarantined`);
  if (s.gate === "flag") parts.push("flagged");
  return parts.join(" · ");
}

function StepCard({ step, dataset, latest }: { step: Step; dataset: Dataset; latest: boolean }) {
  const [open, setOpen] = useState(false);
  const [ask, setAsk] = useState<{ replay: number[]; typing: boolean } | null>(null);
  const undo = useUndo(dataset.id);
  const canUndo = step.active && step.kind !== "undo" && step.kind !== "redo";

  const run = (confirm: boolean) =>
    undo.mutate({ stepId: step.id, base: dataset.current_version, confirm }, {
      onSuccess: (r) => {
        if ("confirm_required" in r) setAsk({ replay: r.replay_needed, typing: r.warning === "typing" });
        else {
          setAsk(null);
          toast(`Undid step ${step.no}`);
        }
      },
      onError: (e) => {
        setAsk(null);
        const err = e as ApiError;
        toast.error(err.message);
      },
    });

  return (
    // An undone step reads as set aside by its struck-through, muted text, not by opacity, which took its
    // text under 4.5:1.
    <li className={cn("group rounded-xl px-2 py-2.5 transition-colors hover:bg-secondary", open && "bg-secondary", latest && "font-medium")}>
      <div className="flex items-start gap-2.5">
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label={open ? "Collapse step" : "Expand step"}
          className={cn("mt-px inline-flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold tnum",
            step.active ? "bg-teal-soft text-teal-ink" : "bg-secondary text-muted-foreground")}>
          <span className="group-hover:hidden">{step.no}</span>
          {open ? <ChevronDown className="hidden size-3.5 group-hover:block" /> : <ChevronRight className="hidden size-3.5 group-hover:block" />}
        </button>
        <div className="min-w-0 flex-1">
          <p className={cn("text-[13.5px] font-medium leading-snug tracking-[-0.01em]", !step.active && "text-muted-foreground",
            !step.active && step.kind !== "undo" && step.kind !== "redo" && "line-through")}>{step.summary}</p>
          <p className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[12px] font-normal text-muted-foreground tnum">
            <Pill size="sm" tone={step.created_by === "cleaner" ? "violet" : step.created_by === "chat" ? "blue" : "neutral"}>
              {WHO[step.created_by] ?? step.created_by}
            </Pill>
            {detailLine(step)}{!step.active && step.kind !== "undo" && step.kind !== "redo" ? " · undone" : ""}
          </p>
        </div>
        {canUndo && (
          <Button size="sm" variant="ghost" className="h-7 px-2.5 text-[12.5px] text-muted-foreground hover:text-foreground"
            loading={undo.isPending && !ask} onClick={() => run(false)}>Undo</Button>
        )}
      </div>
      {open && <StepDetailView datasetId={dataset.id} stepId={step.id} />}
      <Dialog open={!!ask} onOpenChange={(o) => !o && setAsk(null)}>
        <DialogContent className="max-w-[460px] gap-4 p-6">
          <DialogTitle className="type-title">Undo step {step.no}?</DialogTitle>
          <DialogDescription className="text-[14px] text-muted-foreground">
            {ask?.typing && "Undoing typing turns every column back into text; charts and models that need numbers will stop working. "}
            {(ask?.replay.length ?? 0) > 0 &&
              `This undoes step ${step.no} and replays the later steps still in effect (${replayText(ask?.replay ?? [])}) on top. If a replay fails, nothing changes.`}
          </DialogDescription>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setAsk(null)}>Cancel</Button>
            <Button variant="primary" loading={undo.isPending} onClick={() => run(true)}>Undo step {step.no}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </li>
  );
}

function replayText(nos: number[]) {
  if (nos.length === 0) return "none";
  if (nos.length > 1 && nos[nos.length - 1] - nos[0] === nos.length - 1) return `steps ${nos[0]}–${nos[nos.length - 1]}`;
  return nos.length === 1 ? `step ${nos[0]}` : `steps ${nos.join(", ")}`;
}

function StepDetailView({ datasetId, stepId }: { datasetId: string; stepId: string }) {
  const { data: s } = useQuery({
    queryKey: ["step", datasetId, stepId],
    queryFn: () => request<StepDetail>("GET", `/api/v1/datasets/${datasetId}/steps/${stepId}`),
  });
  if (!s) return <p className="mt-2 text-[12px] text-muted-foreground">Loading…</p>;
  const e = s.edits;
  return (
    <div className="mt-3 flex flex-col gap-2 pl-7 text-[12.5px] font-normal">
      {s.kind === "edit" && e ? (
        <ul className="flex flex-col gap-0.5 font-mono">
          {e.edits.slice(0, 50).map((x, i) => <li key={i}>Row {x.row_id} · {x.column} → {displayValue(x.value) || "—"}</li>)}
          {e.new_rows.map((r) => <li key={r.row_id}>Added row {r.row_id}</li>)}
          {e.deleted_row_ids.map((r) => <li key={`d${r}`}>Deleted row {r}</li>)}
          {e.restore_row_ids.map((r) => <li key={`r${r}`}>Restored row {r}</li>)}
          {e.edits.length > 50 && <li className="text-muted-foreground">and {e.edits.length - 50} more</li>}
        </ul>
      ) : s.kind !== "undo" && s.kind !== "redo" ? (
        <pre className="max-h-[260px] overflow-auto whitespace-pre-wrap rounded-xl bg-card p-3 type-data text-[12px] leading-relaxed">
          {s.notebook_code}
        </pre>
      ) : null}
      <p className="text-muted-foreground">
        {s.impact.rows_in.toLocaleString()} rows in, {s.impact.rows_out.toLocaleString()} out · {s.impact.cells_changed.toLocaleString()} cells changed
        {s.impact.quarantined ? ` · ${s.impact.quarantined} quarantined` : ""}
      </p>
      {s.flag_reason && <p className="text-warning">Flag: {s.flag_reason}</p>}
      {s.decisions.map((d, i) => (
        <p key={i}>
          {d.asked && <span className="block text-muted-foreground">You asked: “{d.asked}”</span>}
          <span className="font-medium">{d.question}</span> {d.chosen}{d.reason ? `. ${d.reason}` : ""}
        </p>
      ))}
      {s.impact.before_after.length > 0 && s.kind !== "edit" && (
        <ul className="flex flex-col gap-0.5 font-mono text-muted-foreground">
          {s.impact.before_after.slice(0, 6).map((b, i) => <li key={i}>Row {b.row_id} · {b.column}: {b.old ?? "—"} → {b.new ?? "—"}</li>)}
        </ul>
      )}
    </div>
  );
}
