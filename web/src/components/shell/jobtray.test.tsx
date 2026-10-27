import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Job } from "@/api/types";
import { initials } from "@/components/library/LibraryPanel";
import { mockApi, renderAt } from "@/test/render";
import { JobTray, visibleJobs } from "./JobTray";

afterEach(() => vi.unstubAllGlobals());

describe("job tray", () => {
  it("keeps running, recent and failed jobs in the tray", () => {
    const now = Date.parse("2026-10-25T00:10:00Z");
    const job = (id: string, status: Job["status"], finished: string | null) =>
      ({ id, status, finished_at: finished, kind: "clean", progress: { step: 0, of: 0, label: "", pct: 0 } }) as Job;
    const jobs = [job("a", "running", null), job("b", "done", "2026-10-25T00:09:30Z"), job("c", "done", "2026-10-25T00:01:00Z"),
      job("d", "failed", "2026-10-25T00:00:00Z"), job("e", "failed", "2026-10-25T00:00:00Z")];
    expect(visibleJobs(jobs, new Set(["e"]), now).map((j) => j.id)).toEqual(["a", "b", "d"]);
  });

  it("is a popover whose Retry and Dismiss are reached with Tab", async () => {
    mockApi({
      "GET /api/v1/jobs": [{ id: "job_1", dataset_id: "ds_1", kind: "clean", status: "failed", error: "Model unavailable",
        progress: { step: 0, of: 0, label: "", pct: 0 }, created_at: "", started_at: null, finished_at: null, result: null }],
      "GET /api/v1/datasets": [],
    });
    renderAt(<JobTray />);
    fireEvent.click(await screen.findByRole("button", { name: /Background jobs/ }));
    const retry = await screen.findByRole("button", { name: "Retry" });
    expect(screen.getByRole("dialog")).toContainElement(retry);
    // A dropdown menu cancels Tab inside it (UI/UX brief §8: every control is reachable by keyboard).
    expect(fireEvent.keyDown(retry, { key: "Tab" })).toBe(true);
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });
});

describe("the library rail", () => {
  it("names each dataset by its initials", () => {
    expect(initials("titanic3.csv (sample)")).toBe("TI");
    expect(initials("sales_semicolon.csv")).toBe("SS");
  });
});
