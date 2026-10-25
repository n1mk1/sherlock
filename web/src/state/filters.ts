// The dashboard's global filter (PRD DASH-5), one per dataset: clicking a bar, slice or cell sets it,
// clicking the same element again or the chip's × clears it. Widgets that inherit it re-query.
import { create } from "zustand";
import type { FilterClause } from "@/api/types";

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
