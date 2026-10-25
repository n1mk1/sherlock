// The library (left panel, App Flow §2 and §14): your CSVs with live status, Upload, Try with sample.
import { AlertCircle, Check } from "lucide-react";
import { useRef } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useDatasets, useSample } from "@/api/queries";
import type { Dataset, JobProgressEvent } from "@/api/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useUi } from "@/state/ui";

export const ACCEPT = ".csv,.tsv,.txt,text/csv,text/tab-separated-values,text/plain";

export function LibraryPanel() {
  const { data: datasets, isLoading } = useDatasets();
  const { datasetId } = useParams();
  const progress = useUi((s) => s.progress);
  return (
    <nav aria-label="Your CSVs" className="flex h-full flex-col">
      <div className="px-4 pb-2 pt-5">
        <Link to="/" state={{ stay: true }} className="font-serif text-[22px] font-medium leading-none">
          Sherlock
        </Link>
      </div>
      <h2 className="px-4 pb-2 pt-4 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        Your CSVs
      </h2>
      <div className="min-h-0 flex-1 overflow-y-auto px-2">
        {isLoading ? null : !datasets?.length ? (
          <p className="px-2 text-[13px] text-muted-foreground">No CSVs yet.</p>
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
      <div className="flex flex-col gap-2 p-4">
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
        "block rounded-lg border px-3 py-2.5 hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring",
        active ? "border-border-strong bg-secondary" : "border-transparent",
      )}
    >
      <span className="block truncate text-[14px]">{dataset.name}</span>
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
        <span className="mt-0.5 flex items-center gap-1 text-[12px] text-success">
          <Check className="size-3.5" aria-hidden /> ready · v{dataset.current_version}
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
          <span className="mt-1 block h-0.5 rounded bg-border" aria-hidden>
            <span className="block h-0.5 rounded bg-accent" style={{ width: `${pct}%` }} />
          </span>
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
