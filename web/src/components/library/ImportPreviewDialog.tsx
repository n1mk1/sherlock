// Import preview (App Flow §3.2, UI brief §5.2): parsed locally; nothing uploads until Import.
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { readDictionary } from "@/api/columnNotes";
import { useUpload } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import {
  DELIMITERS, ENCODINGS, SAMPLE_BYTES, buildPreview, changedOptions, decode, detectEncoding, formatBytes,
  looksBinary, sizeError, type PreviewSettings,
} from "@/lib/importPreview";
import { useUi } from "@/state/ui";

const BINARY = "Couldn't read this as text. Is it a spreadsheet or a zip? Export it as CSV first.";

export function ImportPreviewDialog() {
  const file = useUi((s) => s.importFile);
  const close = () => useUi.getState().openImport(null);
  return (
    <Dialog open={!!file} onOpenChange={(open) => !open && close()}>
      {file && <PreviewBody key={`${file.name}:${file.size}:${file.lastModified}`} file={file} onDone={close} />}
    </Dialog>
  );
}

function PreviewBody({ file, onDone }: { file: File; onDone: () => void }) {
  const [bytes, setBytes] = useState<Uint8Array | null>(null);
  const [detected, setDetected] = useState<PreviewSettings | null>(null);
  const [settings, setSettings] = useState<PreviewSettings | null>(null);
  const [dictionaryUrl, setDictionaryUrl] = useState("");
  const upload = useUpload();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const tooBig = sizeError(file.size);

  useEffect(() => {
    let live = true;
    file.slice(0, SAMPLE_BYTES).arrayBuffer().then((buf) => {
      if (!live) return;
      const b = new Uint8Array(buf);
      const encoding = detectEncoding(b);
      const auto = buildPreview(decode(b, encoding), { delimiter: "", encoding, headerRow: 1, skipRows: 0 }, file.size, b.length);
      const first: PreviewSettings = { delimiter: auto.delimiter, encoding, headerRow: 1, skipRows: 0 };
      setBytes(b);
      setDetected(first);
      setSettings(first);
    });
    return () => {
      live = false;
    };
  }, [file]);

  const binary = bytes ? looksBinary(bytes) : false;
  const preview = useMemo(
    () => (bytes && settings && !binary ? buildPreview(decode(bytes, settings.encoding), settings, file.size, bytes.length) : null),
    [bytes, settings, binary, file.size],
  );
  const blocker = tooBig ?? (binary ? BINARY : preview?.error ?? null);
  const set = (patch: Partial<PreviewSettings>) => setSettings((s) => (s ? { ...s, ...patch } : s));

  const doImport = () => {
    if (!detected || !settings) return;
    upload.mutate(
      { file, options: changedOptions(detected, settings) },
      {
        onSuccess: (ds) => {
          onDone();
          navigate(`/d/${ds.id}`);
          const url = dictionaryUrl.trim();
          if (url) {
            // Read after the upload: the column notes arrive in the CSV tab's header tooltips (PRD LOAD-7).
            readDictionary(qc, ds.id, url).then(
              (out) => out.note
                ? toast.message(out.note)
                : toast.success(`Read the data dictionary: notes on ${out.notes.length} ${out.notes.length === 1 ? "column" : "columns"}.`),
              (err: Error) => toast.error(err.message),
            );
          }
        },
        onError: (err) => toast.error((err as Error).message),
      },
    );
  };

  return (
    <DialogContent className="max-w-[880px]" aria-describedby="import-detected">
      <div className="border-b border-border px-6 pb-4 pt-5">
        <DialogTitle className="font-serif text-[22px] leading-tight">
          Import {file.name} <span className="font-sans text-[14px] text-muted-foreground">· {formatBytes(file.size)}</span>
        </DialogTitle>
      </div>
      {settings && !tooBig && !binary && (
        <div className="grid grid-cols-2 gap-3 px-6 pt-4 sm:grid-cols-4">
          <Field label="Delimiter">
            <select
              className="h-9 w-full rounded-md border border-input bg-card px-2"
              value={DELIMITERS.some((d) => d.value === settings.delimiter) ? settings.delimiter : "other"}
              onChange={(e) => set({ delimiter: e.target.value === "other" ? settings.delimiter : e.target.value })}
            >
              {DELIMITERS.map((d) => <option key={d.label} value={d.value}>{d.label}</option>)}
              {!DELIMITERS.some((d) => d.value === settings.delimiter) && (
                <option value="other">Other ({JSON.stringify(settings.delimiter)})</option>
              )}
            </select>
          </Field>
          <Field label="Encoding">
            <select
              className="h-9 w-full rounded-md border border-input bg-card px-2"
              value={settings.encoding}
              onChange={(e) => set({ encoding: e.target.value })}
            >
              {ENCODINGS.map((e) => <option key={e.value} value={e.value}>{e.label}</option>)}
            </select>
          </Field>
          <Field label="Header row">
            <input
              type="number" min={0} max={100}
              className="h-9 w-full rounded-md border border-input bg-card px-2 font-mono"
              value={settings.headerRow}
              onChange={(e) => set({ headerRow: clamp(e.target.valueAsNumber, 0, 100) })}
            />
          </Field>
          <Field label="Skip rows">
            <input
              type="number" min={0} max={1000}
              className="h-9 w-full rounded-md border border-input bg-card px-2 font-mono"
              value={settings.skipRows}
              onChange={(e) => set({ skipRows: clamp(e.target.valueAsNumber, 0, 1000) })}
            />
          </Field>
          <div className="col-span-2 sm:col-span-4">
            <Field label="Data dictionary URL (optional)">
              <input
                type="url" inputMode="url" maxLength={2000}
                placeholder="https://… a page that describes the columns"
                className="h-9 w-full rounded-md border border-input bg-card px-2"
                value={dictionaryUrl}
                onChange={(e) => setDictionaryUrl(e.target.value)}
              />
            </Field>
          </div>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto px-6 py-4">
        {preview && preview.columns.length > 0 && (
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr>
                {preview.columns.map((c) => (
                  <th key={c} className="whitespace-nowrap border-b border-border bg-muted px-2 py-1.5 text-left font-semibold">{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((row, i) => (
                <tr key={i}>
                  {preview.columns.map((_, j) => (
                    <td key={j} className="max-w-[220px] truncate whitespace-nowrap border-b border-border px-2 py-1 font-mono text-[12.5px]">
                      {row[j] ?? ""}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3 border-t border-border px-6 py-4">
        <DialogDescription id="import-detected" className="mr-auto text-[13px] text-muted-foreground">
          {blocker ? (
            <span className="text-destructive">{blocker}</span>
          ) : preview ? (
            <>
              Detected {preview.columns.length} columns · about {preview.estimatedRows.toLocaleString()} rows
              {preview.notes.map((n) => <span key={n} className="block">{n}</span>)}
            </>
          ) : (
            "Reading the file…"
          )}
        </DialogDescription>
        <Button variant="ghost" onClick={onDone}>Cancel</Button>
        <Button variant="primary" disabled={!!blocker || !preview} loading={upload.isPending} onClick={doImport}>
          Import
        </Button>
      </div>
    </DialogContent>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-[12px] font-medium text-muted-foreground">
      {label}
      {children}
    </label>
  );
}

function clamp(n: number, lo: number, hi: number) {
  return Number.isFinite(n) ? Math.min(hi, Math.max(lo, Math.round(n))) : lo;
}
