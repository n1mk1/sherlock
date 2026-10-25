// Cleaning in progress (App Flow §5, UI brief §5.4): the live log from the dataset's event stream,
// "So far" counts, the checks on the latest step, the budget line, and Stop.
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
    <div className="mx-auto w-full max-w-[1100px] px-6 py-8">
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
      <div className="mt-5 flex justify-between text-[13px] text-muted-foreground">
        <span>{progress?.label || "Starting…"}</span>
        <span className="font-mono">{mmss(elapsed)}</span>
      </div>
      <div className="mt-1.5 h-1 rounded bg-border" role="progressbar" aria-valuenow={Math.round(progress?.pct ?? 0)} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-1 rounded bg-accent transition-[width] duration-[var(--duration-base)]" style={{ width: `${progress?.pct ?? 2}%` }} />
      </div>

      <div className="mt-6 grid gap-5 @3xl:grid-cols-[2fr_1fr]">
        <ol
          ref={listRef}
          aria-label="Cleaning log"
          aria-live="polite"
          onScroll={(e) => {
            const el = e.currentTarget;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
          }}
          className="max-h-[60vh] overflow-y-auto rounded-2xl border border-border bg-card px-5"
        >
          {log.length === 0 && <li className="py-5 text-muted-foreground">Waiting for the first step…</li>}
          {log.map((e, i) => (
            <LogEntry key={i} entry={e} started={started} />
          ))}
        </ol>
        <aside className="flex flex-col gap-5">
          <section className="rounded-2xl border border-border bg-card p-5">
            <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">So far</h3>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <Stat value={report?.counts.found ?? 0} label="issues found" />
              <Stat value={report?.counts.fixed ?? 0} label="fixed" />
              <Stat value={report?.counts.flagged ?? 0} label="flagged" />
              <Stat value={0} label="rows deleted" />
            </div>
          </section>
          <section className="rounded-2xl border border-border bg-card p-5">
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
          <p className="rounded-2xl border border-dashed border-border-strong p-5 text-muted-foreground">
            When cleaning finishes, the dashboard builds itself.
          </p>
        </aside>
      </div>
    </div>
  );
}

/** A "running" line is replaced by its outcome for the same issue. */
export function collapse(entries: JobLogEntry[]): JobLogEntry[] {
  const out: JobLogEntry[] = [];
  for (const e of entries) {
    const prev = out[out.length - 1];
    if (prev && prev.icon === "running" && e.icon !== "running" && e.icon !== "wait" && prev.issue_id && prev.issue_id === e.issue_id) {
      out[out.length - 1] = { ...e, text: prev.text, outcome: e.text };
    } else {
      out.push(e);
    }
  }
  return out;
}

function LogEntry({ entry, started }: { entry: JobLogEntry; started: number | null }) {
  const t = started ? (Date.parse(entry.ts) - started) / 1000 : 0;
  const gate = entry.gate;
  const tone =
    gate === "commit" ? "text-success" : gate === "flag" ? "text-warning" : entry.icon === "running" ? "text-accent" : "text-muted-foreground";
  return (
    <li className="grid grid-cols-[52px_24px_1fr] gap-x-2 border-b border-border py-4 last:border-b-0">
      <span className="font-mono text-[12.5px] text-muted-foreground">{mmss(t)}</span>
      <Icon entry={entry} />
      <div className="min-w-0">
        <p>
          {entry.column && <span className="font-mono text-[13px]">{entry.column} · </span>}
          {entry.text}
        </p>
        {entry.outcome && <p className="mt-1 text-[13px] text-foreground-2">{entry.outcome}</p>}
        {entry.candidates && entry.candidates.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {entry.candidates.map((c) => (
              <span
                key={c.label}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-[12px]",
                  c.chosen ? "border-primary bg-primary text-primary-foreground" : "border-border-strong text-foreground-2",
                )}
              >
                {c.label}
              </span>
            ))}
          </div>
        )}
        {entry.detail && <p className={cn("mt-1.5 text-[13px]", tone)}>{entry.detail}</p>}
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
    <div className="rounded-xl bg-muted p-3">
      <div className="font-serif text-[28px] leading-none">{value.toLocaleString()}</div>
      <div className="mt-1.5 text-[12px] text-muted-foreground">{label}</div>
    </div>
  );
}
