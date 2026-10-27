// Domain shapes from TRD §4 and §6. Routes that the API types with pydantic come from the generated
// schema (schema.d.ts); these cover the routes that answer plain JSON objects.
import type { components } from "./schema";

export type Dataset = components["schemas"]["Dataset"];
export type DatasetStatus = Dataset["status"];
export type Settings = components["schemas"]["Settings"];
export type Me = components["schemas"]["Me"];
// One check in the detector catalog (`GET /detectors`, PRD CLEAN-12).
export type Detector = components["schemas"]["Detector"];
// A check of your own as you save it (`POST /datasets/{id}/rules`, PRD CLEAN-13).
export type RuleIn = components["schemas"]["RuleIn"];
export type RuleKind = RuleIn["kind"];

export type JobKind =
  | "profile" | "clean" | "ml_run" | "undo" | "export_notebook" | "purge" | "review_issues";
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
  level?: Level | null; // code's default level (PRD CLEAN-8c); null for a column that's never changed
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

// The cleaning plan (TRD §4.4, PRD CLEAN-8a): what Clean with AI will try, editable before it starts.
export type PlanModule = "yours" | "types" | "missing" | "text" | "records" | "outliers" | "other" | "kept";
// What a finding does to an analysis (PRD CLEAN-8c), most severe first.
export type Level = "breaks" | "skews" | "splits" | "check" | "cosmetic";

export interface CleanPlanItem {
  id: string;
  source: "sherlock" | "you" | "chat";
  key: string | null;
  detector: string;
  column: string | null;
  count: number | null;
  severity: number | null;
  action: string;
  instruction: string | null;
  examples: unknown[];
  ticked: boolean;
  change: boolean; // false for leakage and ID columns: marked, never changed
  reason?: string;
  module: PlanModule;
  // Its level (null for a step you added or a column that's never changed), the reason a review gave
  // (no digits), and where the level came from.
  sev?: Level | null;
  sev_reason?: string | null;
  sev_source?: "model" | "default" | null;
  likely_real?: boolean;
  // An ambiguous-dates item: the order the user picked, up to three values read both ways,
  // and whether every date reads both ways, so it's cleaned only with an order.
  date_order?: "dmy" | "mdy" | null;
  both_ways?: { value: string; day_first: string; month_first: string }[];
  needs_order?: boolean;
}

export interface CleanPlan {
  id: string;
  dataset_id: string;
  version: number;
  status: "draft" | "started" | "discarded";
  source: "user" | "after_upload";
  job_id: string | null;
  items: CleanPlanItem[];
  scope: PlanScope | null; // the rows it was opened for (new-rows toast, chat); null is the whole dataset
  created_at: string;
  updated_at: string;
  notes?: string[];   // what a merge onto a newer version changed
  // The version's severity review: rated, still running, or every item on code's default level.
  review?: "ready" | "running" | "default";
  suggestions?: Suggestion[]; // checks Sherlock suggests, not run until kept (PRD CLEAN-14)
}

// A suggested check: the model wrote it, code counted it on the current version.
export interface Suggestion {
  id: string;
  kind: RuleKind;
  column: string;
  params: Record<string, unknown>;
  action: RuleIn["action"];
  words: string;
  reason?: string;
  count: number | null;
  error: string | null;
  sev: Level;
  sev_reason?: string | null;
  summary?: string;   // what a PATCH changed, written by code
}

export interface PlanScope {
  kind: "selection" | "new_rows";
  selection_id: string | null;
  row_ids: number[] | null;
  rows: number | null;
}

