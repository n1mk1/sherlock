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
import { Segmented } from "@/components/ui/segmented";
import { pendingCount, useEdits } from "@/state/edits";
import { useUi } from "@/state/ui";

interface Options {
  include_data: boolean;
  include_cards: boolean;
  include_notes: boolean;
  include_runs: boolean;
  order: "steps_dashboard" | "flow_path";
}
interface Preview {
  version: number;
  notes: string[];
  counts: { steps: number; widgets: number; runs: number; cards: number; notes?: number };
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

  // Ctrl+Shift+E from any tab, and the ?export=notebook deep link (App Flow §17.1).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "e") {
        e.preventDefault();
        if (!blocked) setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
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
      const q = options ? `?${new URLSearchParams(Object.entries(options).map(([k, v]) => [k, String(v)]))}` : "";
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
  const set = (k: keyof Options, v: boolean | string) => o && setOptions({ ...o, [k]: v } as Options);
  const start = () => {
    if (!o) return;
    setOpen(false);
    runExport(dataset, o);
  };
  const busy = dataset.status === "cleaning" || dataset.status === "building";

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-[520px] gap-4 p-6">
        <DialogTitle className="font-serif text-[22px] font-semibold">Export notebook</DialogTitle>
        <DialogDescription className="text-[14px] text-muted-foreground">
          A runnable Jupyter notebook that rebuilds <strong className="text-foreground">{dataset.name} v{preview.data?.version ?? dataset.current_version}</strong>{" "}
          from the raw file{c ? (
            <>: <span className="font-mono">{c.steps}</span> {c.steps === 1 ? "step" : "steps"}, <span className="font-mono">{c.widgets}</span>{" "}
              {c.widgets === 1 ? "widget" : "widgets"}, <span className="font-mono">{c.runs}</span> model {c.runs === 1 ? "run" : "runs"},{" "}
              <span className="font-mono">{c.cards}</span> story {c.cards === 1 ? "card" : "cards"}
              {c.notes ? <>, <span className="font-mono">{c.notes}</span> canvas {c.notes === 1 ? "note" : "notes"}</> : null}.</>
          ) : "."}
        </DialogDescription>
        {o && (
          <div className="flex flex-col gap-3">
            <Check label="Include data" help="The raw CSV downloads next to the notebook." checked={o.include_data} onChange={(v) => set("include_data", v)} />
            <Check label="Include story cards" help="Each card follows its widget; the overview opens the notebook." checked={o.include_cards} onChange={(v) => set("include_cards", v)} />
            <Check label="Include canvas notes" help="Notes from the Flow canvas." checked={o.include_notes} onChange={(v) => set("include_notes", v)} />
            <Check label="Include ML runs" help="Each run's reproduction code and its tables." checked={o.include_runs} onChange={(v) => set("include_runs", v)} />
            <div className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium">Order</span>
              <Segmented label="Order" value="steps_dashboard" onChange={() => undefined}
                options={[{ value: "steps_dashboard", label: "Steps, then dashboard order" },
                          { value: "flow_path", label: <span title="Order the canvas first" className="opacity-40">Flow reading path</span> }]} />
            </div>
          </div>
        )}
        {(busy || pending > 0 || (preview.data?.notes.length ?? 0) > 0) && (
          <div className="flex gap-2.5 rounded-md bg-muted p-3 text-[13px]">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
            <div className="flex flex-col gap-2">
              {busy && <p>A job is still running. This export uses v{dataset.current_version}, the latest committed version.</p>}
              {pending > 0 && <p>You have {pending} unsaved {pending === 1 ? "edit" : "edits"}. They are not included; save first to include them.</p>}
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
