// The library (left panel, App Flow §2 and §14): your CSVs with live status, Upload, Try with sample.
import { AlertCircle, Check, Settings } from "lucide-react";
import { useRef } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useDatasets, useSample } from "@/api/queries";
import type { Dataset, JobProgressEvent } from "@/api/types";
import { useSettingsOpen } from "@/components/shell/SettingsDialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useUi } from "@/state/ui";

export const ACCEPT = ".csv,.tsv,.txt,text/csv,text/tab-separated-values,text/plain";

export function LibraryPanel() {
  const { data: datasets, isLoading } = useDatasets();
  const { datasetId } = useParams();
  const progress = useUi((s) => s.progress);
  const [, openSettings] = useSettingsOpen();
  return (
    <nav aria-label="Your CSVs" className="flex h-full flex-col gap-3 p-4">
      <div className="flex items-center justify-between">
        <Link to="/" state={{ stay: true }} className="font-serif text-[20px] font-medium leading-none">
          Sherlock
        </Link>
        <button
          type="button"
          aria-label="Settings"
          title="Settings"
          onClick={() => openSettings(true)}
          className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring"
        >
          <Settings className="size-4" strokeWidth={1.75} />
        </button>
      </div>
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Your CSVs</h2>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading ? null : !datasets?.length ? (
          <p className="text-[13px] text-muted-foreground">No CSVs yet.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {datasets.map((d) => (
              <li key={d.id}>
                <LibraryRow dataset={d} active={d.id === datasetId} progress={progress[d.id]} />
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="flex flex-col gap-2">
        <UploadButton className="w-full" label="Upload CSV" />
        <SampleButton className="w-full" label="Try with sample" />
      </div>
    </nav>
  );
}

function LibraryRow({ dataset, active, progress }: { dataset: Dataset; active: boolean; progress?: JobProgressEvent }) {
  return (
    <Link
      to={`/d/${dataset.id}`}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex flex-col gap-0.5 rounded-md border px-2.5 py-2 hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring",
        active ? "border-border-strong bg-secondary" : "border-transparent",
      )}
    >
      <span className="block truncate font-medium">{dataset.name}</span>
      <StatusBadge dataset={dataset} progress={progress} />
    </Link>
  );
}

/** Status line (App Flow §14): profiling · offer · cleaning n% · building · ready · v7 · failed. */
export function StatusBadge({ dataset, progress }: { dataset: Dataset; progress?: JobProgressEvent }) {
  const live = progress && progress.pct < 100 ? progress : undefined;
  const pct = Math.round(live?.pct ?? dataset.cleaning_progress?.pct ?? 0);
  switch (dataset.status) {
    case "ready":
      return (
        <span className="mt-0.5 flex items-center gap-1.5 text-[12px] text-success">
          <Check className="size-3.5" strokeWidth={1.75} aria-hidden /> ready · v{dataset.current_version}
        </span>
      );
    case "failed":
      return (
        <span className="mt-0.5 flex items-center gap-1 text-[12px] text-destructive" title={dataset.error ?? undefined}>
          <AlertCircle className="size-3.5" aria-hidden /> failed
        </span>
      );
    case "cleaning":
    case "building":
      return (
        <span className="mt-0.5 block text-[12px] text-muted-foreground">
          {dataset.status} {dataset.status === "cleaning" ? `${pct}%` : ""}
          <span className="mt-1.5 block h-0.5 rounded bg-border" aria-hidden>
            <span className="block h-0.5 rounded bg-accent" style={{ width: `${pct}%` }} />
          </span>
        </span>
      );
    case "offer":
      return (
        <span className="mt-0.5 block text-[12px] text-muted-foreground">
          offer{dataset.issue_count != null && ` · ${dataset.issue_count} ${dataset.issue_count === 1 ? "issue" : "issues"}`}
        </span>
      );
    default:
      return <span className="mt-0.5 block text-[12px] text-muted-foreground">{dataset.status}</span>;
  }
}

export function UploadButton({ className, label = "Upload" }: { className?: string; label?: string }) {
  const input = useRef<HTMLInputElement>(null);
  const openImport = useUi((s) => s.openImport);
  return (
    <>
      <Button className={className} onClick={() => input.current?.click()}>{label}</Button>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        className="hidden"
        data-testid="file-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) openImport(file);
          e.target.value = "";
        }}
      />
    </>
  );
}

export function SampleButton({ className, label }: { className?: string; label: string }) {
  const sample = useSample();
  const navigate = useNavigate();
  return (
    <Button
      className={className}
      loading={sample.isPending}
      onClick={() =>
        sample.mutate(undefined, {
          onSuccess: (ds) => navigate(`/d/${ds.id}`),
          onError: (err) => toast.error((err as Error).message),
        })
      }
    >
      {label}
    </Button>
  );
}
