import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Dataset, JobLogEntry } from "@/api/types";
import { ME, mockApi, renderAt } from "@/test/render";
import { collapse, mmss } from "./CleaningProgress";
import { ReportSummary } from "./CleaningReport";
import { OfferActions } from "./OfferActions";

afterEach(() => vi.unstubAllGlobals());

const DS = {
  id: "ds_1", name: "messy.csv", status: "offer", current_version: 2, row_count: 120, column_count: 4,
  created_at: "", last_opened_at: null, last_tab: null, error: null,
} as Dataset;

describe("cleaning screens", () => {
  it("merges a running line with its outcome", () => {
    const base = { job_id: "j", ts: "2026-10-24T00:00:00Z", level: "info" };
    const entries: JobLogEntry[] = [
      { ...base, icon: "running", text: "263 missing values", column: "age", issue_id: "i1", detail: "checking candidates" },
      { ...base, icon: "check", text: "Fills ages by title", column: "age", issue_id: "i1", gate: "commit", detail: "committed · step 2" },
      { ...base, icon: "skip", text: "Looks like an ID column", column: "name", issue_id: "i2" },
    ];
    const out = collapse(entries);
    expect(out).toHaveLength(2);
    expect(out[0]).toMatchObject({ text: "263 missing values", outcome: "Fills ages by title", gate: "commit" });
    expect(mmss(83)).toBe("01:23");
  });

  it("merges a running line with its outcome across a wait for the model", () => {
    const base = { job_id: "j", ts: "2026-10-24T00:00:00Z", level: "info" };
    const entries: JobLogEntry[] = [
      { ...base, icon: "running", text: "263 missing values", column: "age", issue_id: "i1", detail: "checking candidates" },
      { ...base, icon: "wait", text: "Waiting for the model…", level: "warn" },
      { ...base, icon: "check", text: "Fills ages by title", column: "age", issue_id: "i1", gate: "commit", detail: "committed · step 2" },
    ];
    const out = collapse(entries);
    expect(out.map((e) => e.icon)).toEqual(["check", "wait"]);
    expect(out[0]).toMatchObject({ text: "263 missing values", outcome: "Fills ages by title" });
  });

  it("starts cleaning and can remember the choice", async () => {
    const calls = mockApi({
      "POST /api/v1/datasets/ds_1/clean": { id: "job_1", kind: "clean", status: "queued" },
      "PUT /api/v1/me/settings": ME.settings,
      "GET /api/v1/jobs": [],
      "GET /api/v1/datasets/ds_1": DS,
    });
    renderAt(<OfferActions dataset={DS} />);
    fireEvent.click(screen.getByLabelText("Remember my choice"));
    fireEvent.click(screen.getByRole("button", { name: "Clean it for me" }));
    await waitFor(() => expect(calls.mock.calls.some(([u, i]) => String((u as Request).url ?? u).includes("/clean") && ((u as Request).method ?? i?.method) === "POST")).toBe(true));
    const put = calls.mock.calls.find(([u]) => String((u as Request).url ?? u).includes("/me/settings"));
    expect(put).toBeTruthy();
    expect(screen.getByRole("button", { name: "Go step by step" })).toBeDisabled();
  });

  it("offers retry choices after a failed run", () => {
    mockApi({});
    renderAt(<OfferActions dataset={{ ...DS, error: "Cleaning stopped: model unavailable" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Cleaning stopped: model unavailable");
    expect(screen.getByRole("button", { name: "Try cleaning again" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build dashboard without cleaning" })).toBeInTheDocument();
  });

  it("summarizes the report", async () => {
    mockApi({
      "GET /api/v1/datasets/ds_1/report": {
        job_id: "job_1", status: "done", from_version: 2, to_version: 4, ended_by: "done", waited_for_model_s: 0,
        attempted: 4, budget: { max_steps: 20, max_seconds: 300 }, started_at: null, finished_at: null, error: null,
        counts: { found: 5, fixed: 1, flagged: 1, skipped: 3, rows_deleted: 0 },
        steps: [{ step_id: "s2", no: 2, summary: "Parse money as numbers (amount)", gate: "flag", confidence: 0.9,
                  flag_reason: "changes more than a fifth of the data",
                  impact: { cells_changed: 120, quarantined: 1, rows_added: 0, rows_deleted: 0 } }],
        skipped: [{ issue_id: "i", column: "customer_id", detector: "id_candidates", reason: "Looks like an ID column" }],
        hand_edited_skipped: [], decisions: [],
      },
    });
    renderAt(<ReportSummary datasetId="ds_1" />);
    expect(await screen.findByText("Every issue was looked at. v2 → v4")).toBeInTheDocument();
    expect(screen.getByText("Parse money as numbers (amount)")).toBeInTheDocument();
    expect(screen.getByText("changes more than a fifth of the data")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View full report" }));
    expect(await screen.findByText(/Looks like an ID column/)).toBeInTheDocument();
  });

  it("names the configured issue budget when the run hit it", async () => {
    mockApi({
      "GET /api/v1/datasets/ds_1/report": {
        job_id: "job_1", status: "done", from_version: 2, to_version: 9, ended_by: "steps", waited_for_model_s: 0,
        attempted: 12, budget: { max_steps: 12, max_seconds: 300 }, started_at: null, finished_at: null, error: null,
        counts: { found: 30, fixed: 7, flagged: 0, skipped: 5, rows_deleted: 0 },
        steps: [], skipped: [], hand_edited_skipped: [], decisions: [],
      },
    });
    renderAt(<ReportSummary datasetId="ds_1" />);
    expect(await screen.findByText("Stopped at the 12-issue budget. v2 → v9")).toBeInTheDocument();
  });
});
