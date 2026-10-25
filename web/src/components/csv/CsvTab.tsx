// The CSV tab (App Flow §8, UI/UX brief §5.6), within cut 5: the paged grid with marks, cell edits,
// add and delete row, sort, find, Save (with conflicts) and Discard, Clean with AI, Restore for
// quarantined rows, and the Download menu. Toolbar 40px, grid, status bar 28px.
import { BookOpen, Download, Plus, RotateCcw, Search, Sparkles, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { busyReason, find, makeSelection, useCleanScoped, type Sort } from "@/api/csv";
import { useDatacard } from "@/api/queries";
import type { Column, Dataset } from "@/api/types";
import { Button } from "@/components/ui/button";
import { MenuContent, MenuItem, MenuRoot, MenuTrigger } from "@/components/ui/menu";
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Segmented } from "@/components/ui/segmented";
import { cn } from "@/lib/utils";
import { pendingCount, useEdits } from "@/state/edits";
import { useUi } from "@/state/ui";
import { Grid, type GridHandle, type GridSelectionInfo } from "./Grid";

const NO_SELECTION: GridSelectionInfo = { rowIds: [], columns: [], newRows: [], cells: 0, current: null, quarantined: [] };

export function CsvTab({ dataset }: { dataset: Dataset }) {
  const version = dataset.current_version;
  const edits = useEdits();
  const buffer = useEdits((s) => s.buffers[dataset.id]);
  const card = useDatacard(dataset.id);
  const grid = useRef<GridHandle>(null);
  const [sort, setSort] = useState<Sort | null>(null);
  const [params, setParams] = useSearchParams();
  const urlSelection = params.get("rows");
  const [found, setFound] = useState<{ q: string; selection: string; count: number; rows: number; matches: Set<string> } | null>(null);
  const [findOpen, setFindOpen] = useState(false);
  const [selection, setSelection] = useState<GridSelectionInfo>(NO_SELECTION);
  useEffect(() => () => useUi.getState().setCsvSelection(null), []); // leaving the tab clears the chat's context
  const [shape, setShape] = useState<{ total: number; columns: Column[] }>({ total: 0, columns: [] });
  const setExportOpen = useUi((s) => s.setExportOpen);

  const hydrate = useEdits((s) => s.hydrate);
  useEffect(() => hydrate(dataset.id), [dataset.id, hydrate]);

  const onEdit = useCallback((e: { rowId: number | null; tempId: string | null; column: string; value: string; old: unknown }) => {
    if (e.tempId) edits.setNewCell(dataset.id, e.tempId, e.column, e.value);
    else if (e.rowId !== null) edits.setCell(dataset.id, version, { row_id: e.rowId, column: e.column, value: e.value, old: e.old });
  }, [dataset.id, version, edits]);

  const addRow = () => {
    edits.addRow(dataset.id, version);
    toast("Row added at the top. Fill it in, then save.");
  };
  const deleteRows = () => {
    for (const t of selection.newRows) edits.removeNewRow(dataset.id, t);
    if (selection.rowIds.length) edits.toggleDelete(dataset.id, version, selection.rowIds);
  };
  const restoreRows = () => edits.toggleRestore(dataset.id, version, selection.quarantined);

  const runFind = async (q: string) => {
    if (!q.trim()) return clearFind();
    try {
      const res = await find(dataset.id, q.trim());
      if (res.count === 0) {
        setFound(null);
        toast("No cells match.");
        return;
      }
      const rows = [...new Set(res.first_matches.map((m) => m.row_id))];
      const sel = await makeSelection(dataset.id, rows, `Find: ${q.trim()}`);
      setFound({ q: q.trim(), selection: sel.selection_id, count: res.count, rows: rows.length,
                 matches: new Set(res.first_matches.map((m) => `${m.row_id}:${m.column}`)) });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const clearFind = () => {
    setFound(null);
    setFindOpen(false);
  };

  const selectionId = found?.selection ?? urlSelection;
  const matches = useMemo(() => found?.matches ?? new Set<string>(), [found]);
  const restoring = selection.quarantined.length;
  const marked = selection.rowIds.length + selection.newRows.length;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-10 shrink-0 items-center gap-1 border-b border-border px-3" role="toolbar" aria-label="CSV tools">
        <Button size="sm" variant="ghost" onClick={addRow}><Plus /> Add row</Button>
        <Button size="sm" variant="ghost" disabled={marked === 0} onClick={deleteRows}
          title={marked === 0 ? "Select cells in the rows to delete" : undefined}>
          <Trash2 /> {marked > 1 ? `Delete ${marked} rows` : "Delete row"}
        </Button>
        {restoring > 0 && (
          <Button size="sm" variant="ghost" onClick={restoreRows} title="Bring quarantined rows back into charts, models and stories">
            <RotateCcw /> Restore {restoring > 1 ? `${restoring} rows` : "row"}
          </Button>
        )}
        <Button size="sm" variant="ghost" aria-pressed={findOpen} onClick={() => setFindOpen((o) => !o)}><Search /> Find</Button>
        <CleanPopover dataset={dataset} selection={selection} />
        <MenuRoot>
          <MenuTrigger asChild>
            <Button size="sm" variant="ghost"><Download /> Download</Button>
          </MenuTrigger>
          <MenuContent align="start">
            <MenuItem onSelect={() => window.location.assign(`/api/v1/datasets/${dataset.id}/export.csv`)}><Download /> CSV</MenuItem>
            <MenuItem onSelect={() => setExportOpen(true)}><BookOpen /> Notebook (.ipynb)</MenuItem>
          </MenuContent>
        </MenuRoot>
        <Legend />
      </div>
      {(findOpen || found) && (
        <FindBar initial={found?.q ?? ""} found={found} onFind={runFind} onClear={clearFind} />
      )}
      {urlSelection && !found && (
        <div className="flex items-center gap-2 border-b border-border px-4 py-1.5 text-[13px]">
          <span className="inline-flex h-7 items-center rounded-full border border-accent bg-accent-soft px-2.5">
            {shape.total.toLocaleString()} rows selected
          </span>
          <Button size="sm" variant="ghost" onClick={() => setParams({})}>Show all rows</Button>
        </div>
      )}
      <Grid
        ref={grid}
        datasetId={dataset.id}
        version={version}
        sort={sort}
        onSort={setSort}
        selectionId={selectionId}
        matches={matches}
        card={card.data?.version === version ? card.data.columns : card.data?.columns ?? []}
        buffer={buffer}
        onEdit={onEdit}
        onSelection={(s) => {
          setSelection(s);
          // The selected cells are the chat's context on this tab ("set these to 0", "clean these rows").
          useUi.getState().setCsvSelection(s.rowIds.length ? { row_ids: s.rowIds.slice(0, 500), columns: s.columns } : null);
        }}
        onLoaded={setShape}
      />
      <StatusBar total={shape.total} pending={pendingCount(buffer)} selection={selection} sort={sort} />
    </div>
  );
}

function Legend() {
  return (
    <div className="ml-auto hidden items-center gap-3 text-[12px] text-muted-foreground md:flex" aria-label="Legend">
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block size-3 bg-changed shadow-[inset_0_2px_0_var(--info)]" /> changed
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block size-3 outline outline-1 -outline-offset-1 outline-dashed outline-warning" /> flagged
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="relative inline-block size-3 bg-unsaved outline outline-1 -outline-offset-1 outline-accent">
          <span className="absolute left-0.5 top-0.5 size-1 rounded-full bg-accent" />
        </span> unsaved
      </span>
    </div>
  );
}

function FindBar({ initial, found, onFind, onClear }: {
  initial: string; found: { count: number; rows: number } | null; onFind: (q: string) => void; onClear: () => void;
}) {
  const [q, setQ] = useState(initial);
  return (
    <form
      className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-3"
      onSubmit={(e) => { e.preventDefault(); onFind(q); }}
    >
      <Search className="size-4 text-muted-foreground" />
      <input
        autoFocus
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Escape") onClear(); }}
        placeholder="Find in every cell…"
        aria-label="Find"
        className="h-8 w-64 rounded-md border border-input bg-card px-2.5 text-[13px] outline-none focus-visible:border-accent"
      />
      <Button size="sm" type="submit">Find</Button>
      {found && (
        <span className="text-[12px] text-muted-foreground">
          {found.count.toLocaleString()} {found.count === 1 ? "match" : "matches"} in {found.rows.toLocaleString()} {found.rows === 1 ? "row" : "rows"}; only those rows are shown
        </span>
      )}
      <Button size="icon" variant="ghost" type="button" aria-label="Close find" className="ml-auto" onClick={onClear}><X /></Button>
    </form>
  );
}

function StatusBar({ total, pending, selection, sort }: { total: number; pending: number; selection: GridSelectionInfo; sort: Sort | null }) {
  const cur = selection.current;
  return (
    <div className="flex h-7 shrink-0 items-center gap-4 border-t border-border px-4 text-[12px] text-muted-foreground">
      <span>{selection.cells > 1 ? `${selection.cells.toLocaleString()} cells` : ""}</span>
      <span>{total.toLocaleString()} rows{sort ? ` · sorted by ${sort.column} ${sort.dir === "asc" ? "↑" : "↓"} (view only)` : ""}</span>
      {pending > 0 && <span className="text-accent">{pending} unsaved</span>}
      <span className="ml-auto font-mono">
        {cur?.column ? `Row ${cur.rowId ?? "new"} · ${cur.column}` : ""}
      </span>
    </div>
  );
}

function CleanPopover({ dataset, selection }: { dataset: Dataset; selection: GridSelectionInfo }) {
  const pending = pendingCount(useEdits((s) => s.buffers[dataset.id]));
  const discard = useEdits((s) => s.discard);
  const [scope, setScope] = useState<"all" | "selection" | "new_rows">("all");
  const clean = useCleanScoped(dataset.id);
  const busy = busyReason(dataset);
  const start = async () => {
    try {
      if (scope === "selection") {
        const sel = await makeSelection(dataset.id, selection.rowIds, "Clean with AI");
        await clean.mutateAsync({ kind: "selection", selection_id: sel.selection_id });
      } else {
        await clean.mutateAsync({ kind: scope });
      }
      toast("Cleaning started. Its steps appear in Changes as they commit.");
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button size="sm" variant="secondary" disabled={!!busy} title={busy ?? undefined}><Sparkles /> Clean with AI</Button>
      </PopoverTrigger>
      <PopoverContent>
        <div className="flex flex-col gap-3">
          <p className="text-[14px] font-semibold">Clean with AI</p>
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Scope</span>
            {([
              ["all", "Whole dataset"],
              ["selection", `Current selection (${selection.rowIds.length.toLocaleString()} rows)`],
              ["new_rows", "Rows added since the last clean"],
            ] as const).map(([v, label]) => (
              <label key={v} className={cn("flex items-center gap-2", v === "selection" && selection.rowIds.length === 0 && "opacity-40")}>
                <input type="radio" name="clean-scope" checked={scope === v} disabled={v === "selection" && selection.rowIds.length === 0}
                  onChange={() => setScope(v)} />
                {label}
              </label>
            ))}
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Mode</span>
            <Segmented label="Mode" value="auto" options={[{ value: "auto", label: "Auto" }]} onChange={() => undefined} />
            <span className="text-[12px] text-muted-foreground">Step by step comes later.</span>
          </div>
          {pending > 0 && (
            <div className="rounded-md bg-muted p-2.5 text-[12px]">
              Save or discard your {pending} unsaved {pending === 1 ? "change" : "changes"} first.
              <div className="mt-2 flex gap-2">
                <Button size="sm" variant="ghost" onClick={() => discard(dataset.id)}>Discard</Button>
              </div>
            </div>
          )}
          <p className="text-[12px] text-muted-foreground">Cells you edited by hand are left alone and listed in the report.</p>
          <div className="flex justify-end gap-2">
            <PopoverClose asChild><Button size="sm" variant="ghost">Cancel</Button></PopoverClose>
            <PopoverClose asChild>
              <Button size="sm" variant="primary" disabled={pending > 0 || clean.isPending} onClick={start}>Start</Button>
            </PopoverClose>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
