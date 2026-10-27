// The dashboard's global filter (PRD DASH-5), one per dataset: clicking a bar, slice or cell sets it,
// clicking the same element again or the chip's × clears it. Widgets that inherit it re-query. A new
// version checks it against its data card and clears a filter that no longer means anything.
import { create } from "zustand";
import type { DataCard, FilterClause, Widget } from "@/api/types";

interface FilterState {
  byDataset: Record<string, FilterClause | null>;
  toggle: (datasetId: string, clause: FilterClause) => void;
  clear: (datasetId: string) => void;
}

const same = (a: FilterClause | null | undefined, b: FilterClause) => !!a && a.col === b.col && String(a.value) === String(b.value);

export const useFilters = create<FilterState>((set) => ({
  byDataset: {},
  toggle: (datasetId, clause) =>
    set((s) => ({ byDataset: { ...s.byDataset, [datasetId]: same(s.byDataset[datasetId], clause) ? null : clause } })),
  clear: (datasetId) => set((s) => ({ byDataset: { ...s.byDataset, [datasetId]: null } })),
}));

export const useGlobalFilter = (datasetId: string) => useFilters((s) => s.byDataset[datasetId] ?? null);

/** The filter a widget's query applies: the global one, unless the widget opts out or the filter is on
 * the widget's own category (a chart doesn't filter itself; its clicked bar keeps the accent instead,
 * UI/UX brief §4.4). The widget and "How do you know?" both use it, so the SQL shown is the SQL run. */
export function appliedFilter(widget: Pick<Widget, "spec">, filter: FilterClause | null): FilterClause | null {
  if (!filter || widget.spec.scope.rows.inherit_global_filters === false) return null;
  return filter.col === String(widget.spec.scope.columns.x) ? null : filter;
}

/** Why the filter means nothing on this data card's version, or null when it still applies: its column
 * is gone, or the card lists every value of the column and its value isn't one of them. */
export function filterGone(clause: FilterClause, card: DataCard): string | null {
  const col = card.columns.find((c) => c.name === clause.col);
  if (!col) return `v${card.version} has no column ${clause.col}`;
  const values = col.top_values;
  if (values && values.length >= col.distinct && !values.some((v) => sameValue(v.value, clause.value))) {
    return `no row of v${card.version} has ${clause.col} = ${String(clause.value)}`;
  }
  return null;
}

/** The data card lists values as text ("1", "True"); a clicked value comes typed (1, true). */
function sameValue(listed: unknown, clicked: unknown): boolean {
  const a = String(listed), b = String(clicked);
  if (a.toLowerCase() === b.toLowerCase()) return true;
  return a.trim() !== "" && b.trim() !== "" && Number.isFinite(Number(a)) && Number(a) === Number(b);
}
