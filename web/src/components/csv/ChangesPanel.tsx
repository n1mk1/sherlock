// The Changes panel (App Flow §8.5, UI/UX brief §5.7): the right panel on the CSV tab. "Unsaved
// (yours)" lists the pending edits, each removable; "Steps" lists every step newest first, with
// Undo on the ones in the current data. Expanding a step shows its code (cleaning) or its edit list,
// its impact and its decisions. Undo of an earlier step asks first and replays the later steps;
// undoing the typing step warns first. Footer: the full cleaning report and Export notebook.
import { useQuery } from "@tanstack/react-query";
import { BookOpen, ChevronDown, ChevronRight, X } from "lucide-react";
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
  const latestActive = steps?.find((s) => s.active && s.kind !== "undo");
  return (
    <section aria-labelledby="changes-title" className="flex h-full flex-col overflow-y-auto">
      <div className="flex items-center gap-2 px-4 pb-2 pt-4">
        <h2 id="changes-title" className="text-[15px] font-semibold">Changes</h2>
        <span className="inline-flex h-6 items-center rounded-full bg-muted px-2 font-mono text-[12px] text-muted-foreground">v{dataset.current_version}</span>
      </div>
      <div className="flex flex-col gap-3 px-4 pb-4">
        <RunningClean dataset={dataset} />
        <Unsaved datasetId={datasetId} />
        <h3 className="pt-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Steps</h3>
        {steps?.length === 0 && <p className="text-[13px] text-muted-foreground">No steps yet. Edits you save and cleaning fixes appear here.</p>}
        {steps?.map((s) => (
          <StepCard key={s.id} step={s} dataset={dataset} latest={s.id === latestActive?.id} />
        ))}
        <div className="flex flex-col items-start gap-1 border-t border-border pt-3">
          <Button variant="link" size="sm" onClick={() => setReport(true)}>Full cleaning report</Button>
          <Button variant="link" size="sm" onClick={() => setExportOpen(true)}><BookOpen /> Export notebook</Button>
        </div>
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
    <div className="rounded-[14px] border border-accent bg-card p-3 text-[13px]" role="status">
      <div className="flex items-center justify-between">
        <span className="font-medium">Cleaning…</span>
        <Button size="sm" variant="ghost" onClick={() => cancel.mutate(job.id)}>Stop</Button>
      </div>
      <p className="mt-1 text-muted-foreground">{live?.label || "Starting"}</p>
      <div className="mt-2 h-0.5 overflow-hidden rounded bg-muted"><div className="h-full bg-accent" style={{ width: `${live?.pct ?? 0}%` }} /></div>
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
    <div className="rounded-[14px] border border-accent bg-card p-3">
      <p className="text-[13px] font-semibold">Unsaved (yours) · {n}</p>
      <ul className="mt-2 flex max-h-[220px] flex-col gap-1 overflow-y-auto">
        {lines.map((l) => (
          <li key={l.key} className="flex items-center gap-2 text-[12.5px]">
            <span className="min-w-0 flex-1 truncate font-mono" title={l.text}>{l.text}</span>
            <button type="button" aria-label={`Remove: ${l.text}`} onClick={l.remove}
              className="rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"><X className="size-3.5" /></button>
          </li>
        ))}
      </ul>
    </div>
  );
}

const WHO: Record<string, string> = { system: "automatic", cleaner: "Cleaner", user: "you", chat: "chat" };

function detailLine(s: Step): string {
  const parts: string[] = [];
  if (s.column_targets?.length) parts.push(s.column_targets.slice(0, 3).join(", ") + (s.column_targets.length > 3 ? "…" : ""));
  if (s.impact.cells_changed) parts.push(`${s.impact.cells_changed.toLocaleString()} cells`);
  if (s.impact.rows_added) parts.push(`${s.impact.rows_added} added`);
  if (s.impact.rows_deleted) parts.push(`${s.impact.rows_deleted} deleted`);
  if (s.impact.quarantined) parts.push(`${s.impact.quarantined} quarantined`);
  if (s.gate === "flag") parts.push(`flagged${s.confidence != null ? ` · ${s.confidence.toFixed(2)}` : ""}`);
  parts.push(WHO[s.created_by] ?? s.created_by);
  return parts.join(" · ");
}

function StepCard({ step, dataset, latest }: { step: Step; dataset: Dataset; latest: boolean }) {
  const [open, setOpen] = useState(false);
  const [ask, setAsk] = useState<{ replay: number[]; typing: boolean } | null>(null);
  const undo = useUndo(dataset.id);
  const canUndo = step.active && step.kind !== "undo";

  const run = (confirm: boolean) =>
    undo.mutate({ stepId: step.id, base: dataset.current_version, confirm }, {
      onSuccess: (r) => {
        if ("confirm_required" in r) setAsk({ replay: r.replay_needed, typing: r.warning === "typing" });
        else {
          setAsk(null);
          toast(`Undid step ${step.no} · now v${r.version}`);
        }
      },
      onError: (e) => {
        setAsk(null);
        const err = e as ApiError;
        toast.error(err.message);
      },
    });

  return (
    // An undone step reads as set aside by its dashed border, the page background and muted text, not by
    // opacity, which took its text under 4.5:1 (UI brief §5.7, §8).
    <div className={cn("rounded-[14px] border p-3", latest ? "border-border-strong" : "border-border",
      step.active ? "bg-card" : "border-dashed bg-background")}>
      <div className="flex items-start gap-2">
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label={open ? "Collapse step" : "Expand step"}
          className="mt-0.5 text-muted-foreground hover:text-foreground">
          {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        </button>
        <span className="mt-px font-mono text-[12px] text-muted-foreground">{step.no}</span>
        <div className="min-w-0 flex-1">
          <p className={cn("text-[13.5px] font-medium leading-snug", !step.active && "text-muted-foreground", !step.active && step.kind !== "undo" && "line-through")}>{step.summary}</p>
          <p className="mt-0.5 text-[12px] text-muted-foreground">{detailLine(step)}{!step.active && step.kind !== "undo" ? " · undone" : ""}</p>
        </div>
        {canUndo && (
          <Button size="sm" variant="secondary" className="h-7" loading={undo.isPending && !ask} onClick={() => run(false)}>Undo</Button>
        )}
      </div>
      {open && <StepDetailView datasetId={dataset.id} stepId={step.id} />}
      <Dialog open={!!ask} onOpenChange={(o) => !o && setAsk(null)}>
        <DialogContent className="max-w-[460px] gap-4 p-6">
          <DialogTitle className="text-[17px] font-semibold">Undo step {step.no}?</DialogTitle>
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
    </div>
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
    <div className="mt-3 flex flex-col gap-2 text-[12.5px]">
      {s.kind === "edit" && e ? (
        <ul className="flex flex-col gap-0.5 font-mono">
          {e.edits.slice(0, 50).map((x, i) => <li key={i}>Row {x.row_id} · {x.column} → {displayValue(x.value) || "—"}</li>)}
          {e.new_rows.map((r) => <li key={r.row_id}>Added row {r.row_id}</li>)}
          {e.deleted_row_ids.map((r) => <li key={`d${r}`}>Deleted row {r}</li>)}
          {e.restore_row_ids.map((r) => <li key={`r${r}`}>Restored row {r}</li>)}
          {e.edits.length > 50 && <li className="text-muted-foreground">and {e.edits.length - 50} more</li>}
        </ul>
      ) : s.kind !== "undo" ? (
        <pre className="max-h-[260px] overflow-auto whitespace-pre-wrap rounded-md bg-muted p-2.5 font-mono text-[12px] leading-relaxed">
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
