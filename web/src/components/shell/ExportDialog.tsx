// Export notebook (App Flow §17, UI/UX brief §5.13): the options (remembered per user), one sentence
// naming what will be rebuilt, notes for a running job or unsaved edits, then a job with a progress
// toast that downloads the notebook (and the raw CSV when "Include data" is on) when it's ready.
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { request } from "@/api/client";
import type { Dataset } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { pendingCount, useEdits } from "@/state/edits";
import { useUi } from "@/state/ui";

interface Options {
  include_data: boolean;
  include_runs: boolean;
}
interface Preview {
  version: number;
  notes: string[];
  counts: { steps: number; runs: number };
  options: Options;
}
interface ExportState {
  export_id: string;
  status: string;
  cached: boolean;
  download_url?: string;
  error?: string | null;
}

export const exportBlocked = (d: Dataset) =>
  d.status === "profiling" ? "Available once the CSV is profiled" : d.status === "failed" ? "This CSV failed to load" : null;

function download(url: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/** Start the export, follow it with a toast, and download the file(s) when it's done. */
export async function runExport(dataset: Dataset, options: Options) {
  const id = toast.loading("Preparing notebook…");
  try {
    let state = await request<ExportState>("POST", `/api/v1/datasets/${dataset.id}/exports/notebook`, options);
    const started = Date.now();
    while (state.status !== "done" && state.status !== "failed" && Date.now() - started < 120_000) {
      await new Promise((r) => setTimeout(r, 600));
      state = await request<ExportState>("GET", `/api/v1/exports/${state.export_id}`);
    }
    if (state.status !== "done" || !state.download_url) throw new Error(state.error ?? "The export didn't finish.");
    const files = () => {
      download(state.download_url!);
      if (options.include_data) setTimeout(() => download(`/api/v1/datasets/${dataset.id}/raw.csv`), 400);
    };
    files();
    toast.success("Notebook ready", { id, duration: 60_000, action: { label: "Download again", onClick: files } });
  } catch (e) {
    toast.error((e as Error).message, { id });
  }
}

export function ExportDialog({ dataset }: { dataset: Dataset }) {
  const open = useUi((s) => s.exportOpen);
  const setOpen = useUi((s) => s.setExportOpen);
  const [params, setParams] = useSearchParams();
  const pending = pendingCount(useEdits((s) => s.buffers[dataset.id]));
  const [options, setOptions] = useState<Options | null>(null);
  const preset = useUi((s) => s.exportPreset);
  const blocked = exportBlocked(dataset);

  // Ctrl+Shift+E anywhere on the dataset, and the ?export=notebook deep link (App Flow §17.1).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "e") {
        e.preventDefault();
        if (!blocked) setOpen(true);
      }
    };
    // Capture phase: the CSV grid stops the keys it handles from bubbling, and it usually has focus there.
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [blocked, setOpen]);
  useEffect(() => {
    if (params.get("export") === "notebook" && !blocked) {
      setOpen(true);
      params.delete("export");
      setParams(params, { replace: true });
    }
  }, [params, setParams, blocked, setOpen]);

  const preview = useQuery({
    queryKey: ["export-preview", dataset.id, dataset.current_version, options],
    enabled: open && !blocked,
    placeholderData: (prev) => prev,
    queryFn: () => {
      // Unset options (the preview answers `up_to_step: null`) are left out: "null" isn't a number, so it was a 422.
      const set = options ? Object.entries(options).filter(([, v]) => v !== null && v !== undefined) : [];
      const q = set.length ? `?${new URLSearchParams(set.map(([k, v]) => [k, String(v)]))}` : "";
      return request<Preview>("GET", `/api/v1/datasets/${dataset.id}/exports/notebook/preview${q}`);
    },
  });
  useEffect(() => {
    // The remembered options, with what chat asked for on top ("export a notebook without the data").
    if (open && preview.data && !options) setOptions({ ...preview.data.options, ...(preset ?? {}) });
  }, [open, preview.data, options, preset]);
  useEffect(() => {
    if (!open) {
      setOptions(null);
      if (preset) useUi.setState({ exportPreset: null });
    }
  }, [open, preset]);

  const o = options ?? preview.data?.options;
  const c = preview.data?.counts;
  const set = (k: keyof Options, v: boolean) => o && setOptions({ ...o, [k]: v });
  const start = () => {
    if (!o) return;
    setOpen(false);
    runExport(dataset, o);
  };
  const busy = dataset.status === "cleaning";
  // The server's notes (TRD §4.2 preview), less its running-job note: the dialog words that one itself.
  const notes = (preview.data?.notes ?? []).filter((n) => !n.startsWith("A job was still running"));

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-[520px] gap-4 p-6">
        <DialogTitle className="font-serif text-[22px] font-semibold">Export notebook</DialogTitle>
        <DialogDescription className="text-[14px] text-muted-foreground">
          A runnable Jupyter notebook that rebuilds <strong className="text-foreground">{dataset.name} v{preview.data?.version ?? dataset.current_version}</strong>{" "}
          from the raw file{c ? (
            <>: <span className="font-mono">{c.steps}</span> {c.steps === 1 ? "step" : "steps"} and{" "}
              <span className="font-mono">{c.runs}</span> model {c.runs === 1 ? "run" : "runs"}.</>
          ) : "."}
        </DialogDescription>
        {o && (
          <div className="flex flex-col gap-3">
            <Check label="Include data" help="The raw CSV downloads next to the notebook." checked={o.include_data} onChange={(v) => set("include_data", v)} />
            <Check label="Include ML runs" help="Each run's reproduction code and its tables." checked={o.include_runs} onChange={(v) => set("include_runs", v)} />
          </div>
        )}
        {(busy || pending > 0 || notes.length > 0) && (
          <div className="flex gap-2.5 rounded-md bg-muted p-3 text-[13px]">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
            <div className="flex flex-col gap-2">
              {busy && <p>A job is still running. This export uses v{dataset.current_version}, the latest committed version.</p>}
              {pending > 0 && <p>You have {pending} unsaved {pending === 1 ? "edit" : "edits"}. They are not included; save first to include them.</p>}
              {notes.map((n) => <p key={n}>{n}</p>)}
            </div>
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="primary" disabled={!o || !!blocked} onClick={start}>Export</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Check({ label, help, checked, onChange }: { label: string; help: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-start gap-2.5">
      <input type="checkbox" className="mt-1 size-4 accent-[var(--accent)]" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="flex flex-col">
        <span className="text-[14px]">{label}</span>
        <span className="text-[13px] text-muted-foreground">{help}</span>
      </span>
    </label>
  );
}
