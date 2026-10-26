import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Dataset } from "@/api/types";
import { mockApi, renderAt } from "@/test/render";
import { FailedScreen } from "./StatusScreens";

afterEach(() => vi.unstubAllGlobals());

const RAW = 'IO Error: Failed to create directory ".tmp": Permission denied';
const DS = {
  id: "ds_1", name: "wide.csv", status: "failed", current_version: 1, row_count: 100, column_count: 300,
  created_at: "", last_opened_at: null, last_tab: null, error: RAW,
} as Dataset;
const JOB = { id: "job_1", dataset_id: "ds_1", kind: "profile", status: "failed", created_at: "", started_at: null,
              finished_at: null, error: RAW, result: null, progress: {} };

describe("failed profile screen", () => {
  it("says what happened in plain words and keeps the raw error behind a toggle", async () => {
    const calls = mockApi({ "GET /api/v1/jobs": [JOB], "POST /api/v1/jobs/job_1/retry": { ...JOB, status: "queued" } });
    renderAt(<FailedScreen dataset={DS} />);
    expect(screen.getByText(/ran into a problem of its own/)).toBeInTheDocument();
    expect(screen.queryByText(/delete this CSV/)).not.toBeInTheDocument();
    const details = screen.getByText("Technical details").closest("details")!;
    expect(details.open).toBe(false);
    expect(details).toHaveTextContent(RAW);

    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(calls.mock.calls.some(([u, i]) => String(u).endsWith("/jobs/job_1/retry") && i?.method === "POST")).toBe(true));
  });

  it("says a cancelled profile was stopped, with no technical details", () => {
    mockApi({ "GET /api/v1/jobs": [{ ...JOB, status: "cancelled", error: "Cancelled." }] });
    renderAt(<FailedScreen dataset={{ ...DS, error: "Cancelled." }} />);
    expect(screen.getByText(/was stopped before it finished/)).toBeInTheDocument();
    expect(screen.queryByText("Technical details")).not.toBeInTheDocument();
  });
});