export type PlanOp =
  | { op: "tick" | "untick" | "remove"; item_id: string }
  | { op: "tick_module" | "untick_module"; module: PlanModule }
  | { op: "tick_level" | "untick_level"; level: Level } // every fix of a level (PRD CLEAN-8c)
  | { op: "add_rule"; rule: RuleIn } // a check of your own (PRD CLEAN-13)
  | { op: "keep_suggestion" | "dismiss_suggestion"; rule_id: string } // a suggested check (PRD CLEAN-14)
  | { op: "set_instruction"; item_id: string; instruction: string | null } // null puts Sherlock's wording back
  | { op: "set_date_order"; item_id: string; order: "dmy" | "mdy" | null } // null clears the order
  | { op: "add"; column: string | null; instruction: string };

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
  note?: string | null; // the model's sentence about the step, only when it has no digits
  calls?: { count: number; models: string[]; latency_ms: number } | null; // the issue's model calls
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
  counts: {
    found: number; fixed: number; flagged: number; skipped: number; rows_deleted: number;
    // What became of each issue (PRD CLEAN-6); marked-not-changed is counted apart.
    checked_and_kept?: number; couldnt_fix?: number; not_attempted?: number; kept_by_design?: number;
  };
  steps: {
    step_id: string; no: number; summary: string; gate: string; confidence: number | null; flag_reason: string | null;
    impact: Step["impact"];
  }[];
  skipped: {
    issue_id: string; column: string | null; detector: string; reason: string;
    skip_kind?: string; level?: Level | null;
  }[];
  hand_edited_skipped: { row_id: number; column: string }[];
  decisions: { step_id: string; question: string; chosen: string; reason: string; asked?: string }[];
  // A run from a cleaning plan: each step the user added or fix they rewrote, and what became of it.
  your_steps?: {
    item_id: string; column: string | null; instruction: string; source: string; detector: string;
    outcome: "fixed" | "flagged" | "skipped" | "not_reached"; reason?: string; step_id?: string; step_no?: number;
  }[];
}

// A chat chart block's spec and result (TRD §6.3 ChartSpec): the view the chart adapter draws and the
// query's rows. `scope` and `op` say what was asked, for "How do you know?".
export type ViewType = "bar" | "line" | "area" | "pie" | "ring" | "kpi" | "table" | string;

export interface ChartSpec {
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

export interface Column {
  name: string;
  type: string;
}

export interface ChartData {
  version: number;
  columns: Column[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  highlight?: Highlight;
}

// Chat (TRD §4.9, §5.3).
export type Run =
  | { type: "text"; text: string }
  | { type: "chip"; id: string; key: string | null; value: string; raw?: unknown; unverified: boolean }
  | { type: "label"; ref: string; text?: string };

/** A citation of a web source in a chat answer (TRD §8.2 web_context): its number is the source's, not
 * data. Only chat answers have it. */
export type CiteRun = { type: "cite"; n: number; url: string; title: string };
export type AnswerRun = Run | CiteRun;

export interface AnswerBody {
  blocks: { type: "paragraph" | "bullets"; runs: AnswerRun[] }[];
}

export type AnswerBlock =
  | { type: "number"; value: unknown; formatted: string; format: string; label: string; result?: string }
  | { type: "table"; columns: Column[]; rows: unknown[][]; total: number; selection_id?: string | null; result?: string }
  | { type: "chart"; spec: ChartSpec; data: ChartData; result?: string }
  | { type: "text"; body: AnswerBody; labeled?: "general" | "web"; web?: "context" | "meaning" }
  | { type: "web_sources"; query: string; cached: boolean; results: WebResult[] };

/** One web search result as Tavily returned it (TRD §3.6): its excerpt is verbatim, numbers included. */
export interface WebResult {
  n: number;
  title: string;
  url: string;
  domain: string;
  snippet: string;
  retrieved_at: string;
}

export interface Source {
  kind: "sql" | "run" | "step" | "help" | "general" | "web";
  run_id?: string;
  url?: string; // a web source's address
  title?: string;
  sql?: string | null;
  step_id?: string;
  label: string;
}

export interface MessageAction {
  kind: "open_rows" | "open_export" | "open_model_card";
  block_index?: number;
  run_id?: string;
  selection_id?: string;
  options?: Partial<Record<"include_data" | "include_runs", boolean>>;
}

/** A change chat proposed (TRD §6.8): nothing applies until it's approved. */
export interface Proposal {
  id: string;
  kind: "edit_cells" | "clean_selection" | "clean_step" | "computed_column";
  base_version: number;
  status: "pending" | "approved" | "rejected" | "expired";
  summary: string;
  edits?: { row_id: number; column: string; value: string | null; before: unknown }[];
  scope?: { kind: "all" | "selection"; selection_id: string | null };
  impact: { cells_changed: number; rows_affected: number };
  result_step_id?: string | null;
}

export interface PlanStep {
  text: string;
  status: "pending" | "running" | "done" | "failed";
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
  proposal?: Proposal;
  plan?: { steps: PlanStep[] };
  created_at: string;
  /** The dataset version the message read; null for a message written before it was kept. */
  version?: number | null;
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
