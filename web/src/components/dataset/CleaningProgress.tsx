// Cleaning in progress (App Flow §5, UI brief §5.4): the live log from the dataset's event stream,
// "So far" counts, the checks on the latest step, the budget line, and Stop. A step's line is built in
// code from its verifier report; the model's own sentence (`note`, never with digits) and the issue's
// model calls (`calls`) sit under it.
import { useQueryClient } from "@tanstack/react-query";
import { Check, CircleDot, Clock, Flag, Redo2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { keys, useCancelJob, useJobs, useReport } from "@/api/queries";
import { useEventStream } from "@/api/sse";
import type { Dataset, JobLogEntry, JobProgressEvent } from "@/api/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const CHECK_LABELS: Record<string, string> = {
  row_ledger: "Row count unchanged",
  nan_introduced: "No new blanks",
  dtype: "Types make sense",
  pandera: "Data-card constraints (pandera)",
  parse_quarantine: "Parse failures quarantined",
  placeholder_fill: "No placeholder fills",
  quarantine_scope: "Quarantine fits the issue",
  lossless: "Lossless round-trip",
};

export function mmss(seconds: number) {
  const s = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export function CleaningProgress({ dataset }: { dataset: Dataset }) {
  const qc = useQueryClient();
  const { data: jobs } = useJobs(dataset.id);
  const job = jobs?.find((j) => j.kind === "clean");
  const { data: report } = useReport(dataset.id, job?.id, !!job);
  const cancel = useCancelJob(dataset.id);
  const [entries, setEntries] = useState<JobLogEntry[]>([]);
  const [progress, setProgress] = useState<JobProgressEvent | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => setEntries([]), [job?.id]);

  // Replay the dataset's events from the start, keeping this job's log lines.
  useEventStream(
    job ? `/api/v1/datasets/${dataset.id}/events` : null,
    {
      "job.log": (data) => {
        const e = data as JobLogEntry;
        if (e.job_id !== job?.id) return;
        setEntries((list) => [...list, e]);
        qc.invalidateQueries({ queryKey: keys.report(dataset.id, job?.id) });
        if (e.step_id) qc.invalidateQueries({ queryKey: keys.dataset(dataset.id) }); // a new version: the header's pill
      },
      "job.progress": (data) => {
        const p = data as JobProgressEvent;
        if (p.job_id === job?.id) setProgress(p);
      },
    },
    0,
  );

  const log = useMemo(() => collapse(entries), [entries]);
  const started = job?.started_at ? Date.parse(job.started_at) : null;
  const elapsed = started ? (now - started) / 1000 : 0;
  const latestChecks = [...entries].reverse().find((e) => e.checks)?.checks;
  const maxSteps = report?.budget.max_steps ?? 20;
  const maxSeconds = report?.budget.max_seconds ?? 300;

  const listRef = useRef<HTMLOListElement>(null);
  const stick = useRef(true);
  useEffect(() => {
    const el = listRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [log.length]);

  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-5 px-6 py-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-serif text-[26px] leading-tight @3xl:text-[32px]">Cleaning {dataset.name}</h2>
          <p className="text-muted-foreground">Running on its own. You can switch CSVs; it keeps going.</p>
        </div>
        <Button
          loading={cancel.isPending}
          disabled={!job || job.status !== "running"}
          onClick={() => job && cancel.mutate(job.id, { onError: (e) => toast.error((e as Error).message) })}
        >
          Stop
        </Button>
      </div>
      <div className="-mb-3.5 flex justify-between text-[12px] text-muted-foreground">
        <span>{progress?.label || "Starting…"}</span>
        <span className="font-mono">{mmss(elapsed)}</span>
      </div>
      <div className="h-1 rounded bg-border" role="progressbar" aria-valuenow={Math.round(progress?.pct ?? 0)} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-1 rounded bg-accent transition-[width] duration-[var(--duration-base)]" style={{ width: `${progress?.pct ?? 2}%` }} />
      </div>

      <div className="grid items-start gap-4 @3xl:grid-cols-[2fr_1fr]">
        <ol
          ref={listRef}
          aria-label="Cleaning log"
          aria-live="polite"
          onScroll={(e) => {
            const el = e.currentTarget;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
          }}
          className="max-h-[60vh] overflow-y-auto rounded-2xl border border-border bg-card px-4 py-2"
        >
          {log.length === 0 && <li className="py-5 text-muted-foreground">Waiting for the first step…</li>}
          {log.map((e, i) => (
            <LogEntry key={i} entry={e} started={started} />
          ))}
        </ol>
        <aside className="flex flex-col gap-4">
          <section className="rounded-2xl border border-border bg-card px-[22px] py-5">
            <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">So far</h3>
            <div className="mt-2.5 grid grid-cols-2 gap-2.5">
              <Stat value={report?.counts.found ?? 0} label="issues found" />
              <Stat value={report?.counts.fixed ?? 0} label="fixed" />
              <Stat value={report?.counts.flagged ?? 0} label="flagged" />
              <Stat value={0} label="rows deleted" />
            </div>
          </section>
          <section className="rounded-2xl border border-border bg-card px-[22px] py-5">
            <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Checks on the latest step</h3>
            <ul className="mt-3 flex flex-col gap-1.5">
              {latestChecks ? (
                Object.entries(latestChecks).map(([k, v]) => (
                  <li key={k} className="flex items-center gap-2">
                    {v === "pass" ? <Check className="size-4 text-success" aria-label="passed" /> : <X className="size-4 text-destructive" aria-label="failed" />}
                    {CHECK_LABELS[k] ?? k}
                  </li>
                ))
              ) : (
                <li className="text-muted-foreground">No step checked yet.</li>
              )}
            </ul>
            <p className="mt-4 border-t border-border pt-3 font-mono text-[12.5px] text-muted-foreground">
              {report?.attempted ?? 0} of {maxSteps} issues tried · {mmss(elapsed)} of {mmss(maxSeconds)}
            </p>
          </section>
          <p className="rounded-2xl border border-dashed border-border-strong px-[22px] py-5 text-[13px] text-muted-foreground">
            When cleaning finishes, the dashboard builds itself.
          </p>
        </aside>
      </div>
    </div>
  );
}

