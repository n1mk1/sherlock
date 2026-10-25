import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fmtMetric, type Run } from "@/api/ml";
import type { Widget } from "@/api/types";
import { BlockView } from "@/components/chat/Blocks";
import { WidgetShell } from "@/components/dashboard/WidgetShell";
import { mockApi, renderAt } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());

const DRIVER: Widget = {
  id: "wdg_9", dataset_id: "ds_1", title: "What drives survived?", status: "ready", error: null, created_by: "builder",
  version_built: 2, score: null, point: null, deleted_at: null, run_id: "run_1",
  spec: {
    scope: { columns: { target: "survived" }, rows: { inherit_global_filters: false } },
    op: { type: "ml", recipe: "driver_analysis", method: "auto", params: { cv_folds: 5, time_budget_s: 60 } },
    view: { type: "importance", options: {} },
  },
};

const RUN: Run = {
  id: "run_1", dataset_id: "ds_1", widget_id: "wdg_9", version: 2, recipe: "driver_analysis", method: "auto",
  scope: DRIVER.spec.scope, params: { cv_folds: 5, time_budget_s: 60 }, status: "done", job_id: "job_1", target: "survived",
  error: null, progress: null,
  summary: {
    verdict: "beats_baseline", verdict_text: "Beats the best simple rule by 2.4 points.", metric: "accuracy", value: 0.804,
    best_baseline: { name: "best one-column rule: sex", metric: "accuracy", value: 0.78, column: "sex" },
    chosen_model: "gradient_boosting", chosen_label: "Gradient boosting", rows: 1309, excluded: 3,
    task: "classification", misclassified: 256, views: ["importance", "confusion", "roc"],
  },
  model_card: null,
};

const shell = (widget: Widget) => (
  <WidgetShell widget={widget} version={2} columns={["sex", "survived"]} collapsed={false} onToggleCollapse={() => {}} onExplain={() => {}} />
);

describe("analysis widgets", () => {
  it("formats metrics as the model card does", () => {
    expect(fmtMetric("accuracy", 0.8044)).toBe("80.4%");
    expect(fmtMetric("r2", 0.4567)).toBe("0.46");
  });

  it("shows the verdict and the importance bars of a finished run", async () => {
    mockApi({
      "GET /api/v1/runs/run_1": RUN,
      "GET /api/v1/runs/run_1/results": {
        version: 2, columns: [{ name: "feature", type: "VARCHAR" }, { name: "importance", type: "DOUBLE" }],
        rows: [["sex", 1], ["age", 0.22]], row_count: 2, truncated: false,
      },
      "GET /api/v1/recipes": [],
      "GET /api/v1/datasets/ds_1/cards": [],
    });
    renderAt(shell(DRIVER));
    expect(await screen.findByText("Beats the best simple rule by 2.4 points.")).toBeTruthy();
    expect(await screen.findByLabelText("Factors by importance: sex, age")).toBeTruthy();
    expect(screen.getByText("0.22")).toBeTruthy();
  });

  it("draws the confusion matrix with the misclassified count", async () => {
    mockApi({
      "GET /api/v1/runs/run_1": RUN,
      "GET /api/v1/runs/run_1/results": (url: URL) => url.searchParams.get("view") === "confusion"
        ? { version: 2, columns: [], rows: [["0", "0", 710], ["0", "1", 99], ["1", "0", 157], ["1", "1", 343]], row_count: 4, truncated: false }
        : { version: 2, columns: [], rows: [["sex", 1]], row_count: 1, truncated: false },
      "GET /api/v1/recipes": [],
      "GET /api/v1/datasets/ds_1/cards": [],
    });
    renderAt(shell({ ...DRIVER, spec: { ...DRIVER.spec, view: { type: "confusion", options: {} } } }));
    expect(await screen.findByLabelText("Confusion matrix: actual by predicted")).toBeTruthy();
    expect(screen.getByTitle("actual 1, predicted 0: 157")).toBeTruthy();
    expect(screen.getByText("256")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "ROC" })).toBeTruthy();
  });

  it("sets general knowledge apart in a chat answer", () => {
    renderAt(<BlockView datasetId="ds_1" block={{ type: "text", labeled: "general", body: { blocks: [{ type: "paragraph", runs: [
      { type: "text", text: "In general (not from your data): " }, { type: "text", text: "Siblings or spouses aboard." }] }] } }} />);
    expect(screen.getByTitle("From the model's general knowledge, not computed from your data").textContent)
      .toContain("Siblings or spouses aboard.");
  });

  it("shows plain-language progress while it runs, and Outdated with Re-run after the data changed", async () => {
    let status: Run["status"] = "running";
    mockApi({
      "GET /api/v1/runs/run_1": () => ({ ...RUN, status, summary: status === "running" ? null : RUN.summary,
                                         progress: { step: 4, of: 6, label: "testing models", pct: 50 } }),
      "GET /api/v1/runs/run_1/results": { version: 2, columns: [], rows: [["sex", 1]], row_count: 1, truncated: false },
      "GET /api/v1/recipes": [],
      "GET /api/v1/datasets/ds_1/cards": [],
    });
    const view = renderAt(shell(DRIVER));
    expect(await screen.findByRole("status")).toBeTruthy();
    expect(screen.getByText(/testing models…/)).toBeTruthy();
    view.unmount();
    status = "outdated";
    renderAt(shell({ ...DRIVER, status: "outdated" }));
    await waitFor(() => expect(screen.getByText("Outdated")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Re-run" })).toBeTruthy();
  });
});
