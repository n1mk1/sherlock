// ML runs (TRD §4.8, §6.5, §6.6, §6.8). With cuts 4 and 7, "What drives this?" runs with Auto only.
// A run starts from chat (`ask_why`); its model card shows it, and runs it again once it's outdated.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "./client";
import type { ChartSpec, Progress } from "./types";

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
  split: { kind: string; folds: number; seed: number; group?: string | null };
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
  scope: ChartSpec["scope"];
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
  version: number;
  recipe: string;
  method: string;
  scope: ChartSpec["scope"];
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

export const mlKeys = {
  run: (rid: string) => ["run", rid] as const,
};

export const METRIC_LABELS: Record<string, string> = { accuracy: "Accuracy", macro_f1: "Macro F1", r2: "R²" };

/** Accuracy and F1 as percentages; R² as a number. */
export const fmtMetric = (metric: string, v: number) => (metric === "r2" ? v.toFixed(2) : `${(v * 100).toFixed(1)}%`);

export function useRun(runId: string | null | undefined) {
  return useQuery({
    queryKey: mlKeys.run(runId ?? ""),
    enabled: !!runId,
    queryFn: () => request<Run>("GET", `/api/v1/runs/${runId}`),
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
  return {
    // An outdated run again on the current version: a new run with the same recipe, scope and params
    // (TRD §4.8 `POST /runs`), or the cached one when nothing it reads changed.
    rerun: useMutation({
      mutationFn: (run: Run) => request<Run>("POST", `/api/v1/datasets/${datasetId}/runs`, {
        recipe: run.recipe, method: run.method, scope: run.scope, params: run.params,
      }),
      onSuccess: (run) => qc.setQueryData(mlKeys.run(run.id), run),
    }),
    wrongRows: useMutation({
      mutationFn: (runId: string) =>
        request<{ selection_id: string; row_count: number; label: string }>("POST", `/api/v1/runs/${runId}/wrong-rows`),
    }),
  };
}
