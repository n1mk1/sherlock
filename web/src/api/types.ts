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
  histogram?: { bins: number[]; counts: number[] } | null;
  top_values?: { value: unknown; count: number }[] | null;
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
  column_targets?: string[];
  flag_reason?: string | null;
  undone_step_id?: string | null;
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

// Widgets (TRD §4.5, §6.3).
export type ViewType = "bar" | "line" | "area" | "pie" | "ring" | "kpi" | "table" | string;

export interface WidgetSpec {
  scope: {
    columns: { x?: string | null; y?: string | null; agg?: string | null; [k: string]: unknown };
    rows: { predicate?: string | null; selection_id?: string | null; inherit_global_filters?: boolean };
  };
  op: { type: "sql"; sql: string } | { type: "ml"; recipe: string; method: string; params: Record<string, unknown> };
  view: { type: ViewType; from?: string; options: Record<string, unknown> };
}

export interface Highlight {
  kind: "bar" | "point" | "cell" | "series";
  key: string;
}

export interface Widget {
  id: string;
  dataset_id: string;
  spec: WidgetSpec;
  title: string;
  status: "ready" | "outdated" | "error" | "building";
  error: string | null;
  run_id?: string | null; // an analysis widget's run (op.type = ml)
  created_by: "builder" | "user" | "chat";
  version_built: number;
  score: number | null;
  point: Highlight | null;
  deleted_at: string | null;
}

export interface Column {
  name: string;
  type: string;
}

export interface WidgetData {
  version: number;
  columns: Column[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  highlight?: Highlight;
}

export interface LayoutItem {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
  collapsed?: boolean;
}

export interface Layout {
  lg: LayoutItem[];
  md?: LayoutItem[];
  sm?: LayoutItem[];
}

export interface Explain {
  op: string;
  sql?: string;
  scope: WidgetSpec["scope"];
  version: number;
  recipe?: string;
}

/** The global filter (PRD DASH-5), in the rows API's filter JSON. */
export interface FilterClause {
  col: string;
  op: "eq";
  value: unknown;
}

// Chat (TRD §4.9, §5.3).
export type Run =
  | { type: "text"; text: string }
  | { type: "chip"; id: string; key: string | null; value: string; raw?: unknown; unverified: boolean }
  | { type: "label"; ref: string; text?: string };

export interface CardBody {
  blocks: { type: "paragraph" | "bullets"; runs: Run[] }[];
}

export type AnswerBlock =
  | { type: "number"; value: unknown; formatted: string; format: string; label: string; result?: string }
  | { type: "table"; columns: Column[]; rows: unknown[][]; total: number; selection_id?: string | null; result?: string; widget_id?: string }
  | { type: "chart"; spec: WidgetSpec; data: WidgetData; result?: string; widget_id?: string }
  | { type: "text"; body: CardBody };

export interface Source {
  kind: "sql" | "run" | "step" | "card" | "help";
  sql?: string | null;
  step_id?: string;
  label: string;
}

export interface MessageAction {
  kind: "pin" | "add_to_flow" | "open_rows" | "open_widget" | "open_export";
  block_index?: number;
  widget_id?: string;
  selection_id?: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  blocks: AnswerBlock[];
  sources: Source[];
  clarification?: { question: string; options: string[] };
  clarification_of?: string | null;
  actions?: MessageAction[];
  created_at: string;
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

// Story cards (TRD §4.6). `facts` carries the latest fact sheet's values, so chips render from it.
export interface Card {
  id: string;
  dataset_id: string;
  kind: "overview" | "widget" | "synthesis" | "direction" | "answer";
  widget_id: string | null;
  headline: CardBody;
  body: CardBody;
  fact_sheet_id: string | null;
  status: "ready" | "updating" | "outdated" | "sources_changed" | "building" | "failed";
  edited_by_user: boolean;
  changed_badge: boolean;
  suggestion: { headline: CardBody; body: CardBody } | null;
  version: number;
  narrated_by: string | null;
  updated_at: string;
  facts: Record<string, { formatted: string; label: string }>;
  related: { widget_id: string; title: string }[];
}

export interface Evidence {
  key?: string;
  value: unknown;
  formatted?: string;
  label: string;
  sql?: string | null;
  formula?: string | null;
  method?: string | null;
  from?: string[] | null;
  version: number;
  computed_at?: string;
  unverified?: boolean;
}
