// Domain shapes from TRD §4 and §6. Routes that the API types with pydantic come from the generated
// schema (schema.d.ts); these cover the routes that answer plain JSON objects.
import type { components } from "./schema";

export type Dataset = components["schemas"]["Dataset"];
export type DatasetStatus = Dataset["status"];
export type Settings = components["schemas"]["Settings"];
export type Me = components["schemas"]["Me"];
export type Tab = "csv" | "dashboard" | "flow";

export type JobKind =
  | "profile" | "clean" | "build_dashboard" | "stories" | "ml_run" | "cascade" | "undo" | "export_notebook" | "purge";
export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export interface Progress {
  step: number;
  of: number;
  label: string;
  pct: number;
}

export interface Job {
  id: string;
  dataset_id: string | null;
  kind: JobKind;
  status: JobStatus;
  progress: Progress;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  result: Record<string, unknown> | null;
}

export interface Issue {
  id: string;
  detector: string;
  column: string | null;
  count: number;
  severity: number;
  proposal: string | null;
  examples: unknown[];
  details: Record<string, unknown>;
}

export interface ColumnCard {
  name: string;
  type: string;
  role: string;
  missing: number;
  missing_pct: number;
  distinct: number;
}

export interface DataCard {
  version: number;
  row_count: number;
  column_count: number;
  quarantined: number;
  columns: ColumnCard[];
  issues: Issue[];
  target_candidates: string[];
  leakage_candidates: { column: string; target: string; reason: string }[];
}

export interface JobLogEntry {
  job_id: string;
  ts: string;
  level: string;
  icon: string;
  text: string;
  column?: string | null;
  candidates?: { label: string; chosen: boolean }[];
  gate?: "commit" | "flag" | "skip";
  step_id?: string;
  step_no?: number;
  confidence?: number;
  checks?: Record<string, string>;
  detail?: string;
  issue_id?: string;
  outcome?: string; // the client's merge of a "running" line with its result
  [key: string]: unknown;
}

export interface Step {
  id: string;
  no: number;
  kind: string;
  summary: string;
  gate: string | null;
  confidence: number | null;
  impact: { cells_changed: number; quarantined: number; rows_added: number; rows_deleted: number };
  created_by: string;
  active: boolean;
}

export interface CleaningReport {
  job_id: string;
  status: JobStatus;
  from_version: number | null;
  to_version: number | null;
  ended_by: "done" | "steps" | "time" | "tokens" | "stopped" | "error";
  waited_for_model_s: number;
  attempted: number;
  budget: { max_steps: number | null; max_seconds: number | null };
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  counts: { found: number; fixed: number; flagged: number; skipped: number; rows_deleted: number };
  steps: {
    step_id: string; no: number; summary: string; gate: string; confidence: number | null; flag_reason: string | null;
    impact: Step["impact"];
  }[];
  skipped: { issue_id: string; column: string | null; detector: string; reason: string }[];
  hand_edited_skipped: { row_id: number; column: string }[];
  decisions: { step_id: string; question: string; chosen: string; reason: string }[];
}

// Server-sent events (TRD §5.1). Every event's data carries dataset_id.
export interface DatasetStatusEvent {
  dataset_id: string;
  status: DatasetStatus;
  current_version: number;
  error?: string;
}

export interface JobProgressEvent extends Progress {
  dataset_id: string;
  job_id: string;
  kind: JobKind;
}
