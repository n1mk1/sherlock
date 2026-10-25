// ML recipes and runs (TRD §4.8, §6.5, §6.6, §6.8). With cuts 4 and 7, "What drives this?" runs
// with Auto only; the other recipes come back disabled with their reason.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "./client";
import { keys } from "./queries";
import type { FilterClause, Progress, WidgetData, WidgetSpec } from "./types";

export interface ParamSpec {
  type: "integer";
  default: number;
  minimum: number;
  maximum: number;
  title?: string;
}

export interface Recipe {
  id: string;
  label: string;
  group: "explain" | "predict" | "group" | "unusual" | "time";
  compatible: boolean;
  reason?: string;
  methods: { id: string; label: string; task: string[] }[];
  params?: { type: "object"; properties: Record<string, ParamSpec> };
  targets?: string[];
  min_rows?: number;
}

export interface Baseline {
  name: string;
  metric: string;
  value: number;
  column?: string;
}

export interface Excluded {
  column: string;
  reason: string;
}

export interface ModelCard {
  run_id: string;
  recipe: string;
  method: string;
  chosen_model: string;
  task: "classification" | "regression";
  target: string;
  features_used: string[];
  excluded: Excluded[];
  rows: { total: number; with_target: number; blank_target: number; used: number; train: number };
  split: { kind: string; folds: number; seed: number };
  baselines: Baseline[];
  model: { metric: string; value: number; ci: [number, number]; folds: number[]; lift_over_best_baseline: number; auc?: number; mae?: number };
  alternatives: { model: string; label: string; metric: string; value: number }[];
  verdict: "beats_baseline" | "weak" | "no_signal";
  verdict_text: string;
  importance: { column: string; value: number }[];
  warnings: { code: string; text: string; suggestion: string }[];
  limits: string[];
  sample: { seed: number; stratify_column: string | null; n: number } | null;
  version: number;
  scope: WidgetSpec["scope"];
  params: Record<string, number>;
  repro: { libraries: Record<string, string>; code_path: string };
  status?: RunStatus;
  // Classification only (out-of-fold predictions): the confusion matrix, the misclassified count, and
  // for two classes the ROC curve on the second class.
  confusion?: { labels: string[]; matrix: number[][] };
  misclassified?: number;
  roc?: { positive: string; auc: number; points: { fpr: number; tpr: number; threshold: number }[] };
}

export type RunStatus = "queued" | "running" | "done" | "failed" | "cancelled" | "outdated";

export interface Run {
  id: string;
  dataset_id: string;
  widget_id: string | null;
  version: number;
  recipe: string;
  method: string;
  scope: WidgetSpec["scope"];
  params: Record<string, number>;
  status: RunStatus;
  job_id: string | null;
  target: string | null;
  error: string | null;
  summary: {
    verdict: ModelCard["verdict"];
    verdict_text: string;
    metric: string;
    value: number;
    best_baseline: Baseline;
    chosen_model: string;
    chosen_label: string;
    rows: number;
    excluded: number;
    task: "classification" | "regression";
    misclassified: number | null;
    views: string[];
  } | null;
  progress: Progress | null;
  model_card?: ModelCard | null;
}

export interface RunRequest {
  recipe: string;
  method?: string;
  scope?: { columns?: Record<string, unknown>; rows?: Record<string, unknown> };
  params?: Record<string, number>;
  filters?: FilterClause[];
  widget_id?: string;
}

export interface Preview {
  target: string;
  targets: string[];
  task: "classification" | "regression";
  metric: string;
  columns: string[];
  features: string[];
  excluded: Excluded[];
  forced: Excluded[];
  rows: { total: number; with_target: number; blank_target: number; used: number };
  baselines: Baseline[];
  estimate_s: number;
  cached: string | null;
}

export type RunData = WidgetData & { run?: Run | null };

export const mlKeys = {
  recipes: (ds: string) => ["recipes", ds] as const,
  run: (rid: string) => ["run", rid] as const,
  results: (rid: string, view: string, feature: string | undefined, status: string) => ["run-results", rid, view, feature ?? "", status] as const,
  card: (rid: string, status: string) => ["model-card", rid, status] as const,
};

export const RUNNING: RunStatus[] = ["queued", "running"];
export const METRIC_LABELS: Record<string, string> = { accuracy: "Accuracy", macro_f1: "Macro F1", r2: "R²" };

/** Accuracy and F1 as percentages; R² as a number. */
export const fmtMetric = (metric: string, v: number) => (metric === "r2" ? v.toFixed(2) : `${(v * 100).toFixed(1)}%`);

export function useRecipes(datasetId: string, enabled = true) {
  return useQuery({
    queryKey: mlKeys.recipes(datasetId),
    enabled,
    queryFn: () => request<Recipe[]>("GET", `/api/v1/recipes?dataset_id=${encodeURIComponent(datasetId)}`),
    staleTime: 30_000,
  });
}

export function usePreview(datasetId: string, body: RunRequest | null) {
  return useQuery({
    queryKey: ["run-preview", datasetId, body],
    enabled: !!body,
    queryFn: () => request<Preview>("POST", `/api/v1/datasets/${datasetId}/runs/preview`, body),
    placeholderData: (prev) => prev, // keep the chips while a toggle re-checks
    retry: false,
  });
}

export function useRun(runId: string | null | undefined) {
  return useQuery({
    queryKey: mlKeys.run(runId ?? ""),
    enabled: !!runId,
    queryFn: () => request<Run>("GET", `/api/v1/runs/${runId}`),
  });
}

export function useRunResults(run: Run | undefined, view = "importance", feature?: string) {
  const ready = !!run && (run.status === "done" || run.status === "outdated");
  return useQuery({
    queryKey: mlKeys.results(run?.id ?? "", view, feature, run?.status ?? ""),
    enabled: ready && (view !== "partial_dependence" || !!feature),
    queryFn: () =>
      request<RunData & { of?: string; kind?: string }>(
        "GET", `/api/v1/runs/${run!.id}/results?view=${view}${feature ? `&feature=${encodeURIComponent(feature)}` : ""}`),
    retry: false,
  });
}

export function useRunCode(runId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["run-code", runId],
    enabled: !!runId && enabled,
    queryFn: () => request<{ python: string }>("GET", `/api/v1/runs/${runId}/code`),
  });
}

export function useRunActions(datasetId: string) {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.widgets(datasetId) });
    qc.invalidateQueries({ queryKey: ["widget-data"] });
  };
  return {
    start: useMutation({
      mutationFn: (body: RunRequest) => request<Run>("POST", `/api/v1/datasets/${datasetId}/runs`, body),
      onSuccess: (run) => {
        qc.setQueryData(mlKeys.run(run.id), run);
        refresh();
      },
    }),
    rerun: useMutation({
      mutationFn: (widgetId: string) => request<Run>("POST", `/api/v1/widgets/${widgetId}/rerun`),
      onSuccess: (run) => {
        qc.setQueryData(mlKeys.run(run.id), run);
        refresh();
      },
    }),
    wrongRows: useMutation({
      mutationFn: (runId: string) =>
        request<{ selection_id: string; row_count: number; label: string }>("POST", `/api/v1/runs/${runId}/wrong-rows`),
    }),
    cancel: useMutation({
      mutationFn: (runId: string) => request<void>("POST", `/api/v1/runs/${runId}/cancel`),
      onSuccess: (_, runId) => qc.invalidateQueries({ queryKey: mlKeys.run(runId) }),
    }),
  };
}
