// The CSV grid (App Flow §8, UI/UX brief §4.7): Glide Data Grid over the rows API, 200 rows a page,
// fetched as they scroll into view. The first column is the row number (`_row_id`, "new" for a
// pending row, struck through when quarantined or marked for deletion). Cells show the marks from
// the rows API (changed, flagged, invalid) and the pending edits from the buffer (unsaved), each
// drawn so it doesn't rely on color alone. Clicking a header sorts by it (asc → desc → none); sorting
// is a view, never a change to the data.
import "@glideapps/glide-data-grid/dist/index.css";
import {
  DataEditor, GridCellKind, CompactSelection,
  type DataEditorRef, type DrawCellCallback, type DrawHeaderCallback, type EditableGridCell, type GridCell,
  type GridColumn, type GridSelection, type Item, type Rectangle, type Theme,
} from "@glideapps/glide-data-grid";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { fetchRows, type RowsPage, type Sort } from "@/api/csv";
import type { ColumnCard, Column } from "@/api/types";
import { displayValue, fitsType, isNumericType, typeLabel } from "@/lib/cells";
import { resolveTokens } from "@/lib/tokens";
import { editKey, type Buffer } from "@/state/edits";

export const PAGE = 200;
const ROW_COL = "_row_id";
type Row = RowsPage["rows"][number];

export interface GridSelectionInfo {
  rowIds: number[];          // server rows touched by the selection
  newRows: string[];         // pending rows touched by it (temp ids)
  cells: number;             // selected cells (user columns)
  current: { rowId: number | null; tempId: string | null; column: string | null } | null;
  quarantined: number[];     // selected rows that are quarantined
}

export interface GridHandle {
  scrollToRow: (rowId: number, column?: string) => void;
  reload: () => void;
}

const TOKENS = {
  accent: "--accent", accentSoft: "--accent-soft", fg: "--foreground", muted: "--muted-foreground", card: "--card",
  background: "--background", border: "--border", borderStrong: "--border-strong", info: "--info", warning: "--warning",
  destructive: "--destructive", changed: "--changed", unsaved: "--unsaved", chart3: "--chart-3", mutedBg: "--muted",
};

/** Re-resolve the tokens when the mode or accent changes (they live on <html>). */
function useTokens() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const obs = new MutationObserver(() => setTick((t) => t + 1));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-accent"] });
    return () => obs.disconnect();
  }, []);
  return useMemo(() => resolveTokens(TOKENS), [tick]);
}

