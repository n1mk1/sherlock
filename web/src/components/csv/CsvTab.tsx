// The CSV grid (App Flow §8, UI/UX brief §5.6), within cut 5: the paged grid with marks, cell edits,
// add and delete row, sort, find, Save (with conflicts) and Discard, Clean with AI (it opens the cleaning
// plan in the right panel), Restore for quarantined rows, and the Download menu. Toolbar 40px, grid,
// status bar 28px. While a clean owns the data the grid is read-only, with a banner.
import { BookOpen, Download, Plus, RotateCcw, Search, Sparkles, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { busyReason, find, makeSelection, type Sort } from "@/api/csv";
import { useCreatePlan, useDatacard } from "@/api/queries";
import type { Column, Dataset } from "@/api/types";
import { Button } from "@/components/ui/button";
import { MenuContent, MenuItem, MenuRoot, MenuTrigger } from "@/components/ui/menu";
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
  useEffect(() => () => useUi.getState().setCsvSelection(null), []); // leaving the grid clears the chat's context
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
  // Find's rows were picked on the version it ran on: a new version runs it again, so the rows and
  // the count shown are this version's (or "No cells match." clears it).
  const findVersion = useRef(version);
  const rerunFind = useRef(runFind);
  rerunFind.current = runFind;
  useEffect(() => {
    if (findVersion.current === version) return;
    findVersion.current = version;
    if (found) void rerunFind.current(found.q);
    // Only a new version re-runs it; `found` changing is the re-run's own result.
  }, [version]);

  const selectionId = found?.selection ?? urlSelection;
  const matches = useMemo(() => found?.matches ?? new Set<string>(), [found]);
  const restoring = selection.quarantined.length;
  const marked = selection.rowIds.length + selection.newRows.length;
  // A job that owns the data: editing waits for it (App Flow §8).
  const locked = dataset.status === "cleaning";
  const lockedWhy = "Cleaning in progress";

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-10 shrink-0 items-center gap-1 border-b border-border px-3" role="toolbar" aria-label="CSV tools">
        <Button size="sm" variant="ghost" disabled={locked} title={locked ? lockedWhy : undefined} onClick={addRow}><Plus /> Add row</Button>
        <Button size="sm" variant="ghost" disabled={marked === 0 || locked} onClick={deleteRows}
          title={locked ? lockedWhy : marked === 0 ? "Select cells in the rows to delete" : undefined}>
          <Trash2 /> {marked > 1 ? `Delete ${marked} rows` : "Delete row"}
        </Button>
        {restoring > 0 && (
          <Button size="sm" variant="ghost" disabled={locked} onClick={restoreRows}
            title={locked ? lockedWhy : "Bring quarantined rows back into answers, models and the notebook"}>
            <RotateCcw /> Restore {restoring > 1 ? `${restoring} rows` : "row"}
          </Button>
        )}
        <Button size="sm" variant="ghost" aria-pressed={findOpen} onClick={() => setFindOpen((o) => !o)}><Search /> Find</Button>
        <CleanButton dataset={dataset} />
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
      {locked && (
        <div role="status" className="flex shrink-0 items-center gap-2 border-b border-border bg-muted px-4 py-1.5 text-[13px]">
          Cleaning in progress · editing resumes when it finishes
        </div>
      )}
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
        readOnly={locked}
        onEdit={onEdit}
        onSelection={(s) => {
          setSelection(s);
          // The selected cells are the chat's context on this tab ("set these to 0", "clean these rows") and
          // the cleaning plan's selection scope; the chat sends at most 500 of the rows.
          useUi.getState().setCsvSelection(s.rowIds.length ? { row_ids: s.rowIds, columns: s.columns } : null);
        }}
        onLoaded={setShape}
      />
      <StatusBar total={shape.total} pending={pendingCount(buffer)} selection={selection} sort={sort} />
    </div>
  );
}

function Legend() {
  return (
    <div role="group" className="ml-auto hidden items-center gap-3 text-[12px] text-muted-foreground md:flex" aria-label="Legend">
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

/** Clean with AI opens the cleaning plan in the right panel (App Flow §8.4); a draft already open stays. */
function CleanButton({ dataset }: { dataset: Dataset }) {
  const create = useCreatePlan(dataset.id);
  const setRightOpen = useUi((s) => s.setRightOpen);
  const busy = busyReason(dataset);
  return (
    <Button size="sm" variant="secondary" disabled={!!busy} title={busy ?? undefined} loading={create.isPending}
      onClick={() => {
        setRightOpen(true); // on a narrow window the right panel is a slide-over
        create.mutate(undefined, { onError: (e) => toast.error((e as Error).message) });
      }}>
      <Sparkles /> Clean with AI
    </Button>
  );
}
