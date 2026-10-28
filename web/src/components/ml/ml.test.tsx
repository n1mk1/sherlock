import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fmtMetric, type ModelCard, type Run } from "@/api/ml";
import { mockApi, renderAt } from "@/test/render";
import { ModelCardDrawer } from "./ModelCardDrawer";

afterEach(() => vi.unstubAllGlobals());

const SCOPE = { columns: { target: "survived" }, rows: { inherit_global_filters: false } };

const CARD: ModelCard = {
  run_id: "run_1", recipe: "driver_analysis", method: "auto", chosen_model: "gradient_boosting", task: "classification",
  target: "survived", features_used: ["sex", "age"], excluded: [{ column: "boat", reason: "records the outcome" }],
  rows: { total: 1309, with_target: 1309, blank_target: 0, used: 1309, train: 1309 },
  split: { kind: "stratified_kfold", folds: 5, seed: 0 },
  baselines: [{ name: "best one-column rule: sex", metric: "accuracy", value: 0.78, column: "sex" }],
  model: { metric: "accuracy", value: 0.804, ci: [0.78, 0.83], folds: [0.8, 0.81], lift_over_best_baseline: 0.024 },
  alternatives: [], verdict: "beats_baseline", verdict_text: "Beats the best simple rule by 2.4 points.",
  importance: [{ column: "sex", value: 1 }, { column: "age", value: 0.22 }], warnings: [], limits: ["observational data"],
  sample: null, version: 2, scope: SCOPE, params: { cv_folds: 5, time_budget_s: 60 },
  repro: { libraries: {}, code_path: "repro.py" },
  confusion: { labels: ["0", "1"], matrix: [[710, 99], [157, 343]] }, misclassified: 256,
};

const RUN: Run = {
  id: "run_1", dataset_id: "ds_1", version: 2, recipe: "driver_analysis", method: "auto",
  scope: SCOPE, params: { cv_folds: 5, time_budget_s: 60 }, status: "done", job_id: "job_1", target: "survived",
  error: null, progress: null, summary: null, model_card: CARD,
};

describe("the model card", () => {
  it("formats metrics as the model card does", () => {
    expect(fmtMetric("accuracy", 0.8044)).toBe("80.4%");
    expect(fmtMetric("r2", 0.4567)).toBe("0.46");
  });

  it("shows the verdict, the importance and the confusion matrix with who it got wrong", async () => {
    mockApi({ "GET /api/v1/runs/run_1": RUN });
    renderAt(<ModelCardDrawer datasetId="ds_1" runId="run_1" onClose={() => {}} />);
    expect(await screen.findByText("Beats the best simple rule by 2.4 points.")).toBeInTheDocument();
    expect(screen.getByText("0.22")).toBeInTheDocument();
    expect(screen.getByLabelText("Confusion matrix: actual by predicted")).toBeInTheDocument();
    expect(screen.getByTitle("actual 1, predicted 0: 157")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Who did it get wrong\? \(256 rows\)/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Re-run" })).toBeNull(); // only an outdated run offers it
  });

  it("runs an outdated analysis again with the same recipe, scope and params, then shows the new run", async () => {
    const calls = mockApi({
      "GET /api/v1/runs/run_1": { ...RUN, status: "outdated" },
      "POST /api/v1/datasets/ds_1/runs": { ...RUN, id: "run_2", version: 3, status: "running", model_card: null },
      "GET /api/v1/runs/run_2": { ...RUN, id: "run_2", version: 3, status: "running", model_card: null },
    });
    renderAt(<ModelCardDrawer datasetId="ds_1" runId="run_1" onClose={() => {}} />);
    expect(await screen.findByText(/Outdated: the data changed after this ran/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Re-run" }));
    expect(await screen.findByText("The model card is written when the analysis finishes.")).toBeInTheDocument();
    const post = calls.mock.calls.find(([u, i]) => String(u).endsWith("/datasets/ds_1/runs") && i?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      recipe: "driver_analysis", method: "auto", scope: SCOPE, params: { cv_folds: 5, time_budget_s: 60 },
    });
    await waitFor(() => expect(calls.mock.calls.some(([u]) => String(u).endsWith("/runs/run_2"))).toBe(true));
  });
});
