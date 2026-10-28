// The library (left panel, App Flow §2 and §14): your CSVs with a live status pill, Upload, Try a sample.
import {
  AlertCircle, Check, ChevronsLeft, ChevronsRight, Download, FlaskConical, Loader2, MoreHorizontal, Pencil, Settings, Trash2, Upload,
} from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useDatasets, useSample } from "@/api/queries";
import type { Dataset, JobProgressEvent } from "@/api/types";
import { ConfirmDelete, useDatasetCommands } from "@/components/shell/DatasetMenu";
import { useSettingsOpen } from "@/components/shell/SettingsDialog";
import { Button, IconButton, type ButtonProps } from "@/components/ui/button";
import { MenuContent, MenuItem, MenuRoot, MenuSeparator, MenuTrigger } from "@/components/ui/menu";
import { Dot, Pill, type Tone } from "@/components/ui/pill";
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

/** The collapsed library: each file's initials with its status dot, Upload, Sample, Settings, and » to expand. */
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
    <nav aria-label="Your CSVs" className="hidden h-full flex-col items-center gap-2 py-3 lg:flex">
      <IconButton label="Expand the library" onClick={() => setRailed(false)}><ChevronsRight /></IconButton>
      <ul className="flex min-h-0 flex-1 flex-col items-center gap-1.5 overflow-y-auto py-2">
        {datasets?.map((d) => (
          <li key={d.id}>
            <Link
              to={`/d/${d.id}`}
              title={d.name}
              aria-label={d.name}
              aria-current={d.id === datasetId ? "page" : undefined}
              className={cn(
                "relative inline-flex size-9 items-center justify-center rounded-xl text-[12px] font-semibold uppercase tracking-tight",
                d.id === datasetId
                  ? "bg-card text-foreground shadow-[0_1px_3px_rgba(0,0,0,0.08)] dark:bg-secondary dark:shadow-none"
                  : "text-muted-foreground hover:bg-secondary",
              )}
            >
              {initials(d.name)}
              <Dot tone={statusOf(d).tone} className="absolute right-1 top-1" />
            </Link>
          </li>
        ))}
      </ul>
      <IconButton label="Upload CSV" onClick={() => input.current?.click()}><Upload /></IconButton>
      <input ref={input} type="file" accept={ACCEPT} className="hidden" onChange={(e) => {
        const file = e.target.files?.[0];
        if (file) openImport(file);
        e.target.value = "";
      }} />
      <IconButton label="Try a sample"
        onClick={() => sample.mutate(undefined, { onSuccess: (ds) => navigate(`/d/${ds.id}`), onError: (e) => toast.error((e as Error).message) })}>
        <FlaskConical />
      </IconButton>
      <IconButton label="Settings" onClick={() => openSettings(true)}><Settings strokeWidth={1.75} /></IconButton>
    </nav>
  );
}

export function initials(name: string) {
  const words = name.replace(/\.(csv|tsv|txt)\b.*$/i, "").split(/[^A-Za-z0-9]+/).filter(Boolean);
  return ((words[0]?.[0] ?? "?") + (words[1]?.[0] ?? words[0]?.[1] ?? "")).toUpperCase();
}

/** A file's name as people read it: without the .csv, .tsv or .txt (the full name is in the tooltip). */
export function displayName(name: string) {
  return name.replace(/\.(csv|tsv|txt)(?=$|\s)/i, "");
}

