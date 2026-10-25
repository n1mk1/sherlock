// The library (left panel, App Flow §2 and §14): your CSVs with live status, Upload, Try with sample.
import {
  AlertCircle, Check, ChevronsLeft, ChevronsRight, Download, FlaskConical, MoreHorizontal, Pencil, Settings, Trash2, Upload,
} from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useDatasets, useSample } from "@/api/queries";
import type { Dataset, JobProgressEvent } from "@/api/types";
import { ConfirmDelete, useDatasetCommands } from "@/components/shell/DatasetMenu";
import { useSettingsOpen } from "@/components/shell/SettingsDialog";
import { Button } from "@/components/ui/button";
import { MenuContent, MenuItem, MenuRoot, MenuSeparator, MenuTrigger } from "@/components/ui/menu";
import { cn } from "@/lib/utils";
import { useUi } from "@/state/ui";

export const ACCEPT = ".csv,.tsv,.txt,text/csv,text/tab-separated-values,text/plain";

export function LibraryPanel() {
  const railed = useUi((s) => s.railed);
  return (
    <>
      {railed && <Rail />}
      <FullPanel className={cn(railed && "lg:hidden")} />
    </>
  );
}

const iconBtn =
  "inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring";

/** The collapsed library (App Flow §14): dataset initials, Upload, Sample, the gear, and » to expand. */
function Rail() {
  const { data: datasets } = useDatasets();
  const { datasetId } = useParams();
  const setRailed = useUi((s) => s.setRailed);
  const openImport = useUi((s) => s.openImport);
  const [, openSettings] = useSettingsOpen();
  const sample = useSample();
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  return (
    <nav aria-label="Your CSVs" className="hidden h-full flex-col items-center gap-2 py-4 lg:flex">
      <button type="button" aria-label="Expand the library" title="Expand" onClick={() => setRailed(false)} className={iconBtn}>
        <ChevronsRight className="size-4" />
      </button>
      <ul className="flex min-h-0 flex-1 flex-col items-center gap-1.5 overflow-y-auto">
        {datasets?.map((d) => (
          <li key={d.id}>
            <Link
              to={`/d/${d.id}`}
              title={d.name}
              aria-label={d.name}
              aria-current={d.id === datasetId ? "page" : undefined}
              className={cn(
                "inline-flex size-9 items-center justify-center rounded-md border font-mono text-[12px] uppercase",
                d.id === datasetId ? "border-border-strong bg-secondary" : "border-transparent hover:bg-secondary",
              )}
            >
              {initials(d.name)}
            </Link>
          </li>
        ))}
      </ul>
      <button type="button" aria-label="Upload CSV" title="Upload CSV" onClick={() => input.current?.click()} className={iconBtn}>
        <Upload className="size-4" />
      </button>
      <input ref={input} type="file" accept={ACCEPT} className="hidden" onChange={(e) => {
        const file = e.target.files?.[0];
        if (file) openImport(file);
        e.target.value = "";
      }} />
      <button type="button" aria-label="Try with sample" title="Try with sample" className={iconBtn}
        onClick={() => sample.mutate(undefined, { onSuccess: (ds) => navigate(`/d/${ds.id}`), onError: (e) => toast.error((e as Error).message) })}>
        <FlaskConical className="size-4" />
      </button>
      <button type="button" aria-label="Settings" title="Settings" onClick={() => openSettings(true)} className={iconBtn}>
        <Settings className="size-4" strokeWidth={1.75} />
      </button>
    </nav>
  );
}

export function initials(name: string) {
  const words = name.replace(/\.(csv|tsv|txt)\b.*$/i, "").split(/[^A-Za-z0-9]+/).filter(Boolean);
  return ((words[0]?.[0] ?? "?") + (words[1]?.[0] ?? words[0]?.[1] ?? "")).toUpperCase();
}

function FullPanel({ className }: { className?: string }) {
  const { data: datasets, isLoading } = useDatasets();
  const { datasetId } = useParams();
  const progress = useUi((s) => s.progress);
  const setRailed = useUi((s) => s.setRailed);
  const [, openSettings] = useSettingsOpen();
  return (
    <nav aria-label="Your CSVs" className={cn("flex h-full flex-col gap-3 p-4", className)}>
      <div className="flex items-center justify-between">
        <Link to="/" state={{ stay: true }} className="font-serif text-[20px] font-medium leading-none">
          Sherlock
        </Link>
        <div className="flex items-center">
          <button type="button" aria-label="Settings" title="Settings" onClick={() => openSettings(true)} className={iconBtn}>
            <Settings className="size-4" strokeWidth={1.75} />
          </button>
          <button type="button" aria-label="Collapse the library" title="Collapse" onClick={() => setRailed(true)}
            className={cn(iconBtn, "max-lg:hidden")}>
            <ChevronsLeft className="size-4" />
          </button>
        </div>
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
  const cmd = useDatasetCommands(dataset);
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  return (
    <div className="group relative">
      {renaming ? (
        <form
          className="rounded-md border border-border-strong px-2.5 py-2"
          onSubmit={(e) => {
            e.preventDefault();
            cmd.rename(new FormData(e.currentTarget).get("name") as string);
            setRenaming(false);
          }}
        >
          <input
            name="name"
            autoFocus
            defaultValue={dataset.name}
            aria-label="New name"
            onBlur={(e) => { cmd.rename(e.target.value); setRenaming(false); }}
            onKeyDown={(e) => e.key === "Escape" && setRenaming(false)}
            className="w-full bg-transparent font-medium outline-none"
          />
        </form>
      ) : (
        <Link
          to={`/d/${dataset.id}`}
          aria-current={active ? "page" : undefined}
          className={cn(
            "flex flex-col gap-0.5 rounded-md border px-2.5 py-2 pr-8 hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring",
            active ? "border-border-strong bg-secondary" : "border-transparent",
          )}
        >
          <span className="block truncate font-medium">{dataset.name}</span>
          <StatusBadge dataset={dataset} progress={progress} />
        </Link>
      )}
      {!renaming && (
        <MenuRoot>
          <MenuTrigger asChild>
            <button
              type="button"
              aria-label={`Menu for ${dataset.name}`}
              className="absolute right-1 top-1.5 inline-flex size-7 items-center justify-center rounded-md text-muted-foreground opacity-0 hover:bg-muted focus-visible:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100"
            >
              <MoreHorizontal className="size-4" />
            </button>
          </MenuTrigger>
          <MenuContent>
            <MenuItem onSelect={() => setRenaming(true)}><Pencil /> Rename</MenuItem>
            <MenuItem onSelect={cmd.downloadRaw}><Download /> Download original CSV</MenuItem>
            <MenuSeparator />
            <MenuItem destructive onSelect={() => setDeleting(true)}><Trash2 /> Delete</MenuItem>
          </MenuContent>
        </MenuRoot>
      )}
      <ConfirmDelete dataset={dataset} open={deleting} onOpenChange={setDeleting} onConfirm={() => cmd.remove(active)} />
    </div>
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