export const Grid = forwardRef<GridHandle, {
  datasetId: string;
  version: number;
  sort: Sort | null;
  onSort: (s: Sort | null) => void;
  selectionId: string | null; // rows limited to a saved selection (find, ?rows=)
  matches: Set<string>;       // find matches, `${row_id}:${column}`
  card: ColumnCard[];
  buffer: Buffer | undefined;
  onEdit: (cell: { rowId: number | null; tempId: string | null; column: string; value: string; old: unknown }) => void;
  onSelection: (info: GridSelectionInfo) => void;
  onLoaded: (info: { total: number; columns: Column[] }) => void;
}>(function Grid({ datasetId, version, sort, onSort, selectionId, matches, card, buffer, onEdit, onSelection, onLoaded }, ref) {
  const t = useTokens();
  const editor = useRef<DataEditorRef>(null);
  const pages = useRef(new Map<number, Row[]>());
  const loading = useRef(new Set<number>());
  const [columns, setColumns] = useState<Column[]>([]);
  const [total, setTotal] = useState(0);
  const [generation, setGeneration] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<GridSelection>({ columns: CompactSelection.empty(), rows: CompactSelection.empty() });
  const viewKey = `${datasetId}:${version}:${sort?.column ?? ""}:${sort?.dir ?? ""}:${selectionId ?? ""}`;
  const onLoadedRef = useRef(onLoaded);
  onLoadedRef.current = onLoaded;
  const viewKeyRef = useRef(viewKey);

  const newRows = buffer?.newRows ?? [];
  const deleted = useMemo(() => new Set(buffer?.deleted ?? []), [buffer]);
  const restored = useMemo(() => new Set(buffer?.restored ?? []), [buffer]);
  const types = useMemo(() => Object.fromEntries(columns.map((c) => [c.name, c.type])), [columns]);
  const userCols = useMemo(() => columns.filter((c) => c.name !== ROW_COL && c.name !== "_quarantine_reason"), [columns]);

  const load = useCallback((page: number, key: string) => {
    if (pages.current.has(page) || loading.current.has(page)) return;
    loading.current.add(page);
    fetchRows(datasetId, version, page * PAGE, PAGE, sort, selectionId)
      .then((res) => {
        if (key !== viewKeyRef.current) return; // the view changed while this page was on its way
        pages.current.set(page, res.rows);
        if (page === 0) {
          setColumns(res.columns);
          setTotal(res.total);
          onLoadedRef.current({ total: res.total, columns: res.columns });
        }
        setGeneration((g) => g + 1);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => loading.current.delete(page));
  }, [datasetId, version, sort, selectionId]);

  // A new version, sort or selection is a new view: drop the cache and start from the top.
  useEffect(() => {
    viewKeyRef.current = viewKey;
    pages.current = new Map();
    loading.current = new Set();
    setError(null);
    load(0, viewKey);
  }, [viewKey, load]);

  useImperativeHandle(ref, () => ({
    scrollToRow: (rowId, column) => {
      for (const [p, rows] of pages.current) {
        const i = rows.findIndex((r) => r._row_id === rowId);
        if (i >= 0) {
          const col = column ? Math.max(0, gridCols.findIndex((c) => c.id === column)) : 1;
          editor.current?.scrollTo(col, newRows.length + p * PAGE + i, "both", 0, 0, { vAlign: "center" });
          return;
        }
      }
    },
    reload: () => {
      pages.current = new Map();
      setGeneration((g) => g + 1);
      load(0, viewKeyRef.current);
    },
  }));

  const gridCols = useMemo<GridColumn[]>(() => [
    { id: ROW_COL, title: "#", width: 64 },
    ...userCols.map((c) => ({ id: c.name, title: c.name, width: isNumericType(c.type) ? 110 : c.type === "VARCHAR" ? 170 : 130 })),
  ], [userCols]);

  const rowAt = useCallback((row: number): { kind: "new"; temp: string; cells: Record<string, string> } | { kind: "row"; row: Row } | null => {
    if (row < newRows.length) return { kind: "new", temp: newRows[row].temp_id, cells: newRows[row].cells };
    const i = row - newRows.length;
    const page = pages.current.get(Math.floor(i / PAGE));
    if (!page) {
      load(Math.floor(i / PAGE), viewKeyRef.current);
      return null;
    }
    const r = page[i % PAGE];
    return r ? { kind: "row", row: r } : null;
  }, [newRows, load]);

  const getCellContent = useCallback(([col, row]: Item): GridCell => {
    const at = rowAt(row);
    const column = gridCols[col];
    if (!at || !column) return { kind: GridCellKind.Loading, allowOverlay: false };
    const name = column.id as string;
    const mono = { fontFamily: "Geist Mono Variable, ui-monospace, monospace" };
    if (name === ROW_COL) {
      const label = at.kind === "new" ? "new" : String(at.row._row_id);
      return { kind: GridCellKind.Text, data: label, displayData: label, allowOverlay: false, readonly: true,
               contentAlign: "right", themeOverride: { ...mono, textDark: t.muted, bgCell: t.background } };
    }
    const type = types[name] ?? "VARCHAR";
    const numeric = isNumericType(type);
    const base = { allowOverlay: true, contentAlign: numeric ? "right" as const : "left" as const,
                   themeOverride: numeric || type === "BOOLEAN" ? mono : undefined };
    if (at.kind === "new") {
      const v = at.cells[name] ?? "";
      return { kind: GridCellKind.Text, data: v, displayData: v, ...base, themeOverride: { ...base.themeOverride, bgCell: t.unsaved } };
    }
    const pending = buffer?.edits[editKey(at.row._row_id, name)];
    const v = pending ? pending.value : displayValue(at.row.cells[name]);
    const mark = pending ? "unsaved" : at.row.marks[name];
    const bg = mark === "unsaved" ? t.unsaved : mark === "changed" ? t.changed : matches.has(`${at.row._row_id}:${name}`) ? t.accentSoft : undefined;
    return {
      kind: GridCellKind.Text, data: v, displayData: v, ...base, readonly: deleted.has(at.row._row_id),
      themeOverride: bg ? { ...base.themeOverride, bgCell: bg } : base.themeOverride,
    };
  }, [rowAt, gridCols, types, buffer, matches, deleted, t, generation]);

  const drawCell = useCallback<DrawCellCallback>((args, drawContent) => {
    drawContent();
    const { ctx, rect, col, row } = args;
    const at = rowAt(row);
    if (!at) return;
    const name = gridCols[col]?.id as string;
    if (name === ROW_COL) {
      const struck = at.kind === "row" && (at.row.quarantined && !restored.has(at.row._row_id) || deleted.has(at.row._row_id));
      if (struck) drawMarks(ctx, rect, "struck", false, t);
      return;
    }
    if (at.kind === "new") {
      const v = at.cells[name];
      if (v !== undefined && !fitsType(types[name] ?? "VARCHAR", v)) drawMarks(ctx, rect, "invalid", false, t);
      return;
    }
    const pending = buffer?.edits[editKey(at.row._row_id, name)];
    drawMarks(ctx, rect, pending ? "unsaved" : at.row.marks[name],
      !!pending && !fitsType(types[name] ?? "VARCHAR", pending.value), t);
  }, [rowAt, gridCols, types, buffer, deleted, restored, t]);

  const byName = useMemo(() => Object.fromEntries(card.map((c) => [c.name, c])), [card]);
  const drawHeader = useCallback<DrawHeaderCallback>((args) => {
    const { ctx, rect, column } = args;
    const name = column.id as string;
    ctx.fillStyle = t.background;
    ctx.fillRect(rect.x, rect.y, rect.width, rect.height);
    const x = rect.x + 8;
    ctx.fillStyle = t.fg;
    ctx.font = "600 13px Inter Variable, sans-serif";
    ctx.textBaseline = "alphabetic";
    if (name === ROW_COL) {
      ctx.textAlign = "right";
      ctx.fillStyle = t.muted;
      ctx.fillText("#", rect.x + rect.width - 8, rect.y + 20);
      ctx.textAlign = "left";
      return;
    }
    const arrow = sort?.column === name ? (sort.dir === "asc" ? " ↑" : " ↓") : "";
    ctx.fillText(clip(ctx, name + arrow, rect.width - 16), x, rect.y + 18);
    const info = byName[name];
    ctx.font = "11px Inter Variable, sans-serif";
    ctx.fillStyle = t.muted;
    const sub = `${typeLabel(types[name] ?? "VARCHAR")}${info ? ` · ${info.missing_pct}% missing` : ""}`;
    ctx.fillText(clip(ctx, sub, rect.width - 16), x, rect.y + 32);
    const counts = info?.histogram?.counts ?? info?.top_values?.map((v) => v.count) ?? [];
    if (counts.length) {
      const top = Math.max(...counts) || 1;
      const w = Math.max(1, (rect.width - 16) / counts.length);
      ctx.fillStyle = t.chart3;
      counts.forEach((c, i) => {
        const h = Math.max(c > 0 ? 1 : 0, (c / top) * 14);
        ctx.fillRect(x + i * w, rect.y + rect.height - 6 - h, Math.max(1, w - 1), h);
      });
    }
  }, [t, byName, types, sort]);

  const theme = useMemo<Partial<Theme>>(() => ({
    accentColor: t.accent, accentLight: t.accentSoft, textDark: t.fg, textMedium: t.muted, textLight: t.muted,
    textHeader: t.fg, bgCell: t.card, bgCellMedium: t.mutedBg, bgHeader: t.background, bgHeaderHasFocus: t.background,
    bgHeaderHovered: t.background, borderColor: t.border, horizontalBorderColor: t.border, headerBottomBorderColor: t.borderStrong,
    fontFamily: "Inter Variable, sans-serif", baseFontStyle: "13px", headerFontStyle: "600 13px", editorFontSize: "13px",
    cellHorizontalPadding: 10,
  }), [t]);

  const getRowThemeOverride = useCallback((row: number): Partial<Theme> | undefined => {
    const at = rowAt(row);
    if (at?.kind === "row" && ((at.row.quarantined && !restored.has(at.row._row_id)) || deleted.has(at.row._row_id))) {
      return { textDark: t.muted };
    }
    return undefined;
  }, [rowAt, restored, deleted, t]);

  const onCellEdited = useCallback(([col, row]: Item, value: EditableGridCell) => {
    const at = rowAt(row);
    const name = gridCols[col]?.id as string;
    if (!at || name === ROW_COL || value.kind !== GridCellKind.Text) return;
    if (at.kind === "new") onEdit({ rowId: null, tempId: at.temp, column: name, value: value.data, old: null });
    else onEdit({ rowId: at.row._row_id, tempId: null, column: name, value: value.data, old: at.row.cells[name] });
  }, [rowAt, gridCols, onEdit]);

  const onSelectionChange = (s: GridSelection) => {
    setSel(s);
    const r: Rectangle | undefined = s.current?.range;
    const info: GridSelectionInfo = { rowIds: [], newRows: [], cells: 0, current: null, quarantined: [] };
    if (r) {
      for (let row = r.y; row < r.y + r.height; row++) {
        const at = rowAt(row);
        if (!at) continue;
        if (at.kind === "new") info.newRows.push(at.temp);
        else {
          info.rowIds.push(at.row._row_id);
          if (at.row.quarantined) info.quarantined.push(at.row._row_id);
        }
      }
      info.cells = r.height * Math.max(0, Math.min(r.x + r.width, gridCols.length) - Math.max(r.x, 1));
      const [cc, cr] = s.current!.cell;
      const at = rowAt(cr);
      info.current = {
        rowId: at?.kind === "row" ? at.row._row_id : null,
        tempId: at?.kind === "new" ? at.temp : null,
        column: cc > 0 ? (gridCols[cc]?.id as string) : null,
      };
    }
    onSelection(info);
  };

  if (error) return <p className="p-6 text-destructive">{error}</p>;
  return (
    <div className="min-h-0 flex-1" data-testid="csv-grid">
      {columns.length > 0 && (
        <DataEditor
          ref={editor}
          columns={gridCols}
          rows={newRows.length + total}
          getCellContent={getCellContent}
          getCellsForSelection
          onCellEdited={onCellEdited}
          drawCell={drawCell}
          drawHeader={drawHeader}
          getRowThemeOverride={getRowThemeOverride}
          headerHeight={56}
          rowHeight={32}
          freezeColumns={1}
          rowMarkers="none"
          theme={theme}
          gridSelection={sel}
          onGridSelectionChange={onSelectionChange}
          onHeaderClicked={(col) => {
            const name = gridCols[col]?.id as string;
            if (!name || name === ROW_COL) return;
            if (sort?.column !== name) onSort({ column: name, dir: "asc" });
            else if (sort.dir === "asc") onSort({ column: name, dir: "desc" });
            else onSort(null);
          }}
          onVisibleRegionChanged={(range) => {
            const first = Math.max(0, range.y - newRows.length);
            for (let p = Math.floor(first / PAGE); p <= Math.floor((first + range.height) / PAGE); p++) load(p, viewKeyRef.current);
          }}
          smoothScrollX
          smoothScrollY
          width="100%"
          height="100%"
        />
      )}
    </div>
  );
});

/** Draw a cell's mark over its content: a server mark, "unsaved" for a pending edit (`invalid` when it
 * doesn't fit the type), or "struck" for a row number. Glide reuses the context for the next cell and
 * caches the styles it set, so this leaves the context as it found it; before, a column's later cells
 * drew their text in the accent colour after a pending edit's dot. */
export function drawMarks(ctx: CanvasRenderingContext2D, rect: Rectangle, mark: string | undefined, invalid: boolean,
                          t: Record<"accent" | "info" | "warning" | "destructive" | "muted", string>) {
  ctx.save();
  try {
    paintMark(ctx, rect, mark, invalid, t);
  } finally {
    ctx.restore();
  }
}

function paintMark(ctx: CanvasRenderingContext2D, rect: Rectangle, mark: string | undefined, invalid: boolean,
                   t: Record<"accent" | "info" | "warning" | "destructive" | "muted", string>) {
  if (mark === "struck") line(ctx, rect.x + 12, rect.y + rect.height / 2, rect.x + rect.width - 8, rect.y + rect.height / 2, t.muted, 1);
  else if (mark === "unsaved") {
    // Unsaved: an accent outline and a dot in the top-left corner, so it differs from a selection by shape.
    ctx.strokeStyle = t.accent;
    ctx.lineWidth = 1;
    ctx.strokeRect(rect.x + 0.5, rect.y + 0.5, rect.width - 1, rect.height - 1);
    ctx.fillStyle = t.accent;
    ctx.beginPath();
    ctx.arc(rect.x + 5, rect.y + 5, 2, 0, Math.PI * 2);
    ctx.fill();
    if (invalid) underline(ctx, rect, t.destructive);
  } else if (mark === "changed") line(ctx, rect.x, rect.y + 1, rect.x + rect.width, rect.y + 1, t.info, 2);
  else if (mark === "flagged") {
    ctx.setLineDash([3, 2]);
    ctx.strokeStyle = t.warning;
    ctx.strokeRect(rect.x + 1.5, rect.y + 1.5, rect.width - 3, rect.height - 3);
  } else if (mark === "invalid") underline(ctx, rect, t.destructive);
}

function line(ctx: CanvasRenderingContext2D, x1: number, y1: number, x2: number, y2: number, color: string, width: number) {
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
}

function underline(ctx: CanvasRenderingContext2D, rect: Rectangle, color: string) {
  line(ctx, rect.x + 8, rect.y + rect.height - 7, rect.x + rect.width - 8, rect.y + rect.height - 7, color, 1);
}

function clip(ctx: CanvasRenderingContext2D, text: string, width: number): string {
  if (ctx.measureText(text).width <= width) return text;
  let s = text;
  while (s.length > 1 && ctx.measureText(s + "…").width > width) s = s.slice(0, -1);
  return s + "…";
}
