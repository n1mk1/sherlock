// The CSV grid (App Flow §8, UI/UX brief §5.6), within cut 5: the paged grid with marks, cell edits,
// add and delete row, sort, find, Save (with conflicts) and Discard, Clean with AI (it opens the cleaning
// plan in the right panel), Restore for quarantined rows, and the Download menu. Toolbar 40px, grid,
// status bar 28px. While a clean owns the data the grid is read-only, with a banner.
import { BookOpen, Download, Plus, Redo2, RotateCcw, Search, Sparkles, Trash2, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { busyReason, find, makeSelection, useHistory, useMove, type Sort } from "@/api/csv";
import { useCreatePlan, useDatacard } from "@/api/queries";
import type { Column, Dataset } from "@/api/types";
import { Button } from "@/components/ui/button";
import { MenuContent, MenuItem, MenuRoot, MenuTrigger } from "@/components/ui/menu";
import { Pill } from "@/components/ui/pill";
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
  // "Sort by fare" in chat sorts this view, as a click on the header would; taken once, so a later visit starts unsorted.
  const gridSort = useUi((s) => s.gridSort);
  useEffect(() => {
    if (!gridSort) return;
    setSort(gridSort.sort);
    useUi.setState({ gridSort: null });
  }, [gridSort]);
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
      <div className="flex h-12 shrink-0 items-center gap-0.5 border-b border-border px-3" role="toolbar" aria-label="CSV tools">
        <CleanButton dataset={dataset} />
        <Divider />
        <Button size="sm" variant="ghost" disabled={locked} title={locked ? lockedWhy : undefined} onClick={addRow}><Plus /> Add row</Button>
        <Button size="sm" variant="ghost" disabled={marked === 0 || locked} onClick={deleteRows}
          title={locked ? lockedWhy : marked === 0 ? "Select cells in the rows to delete" : undefined}>
          <Trash2 /> {marked > 1 ? `Delete ${marked} rows` : "Delete row"}
        </Button>
        {restoring > 0 && (
          <Button size="sm" variant="ghost" disabled={locked} onClick={restoreRows}
            title={locked ? lockedWhy : "Bring set-aside rows back into answers, models and the notebook"}>
            <RotateCcw /> Restore {restoring > 1 ? `${restoring} rows` : "row"}
          </Button>
        )}
        <Button size="sm" variant="ghost" aria-pressed={findOpen} className="aria-pressed:bg-secondary" onClick={() => setFindOpen((o) => !o)}><Search /> Find</Button>
        <Divider />
        <HistoryButtons dataset={dataset} pending={pendingCount(buffer)} />
        <Divider />
        <MenuRoot>
          <MenuTrigger asChild>
            <Button size="sm" variant="ghost" className="data-[state=open]:bg-secondary"><Download /> Download</Button>
          </MenuTrigger>
          <MenuContent align="start">
            <MenuItem onSelect={() => window.location.assign(`/api/v1/datasets/${dataset.id}/export.csv`)}><Download /> CSV</MenuItem>
            <MenuItem onSelect={() => setExportOpen(true)}><BookOpen /> Notebook (.ipynb)</MenuItem>
          </MenuContent>
        </MenuRoot>
        <Legend />
      </div>
      {locked && (
        <div role="status" className="flex shrink-0 items-center gap-2 border-b border-border bg-violet-soft px-4 py-2 text-[13px] text-violet-ink">
          <Sparkles className="size-3.5" aria-hidden />
          Cleaning in progress · editing resumes when it finishes
        </div>
      )}
      {(findOpen || found) && (
        <FindBar initial={found?.q ?? ""} found={found} onFind={runFind} onClear={clearFind} />
      )}
      {urlSelection && !found && (
        <div className="flex items-center gap-2 border-b border-border px-4 py-2 text-[13px]">
          <Pill tone="accent">{shape.total.toLocaleString()} rows selected</Pill>
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

function Divider() {
  return <span aria-hidden className="mx-1.5 h-4 w-px shrink-0 bg-border-strong" />;
}

function Legend() {
  return (
    <div role="group" className="ml-auto hidden items-center gap-1.5 @[60rem]:flex" aria-label="Legend">
      <Pill size="sm" icon={<span className="size-2 rounded-[2px] bg-changed shadow-[inset_0_1.5px_0_var(--info)]" />}>changed</Pill>
      <Pill size="sm" icon={<span className="size-2 rounded-[2px] outline outline-1 -outline-offset-1 outline-dashed outline-warning" />}>flagged</Pill>
      <Pill size="sm" icon={<span className="size-2 rounded-[2px] bg-unsaved outline outline-1 -outline-offset-1 outline-accent" />}>unsaved</Pill>
    </div>
  );
}

function FindBar({ initial, found, onFind, onClear }: {
  initial: string; found: { count: number; rows: number } | null; onFind: (q: string) => void; onClear: () => void;
}) {
  const [q, setQ] = useState(initial);
  return (
    <form
      className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3"
      onSubmit={(e) => { e.preventDefault(); onFind(q); }}
    >
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Escape") onClear(); }}
          placeholder="Find in every cell…"
          aria-label="Find"
          className="h-8 w-72 rounded-full bg-secondary pl-8 pr-3 text-[13px] outline-none placeholder:text-muted-foreground focus-visible:bg-card focus-visible:shadow-[0_0_0_1px_var(--accent)]"
        />
      </div>
      <Button size="sm" type="submit">Find</Button>
      {found && (
        <Pill tone="accent" title="Only those rows are shown">
          {found.count.toLocaleString()} {found.count === 1 ? "match" : "matches"} in {found.rows.toLocaleString()} {found.rows === 1 ? "row" : "rows"}
        </Pill>
      )}
      <Button size="icon" variant="ghost" type="button" aria-label="Close find" className="ml-auto" onClick={onClear}><X /></Button>
    </form>
  );
}

function StatusBar({ total, pending, selection, sort }: { total: number; pending: number; selection: GridSelectionInfo; sort: Sort | null }) {
  const cur = selection.current;
  return (
    <div className="flex h-8 shrink-0 items-center gap-4 border-t border-border px-4 text-[12px] text-muted-foreground tnum">
      {selection.cells > 1 && <span>{selection.cells.toLocaleString()} cells</span>}
      <span>{total.toLocaleString()} rows{sort ? ` · sorted by ${sort.column} ${sort.dir === "asc" ? "↑" : "↓"} (view only)` : ""}</span>
      {pending > 0 && <span className="font-medium text-accent">{pending} unsaved</span>}
      <span className="ml-auto">
        {cur?.column ? `Row ${cur.rowId ?? "new"} · ${cur.column}` : ""}
      </span>
    </div>
  );
}

/** Undo and Redo (Ctrl+Z, Ctrl+Y or Ctrl+Shift+Z): back one state at a time, at most `undo_depth` in a row, and
 * forward again through what was undone. A new change clears Redo; older steps are in the Changes panel. Unsaved
 * grid edits are saved or discarded first, and both wait while a clean runs. */
function HistoryButtons({ dataset, pending }: { dataset: Dataset; pending: number }) {
  const history = useHistory(dataset.id, dataset.current_version);
  const move = useMove(dataset.id);
  const h = history.data;
  const busy = busyReason(dataset);
  const go = useCallback((way: "undo" | "redo") => {
    const target = way === "undo" ? h?.undo : h?.redo;
    if (busy) return void toast(busy);
    if (pending > 0) return void toast(`Save or discard your ${pending} unsaved ${pending === 1 ? "edit" : "edits"} first.`);
    if (!target || move.isPending) return;
    move.mutate({ way, base: dataset.current_version }, {
      onSuccess: () => toast(`${way === "undo" ? "Undid" : "Redid"}: ${target.summary}`),
      onError: (e) => toast.error((e as Error).message),
    });
  }, [h, busy, pending, move, dataset.current_version]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const editing = t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
      if (editing || !(e.ctrlKey || e.metaKey) || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === "z" && !e.shiftKey) {
        e.preventDefault();
        go("undo");
      } else if (k === "y" || (k === "z" && e.shiftKey)) {
        e.preventDefault();
        go("redo");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go]);
  const after = h ? Math.max(h.depth_left - 1, 0) : 0; // undos still allowed once this one is done
  const undoTitle = h?.undo
    ? `Undo: ${h.undo.summary} (Ctrl+Z) · ${after === 0 ? "the last one in a row" : `${after} more after this`}`
    : h && h.depth_left === 0 ? "You can undo up to 3 changes in a row; older ones are in the Changes panel" : "Nothing to undo";
  const redoTitle = h?.redo ? `Redo: ${h.redo.summary} (Ctrl+Y)` : "Nothing to redo";
  return (
    <>
      <Button size="icon" variant="ghost" aria-label="Undo" title={busy ?? undoTitle} disabled={!h?.undo || !!busy}
        loading={move.isPending && move.variables?.way === "undo"} onClick={() => go("undo")}>
        {!(move.isPending && move.variables?.way === "undo") && <Undo2 />}
      </Button>
      <Button size="icon" variant="ghost" aria-label="Redo" title={busy ?? redoTitle} disabled={!h?.redo || !!busy}
        loading={move.isPending && move.variables?.way === "redo"} onClick={() => go("redo")}>
        {!(move.isPending && move.variables?.way === "redo") && <Redo2 />}
      </Button>
    </>
  );
}

/** Clean with AI opens the cleaning plan in the right panel (App Flow §8.4); a draft already open stays. */
function CleanButton({ dataset }: { dataset: Dataset }) {
  const create = useCreatePlan(dataset.id);
  const setRightOpen = useUi((s) => s.setRightOpen);
  const busy = busyReason(dataset);
  return (
    <Button size="sm" variant="violet" disabled={!!busy} title={busy ?? undefined} loading={create.isPending}
      onClick={() => {
        setRightOpen(true); // on a narrow window the right panel is a slide-over
        create.mutate(undefined, { onError: (e) => toast.error((e as Error).message) });
      }}>
      <Sparkles /> Clean with AI
    </Button>
  );
}
