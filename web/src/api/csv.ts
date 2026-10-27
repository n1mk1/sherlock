// The CSV tab's API (TRD §4.3, §4.4): row pages, find, edits, step detail and undo, scoped cleaning,
// selections. The grid keeps its own page cache, so pages are plain requests, not queries.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { request } from "./client";
import { keys } from "./queries";
import type { Column, Dataset } from "./types";

export interface RowsPage {
  version: number;
  total: number;
  columns: Column[];
  rows: { _row_id: number; cells: Record<string, unknown>; marks: Record<string, string>; quarantined: boolean; quarantine_reason?: string | null }[];
}

export interface Sort {
  column: string;
  dir: "asc" | "desc";
}

export function fetchRows(datasetId: string, version: number, offset: number, limit: number, sort: Sort | null,
                          selection: string | null): Promise<RowsPage> {
  const q = new URLSearchParams({ version: String(version), offset: String(offset), limit: String(limit) });
  if (sort) q.set("sort", `${sort.column}:${sort.dir}`);
  if (selection) q.set("selection", selection);
  return request<RowsPage>("GET", `/api/v1/datasets/${datasetId}/rows?${q}`);
}

export interface FindResult {
  count: number;
  first_matches: { row_id: number; column: string; value?: unknown }[];
}

export function find(datasetId: string, q: string): Promise<FindResult> {
  return request<FindResult>("GET", `/api/v1/datasets/${datasetId}/find?q=${encodeURIComponent(q)}&all=true`);
}

export function makeSelection(datasetId: string, rowIds: number[], label?: string) {
  return request<{ selection_id: string; row_count: number }>("POST", `/api/v1/datasets/${datasetId}/selections`,
    { row_ids: rowIds, ...(label ? { label } : {}) });
}

export interface StepDetail {
  id: string;
  no: number;
  kind: string;
  summary: string;
  from_version: number;
  to_version: number;
  column_targets: string[];
  code: string | null;
  notebook_code: string;
  edits: {
    edits: { row_id: number; column: string; value: unknown }[];
    new_rows: { temp_id: string; row_id: number; cells: Record<string, unknown> }[];
    deleted_row_ids: number[];
    restore_row_ids: number[];
  } | null;
  impact: {
    rows_in: number; rows_out: number; cells_changed: number; quarantined: number; rows_added: number; rows_deleted: number;
    before_after: { row_id: number; column: string; old: string | null; new: string | null }[];
  };
  confidence: number | null;
  gate: string | null;
  flag_reason: string | null;
  decisions: { question: string; chosen: string; alternatives?: string[]; reason?: string; asked?: string }[];
  undone_step_id: string | null;
  replayed_step_ids: string[] | null;
  created_by: string;
  created_at: string;
  active: boolean;
}

export interface SaveResult {
  step: StepDetail;
  version: number;
  new_row_ids: Record<string, number>;
}

export interface Conflict {
  row_id: number;
  column: string;
  mine: unknown;
  theirs: unknown;
}

export type UndoAnswer =
  | { confirm_required: true; replay_needed: number[]; warning: "typing" | null }
  | { step: StepDetail; version: number };

/** After a commit: the dataset, its steps, rows and data card are for the old version. */
export function useAfterCommit(datasetId: string) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: keys.dataset(datasetId) });
    qc.invalidateQueries({ queryKey: keys.steps(datasetId) });
    qc.invalidateQueries({ queryKey: ["datacard", datasetId] });
    qc.invalidateQueries({ queryKey: keys.datasets });
  };
}

export function useSaveEdits(datasetId: string) {
  const after = useAfterCommit(datasetId);
  return useMutation({
    mutationFn: (batch: object) => request<SaveResult>("POST", `/api/v1/datasets/${datasetId}/edits`, batch),
    onSuccess: after,
  });
}

export function useUndo(datasetId: string) {
  const after = useAfterCommit(datasetId);
  return useMutation({
    mutationFn: ({ stepId, base, confirm }: { stepId: string; base: number; confirm: boolean }) =>
      request<UndoAnswer>("POST", `/api/v1/datasets/${datasetId}/steps/${stepId}/undo`, { base_version: base, confirm }),
    onSuccess: (r) => {
      if ("step" in r) after();
    },
  });
}

export function busyReason(d: Dataset): string | null {
  if (d.status === "profiling") return "The CSV is still being profiled.";
  if (d.status === "cleaning") return "Cleaning is running.";
  return null;
}
