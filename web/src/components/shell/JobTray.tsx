// The jobs tray (App Flow §15, UI/UX brief §5.15): a ghost icon in the centre header with a count of
// running jobs. Its popover lists jobs with progress and Cancel; finished jobs stay for a minute,
// failed ones until dismissed, with Retry.
import * as Popover from "@radix-ui/react-popover";
import { Activity, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useAllJobs, useCancelJob, useDatasets, useRetryJob } from "@/api/queries";
import type { Job } from "@/api/types";
import { Button } from "@/components/ui/button";

const LABEL: Record<string, string> = {
  profile: "Profiling", clean: "Cleaning", build_dashboard: "Building the dashboard", stories: "Writing stories",
  ml_run: "Analysis", cascade: "Updating", undo: "Undoing", export_notebook: "Exporting a notebook", purge: "Cleaning up",
};
const RECENT_MS = 60_000;

export function visibleJobs(jobs: Job[], dismissed: Set<string>, now = Date.now()) {
  return jobs.filter((j) => {
    if (j.status === "queued" || j.status === "running") return true;
    if (j.status === "failed") return !dismissed.has(j.id);
    return !!j.finished_at && now - Date.parse(j.finished_at) < RECENT_MS; // done or cancelled: one minute
  });
}

export function JobTray() {
  const { data: jobs } = useAllJobs();
  const { data: datasets } = useDatasets();
  const cancel = useCancelJob();
  const retry = useRetryJob();
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const shown = visibleJobs(jobs ?? [], dismissed);
  const running = shown.filter((j) => j.status === "running" || j.status === "queued").length;
  const name = (id: string | null) => datasets?.find((d) => d.id === id)?.name ?? "";
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          aria-label={`Background jobs (${running} running)`}
          className="relative inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring"
        >
          <Activity className="size-4" strokeWidth={1.75} />
          {running > 0 && (
            <span className="absolute -right-0.5 -top-0.5 inline-flex min-w-4 items-center justify-center rounded-full bg-accent px-1 font-mono text-[10px] text-accent-foreground">
              {running}
            </span>
          )}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="end" sideOffset={6} className="z-50 w-[320px] rounded-lg border border-border bg-popover p-2 text-[13px] shadow-[var(--shadow-overlay)]">
          {shown.length === 0 ? (
            <p className="px-2 py-3 text-muted-foreground">No background jobs right now.</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {shown.map((j) => (
                <li key={j.id} className="flex flex-col gap-1.5 rounded-md px-2 py-2">
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate">
                      <span className="font-medium">{LABEL[j.kind] ?? j.kind}</span>
                      <span className="text-muted-foreground"> · {name(j.dataset_id)}</span>
                    </span>
                    {(j.status === "running" || j.status === "queued") && (
                      <Button size="sm" variant="ghost" onClick={() => cancel.mutate(j.id)}>Cancel</Button>
                    )}
                    {j.status === "failed" && (
                      <>
                        <Button size="sm" variant="ghost" onClick={() => retry.mutate(j.id, { onError: (e) => toast.error((e as Error).message) })}>
                          Retry
                        </Button>
                        <button type="button" aria-label="Dismiss" onClick={() => setDismissed((d) => new Set(d).add(j.id))}
                          className="inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-secondary">
                          <X className="size-3.5" />
                        </button>
                      </>
                    )}
                  </div>
                  {j.status === "failed" ? (
                    <span className="text-[12px] text-destructive">{j.error}</span>
                  ) : j.status === "done" || j.status === "cancelled" ? (
                    <span className={j.status === "done" ? "text-[12px] text-success" : "text-[12px] text-muted-foreground"}>
                      {j.status === "done" ? "Done" : "Cancelled"}
                    </span>
                  ) : (
                    <>
                      <span className="text-[12px] text-muted-foreground">{j.progress.label || (j.status === "queued" ? "Waiting to start" : "Working")}</span>
                      <span className="block h-0.5 rounded bg-border" aria-hidden>
                        <span className="block h-0.5 rounded bg-accent" style={{ width: `${Math.round(j.progress.pct)}%` }} />
                      </span>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