/** A "running" line is replaced by its outcome for the same issue, also when "Waiting for the
 * model…" lines came in between (those stay, after it). */
export function collapse(entries: JobLogEntry[]): JobLogEntry[] {
  const out: JobLogEntry[] = [];
  for (const e of entries) {
    let i = out.length - 1;
    while (i >= 0 && out[i].icon === "wait") i--;
    const prev = out[i];
    if (prev && prev.icon === "running" && e.icon !== "running" && e.icon !== "wait" && prev.issue_id && prev.issue_id === e.issue_id) {
      out[i] = { ...e, text: prev.text, outcome: e.text };
    } else {
      out.push(e);
    }
  }
  return out;
}

/** "4 model calls · Nemotron-3-Ultra-550b-a55b · 12.3 s": the issue's calls from `llm_calls`. */
export function callsLine(calls: NonNullable<JobLogEntry["calls"]>) {
  const models = calls.models.map((m) => m.replace(/^nvidia\//i, "")).join(", ");
  const n = calls.count === 1 ? "1 model call" : `${calls.count} model calls`;
  return `${n} · ${models} · ${(calls.latency_ms / 1000).toFixed(1)} s`;
}

export function LogEntry({ entry, started }: { entry: JobLogEntry; started: number | null }) {
  const t = started ? (Date.parse(entry.ts) - started) / 1000 : 0;
  const gate = entry.gate;
  const tone =
    gate === "commit" ? "text-success" : gate === "flag" ? "text-warning" : entry.icon === "running" ? "text-accent" : "text-muted-foreground";
  return (
    <li className="grid grid-cols-[56px_24px_minmax(0,1fr)] gap-x-2.5 border-b border-border py-3 last:border-b-0">
      <span className="font-mono text-[12.5px] text-muted-foreground">{mmss(t)}</span>
      <Icon entry={entry} />
      <div className="min-w-0">
        <p>
          {entry.column && <span className="font-mono text-[12.5px]">{entry.column}</span>}
          <span className="text-foreground-2">{entry.column ? " · " : ""}{entry.text}</span>
        </p>
        {entry.outcome && <p className="mt-1 text-[13px] text-foreground-2">{entry.outcome}</p>}
        {entry.note && <p className="mt-0.5 text-[12.5px] text-muted-foreground">{entry.note}</p>}
        {entry.candidates && entry.candidates.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {entry.candidates.map((c) => (
              <span
                key={c.label}
                className={cn(
                  "inline-flex h-6 items-center rounded-full border px-2 text-[12px]",
                  c.chosen ? "border-primary bg-primary text-primary-foreground" : "border-border-strong text-foreground-2",
                )}
              >
                {c.label}
              </span>
            ))}
          </div>
        )}
        {entry.detail && <p className={cn("mt-1.5 text-[12px]", tone)}>{entry.detail}</p>}
        {entry.calls && <p className="mt-0.5 font-mono text-[11.5px] text-muted-foreground">{callsLine(entry.calls)}</p>}
      </div>
    </li>
  );
}

function Icon({ entry }: { entry: JobLogEntry }) {
  const cls = "mt-0.5 size-4";
  if (entry.icon === "check") return <Check className={cn(cls, "text-success")} aria-label="committed" />;
  if (entry.icon === "flag") return <Flag className={cn(cls, "text-warning")} aria-label="flagged" />;
  if (entry.icon === "skip") return <Redo2 className={cn(cls, "text-muted-foreground")} aria-label="skipped" />;
  if (entry.icon === "wait") return <Clock className={cn(cls, "text-warning")} aria-label="waiting" />;
  if (entry.icon === "error") return <X className={cn(cls, "text-destructive")} aria-label="error" />;
  return <CircleDot className={cn(cls, "text-accent")} aria-label="running" />;
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div className="rounded-md bg-muted p-2.5">
      <div className="font-mono text-[24px] leading-tight">{value.toLocaleString()}</div>
      <div className="text-[12px] text-muted-foreground">{label}</div>
    </div>
  );
}
