// Centre screens for a dataset that isn't ready (App Flow §3.3): profiling, failed and building.
import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { keys, useJobs, useRetryJob } from "@/api/queries";
import type { Dataset } from "@/api/types";
import { useSettingsOpen } from "@/components/shell/SettingsDialog";
import { Button } from "@/components/ui/button";
import { useUi } from "@/state/ui";
import { ReportSummary } from "./CleaningReport";

export function ProfilingScreen({ dataset }: { dataset: Dataset }) {
  const progress = useUi((s) => s.progress[dataset.id]);
  const label =
    progress?.kind === "profile" && progress.label
      ? `${progress.label}…`
      : `Reading ${dataset.name}…`;
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8" role="status">
      <Loader2 className="size-6 animate-spin text-muted-foreground" aria-hidden />
      <p className="text-[15px]">{label}</p>
    </div>
  );
}

// The job's error is an internal message (a DuckDB error, say), so the screen says what happened in plain
// words and keeps the error behind "Technical details" (UI/UX brief §7). The profile job runs after the file
// was read and checked, so uploading it again fails the same way; Try again retries the job (TRD §4.10).
export function FailedScreen({ dataset }: { dataset: Dataset }) {
  const { data: jobs } = useJobs(dataset.id);
  const retry = useRetryJob();
  const qc = useQueryClient();
  const job = jobs?.find((j) => j.kind === "profile" && (j.status === "failed" || j.status === "cancelled"));
  const cancelled = dataset.error === "Cancelled.";
  return (
    <div className="mx-auto flex max-w-[420px] flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
      <AlertCircle className="size-6 text-destructive" aria-hidden />
      <h2 className="text-[15px] font-semibold">Profiling failed</h2>
      <p className="text-muted-foreground">
        {cancelled
          ? "Profiling was stopped before it finished. Try again to profile this CSV."
          : "Sherlock ran into a problem of its own while profiling this CSV, so uploading it again won't help. Try again, and if it fails again, this file can't be loaded yet."}
      </p>
      {job && (
        <Button
          size="sm"
          disabled={retry.isPending}
          onClick={() =>
            retry.mutate(job.id, {
              onSuccess: () => qc.invalidateQueries({ queryKey: keys.dataset(dataset.id) }),
              onError: (e) => toast.error((e as Error).message),
            })
          }
        >
          Try again
        </Button>
      )}
      {dataset.error && !cancelled && (
        <details className="w-full text-left text-[12.5px] text-muted-foreground">
          <summary className="cursor-pointer select-none text-center">Technical details</summary>
          <code className="mt-2 block whitespace-pre-wrap break-words rounded-md bg-secondary p-2 font-mono text-[12px]">
            {dataset.error}
          </code>
        </details>
      )}
    </div>
  );
}

export function BuildingScreen({ dataset }: { dataset: Dataset }) {
  const { data: jobs } = useJobs(dataset.id);
  const [, , openSettingsAt] = useSettingsOpen();
  // The After upload setting skipped the offer: the screen says why, with a way to change it (App Flow §4).
  const automatic = jobs?.find((j) => j.kind === "build_dashboard")?.automatic;
  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col gap-6 px-4 py-10">
      <div className="flex flex-col items-center gap-2" role="status">
        <div className="flex items-center gap-3">
          <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden />
          <p className="text-[15px]">Building your dashboard…</p>
        </div>
        {automatic && (
          <p className="text-center text-[13px] text-muted-foreground">
            Building without cleaning because After upload is “I'll clean it myself” ·{" "}
            <Button variant="link" size="sm" className="text-[13px]" onClick={() => openSettingsAt("after_upload")}>Change</Button>
          </p>
        )}
      </div>
      {!automatic && <ReportSummary datasetId={dataset.id} />}
    </div>
  );
}
