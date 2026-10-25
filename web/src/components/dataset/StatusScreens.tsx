// Centre screens for a dataset that isn't ready (App Flow §3.3): profiling and failed.
import { AlertCircle, Loader2 } from "lucide-react";
import type { Dataset } from "@/api/types";
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

export function FailedScreen({ dataset }: { dataset: Dataset }) {
  return (
    <div className="mx-auto flex max-w-[420px] flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
      <AlertCircle className="size-6 text-destructive" aria-hidden />
      <h2 className="text-[15px] font-semibold">Profiling failed</h2>
      <p className="text-muted-foreground">
        {dataset.error ? `${dataset.error}. ` : ""}You can delete this CSV and try again.
      </p>
    </div>
  );
}

export function BuildingScreen({ dataset }: { dataset: Dataset }) {
  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col gap-6 px-4 py-10">
      <div className="flex items-center justify-center gap-3" role="status">
        <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden />
        <p className="text-[15px]">Building your dashboard…</p>
      </div>
      <ReportSummary datasetId={dataset.id} />
    </div>
  );
}