function FullPanel({ className }: { className?: string }) {
  const { data: datasets, isLoading } = useDatasets();
  const { datasetId } = useParams();
  const progress = useUi((s) => s.progress);
  const setRailed = useUi((s) => s.setRailed);
  const [, openSettings] = useSettingsOpen();
  return (
    <nav aria-label="Your CSVs" className={cn("flex h-full flex-col", className)}>
      <div className="flex h-14 shrink-0 items-center justify-between pl-5 pr-2.5">
        <Link to="/" state={{ stay: true }} className="font-serif text-[21px] leading-none tracking-[-0.02em]">
          Sherlock
        </Link>
        <div className="flex items-center">
          <IconButton label="Settings" onClick={() => openSettings(true)}><Settings strokeWidth={1.75} /></IconButton>
          <IconButton label="Collapse the library" className="max-lg:hidden" onClick={() => setRailed(true)}><ChevronsLeft /></IconButton>
        </div>
      </div>
      <h2 className="px-5 pb-2 pt-3 type-label">Library</h2>
      <div className="min-h-0 flex-1 overflow-y-auto px-2.5">
        {isLoading ? null : !datasets?.length ? (
          <p className="px-2.5 text-[13px] text-muted-foreground">No CSVs yet.</p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {datasets.map((d) => (
              <li key={d.id}>
                <LibraryRow dataset={d} active={d.id === datasetId} progress={progress[d.id]} />
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="flex shrink-0 flex-col gap-1 p-3">
        <UploadButton className="w-full" label="Upload CSV" variant="primary" />
        <SampleButton className="w-full" label="Try a sample" variant="ghost" />
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
          className="rounded-xl bg-card px-3 py-2.5 shadow-[0_0_0_1px_var(--accent)]"
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
            className="w-full bg-transparent text-[13.5px] font-medium outline-none"
          />
        </form>
      ) : (
        <Link
          to={`/d/${dataset.id}`}
          aria-current={active ? "page" : undefined}
          title={dataset.name}
          className={cn(
            "flex flex-col gap-1.5 rounded-xl px-3 py-2.5 pr-9 transition-colors duration-[var(--duration-fast)] focus-visible:outline-2 focus-visible:outline-ring",
            active ? "bg-card shadow-[0_1px_3px_rgba(0,0,0,0.07)] dark:bg-secondary dark:shadow-none" : "hover:bg-secondary",
          )}
        >
          <span className="block truncate text-[13.5px] font-medium tracking-[-0.01em]">{displayName(dataset.name)}</span>
          <StatusBadge dataset={dataset} progress={progress} />
        </Link>
      )}
      {!renaming && (
        <MenuRoot>
          <MenuTrigger asChild>
            <IconButton
              label={`Menu for ${dataset.name}`}
              className="absolute right-1.5 top-2 size-7 opacity-0 focus-visible:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100"
            >
              <MoreHorizontal />
            </IconButton>
          </MenuTrigger>
          <MenuContent>
            <MenuItem onSelect={() => setRenaming(true)}><Pencil /> Rename</MenuItem>
            <MenuItem onSelect={cmd.downloadRaw}><Download /> Download original</MenuItem>
            <MenuSeparator />
            <MenuItem destructive onSelect={() => setDeleting(true)}><Trash2 /> Delete</MenuItem>
          </MenuContent>
        </MenuRoot>
      )}
      <ConfirmDelete dataset={dataset} open={deleting} onOpenChange={setDeleting} onConfirm={() => cmd.remove(active)} />
    </div>
  );
}

/** A file's status in words and a hue: reading, its issues to look at, cleaning, ready, failed. */
export function statusOf(dataset: Dataset, pct = 0): { label: string; tone: Tone } {
  switch (dataset.status) {
    case "ready": return { label: "Ready", tone: "green" };
    case "failed": return { label: "Failed", tone: "red" };
    case "cleaning": return { label: `Cleaning ${pct}%`, tone: "violet" };
    case "profiling": return { label: "Reading", tone: "blue" };
    case "offer": {
      const n = dataset.issue_count;
      if (n == null) return { label: "To review", tone: "amber" };
      if (n === 0) return { label: "Looks clean", tone: "green" };
      return { label: `${n.toLocaleString()} ${n === 1 ? "issue" : "issues"}`, tone: "amber" };
    }
    default: return { label: dataset.status, tone: "neutral" };
  }
}

/** The row's status pill and row count; while cleaning, a thin progress line under it. */
export function StatusBadge({ dataset, progress }: { dataset: Dataset; progress?: JobProgressEvent }) {
  const live = progress && progress.pct < 100 ? progress : undefined;
  const pct = Math.round(live?.pct ?? dataset.cleaning_progress?.pct ?? 0);
  const { label, tone } = statusOf(dataset, pct);
  const icon = dataset.status === "ready" ? <Check strokeWidth={2.5} aria-hidden />
    : dataset.status === "failed" ? <AlertCircle aria-hidden />
    : dataset.status === "profiling" ? <Loader2 className="animate-spin" aria-hidden /> : null;
  return (
    <span className="flex min-w-0 flex-col gap-1.5" title={dataset.status === "failed" ? dataset.error ?? undefined : undefined}>
      <span className="flex min-w-0 items-center gap-2">
        <Pill tone={tone} size="sm" icon={icon}>{label}</Pill>
        {dataset.row_count != null && dataset.status !== "cleaning" && (
          <span className="truncate text-[11.5px] text-muted-foreground tnum">{dataset.row_count.toLocaleString()} rows</span>
        )}
      </span>
      {dataset.status === "cleaning" && (
        <span className="block h-0.5 overflow-hidden rounded-full bg-secondary" aria-hidden>
          <span className="block h-full rounded-full bg-violet transition-[width] duration-[var(--duration-base)]" style={{ width: `${pct}%` }} />
        </span>
      )}
    </span>
  );
}

export function UploadButton({ className, label = "Upload", variant }: {
  className?: string; label?: string; variant?: ButtonProps["variant"];
}) {
  const input = useRef<HTMLInputElement>(null);
  const openImport = useUi((s) => s.openImport);
  return (
    <>
      <Button className={className} variant={variant} onClick={() => input.current?.click()}>{label}</Button>
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

export function SampleButton({ className, label, variant }: { className?: string; label: string; variant?: ButtonProps["variant"] }) {
  const sample = useSample();
  const navigate = useNavigate();
  return (
    <Button
      className={className}
      variant={variant}
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
