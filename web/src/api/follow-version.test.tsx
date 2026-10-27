// Web state follows the version: what the page shows is re-checked when the data moves on,
// and a change made in another tab reaches this one.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useRun } from "@/api/ml";
import { applyStatus, keys, useCleanPlan, useDatasetEvents, useThread } from "@/api/queries";
import type { CleanPlan, Dataset } from "@/api/types";
import { CleanPlanPanel } from "@/components/dataset/CleanPlanPanel";
import { stubEventSource } from "@/test/eventsource";
import { mockApi, renderAt } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());

const DS = {
  id: "ds_1", name: "messy.csv", status: "ready", current_version: 3, row_count: 120, column_count: 4,
  created_at: "", last_opened_at: null, last_tab: null, error: null, clean_plan_id: "pln_1",
} as Dataset;

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { qc, wrapper: ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client: qc }, children) };
}

describe("the dataset stream", () => {
  it("reads an open cleaning plan again on version.created, and the thread on chat.updated", async () => {
    const ES = stubEventSource();
    const reads = { plan: 0, chat: 0 };
    mockApi({
      "GET /api/v1/clean-plans/pln_1": () => ({ id: "pln_1", version: 2 + reads.plan++ }),
      "GET /api/v1/datasets/ds_1/chat": () => (reads.chat++ ? [{ id: "msg_2" }] : []),
    });
    const { wrapper: w } = wrapper();
    const { result } = renderHook(() => {
      useDatasetEvents("ds_1");
      return { plan: useCleanPlan("pln_1"), thread: useThread("ds_1") };
    }, { wrapper: w });
    await waitFor(() => expect(result.current.plan.data?.version).toBe(2));
    const stream = ES.last();
    act(() => stream.emit("version.created", { version: 3 }, 11));
    await waitFor(() => expect(result.current.plan.data?.version).toBe(3)); // the server merged it on read
    act(() => stream.emit("chat.updated", {}, 12)); // another tab's question was answered
    await waitFor(() => expect(result.current.thread.data).toHaveLength(1));
  });

  it("reads the steps and report again when the library stream says the status changed", () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    applyStatus(qc, { dataset_id: "ds_1", status: "ready", current_version: 3 } as Parameters<typeof applyStatus>[1]);
    const invalidated = spy.mock.calls.map(([f]) => JSON.stringify(f?.queryKey));
    for (const key of [keys.steps("ds_1"), ["report", "ds_1"]]) expect(invalidated).toContain(JSON.stringify(key));
  });

  it("reads an open model card again on version.created, since the new version can outdate its run", async () => {
    const ES = stubEventSource();
    let status = "done";
    mockApi({ "GET /api/v1/runs/run_1": () => ({ id: "run_1", status }) });
    const { wrapper: w } = wrapper();
    const { result } = renderHook(() => {
      useDatasetEvents("ds_1");
      return useRun("run_1");
    }, { wrapper: w });
    await waitFor(() => expect(result.current.data?.status).toBe("done"));
    status = "outdated";
    act(() => ES.last().emit("version.created", { version: 4 }, 3));
    await waitFor(() => expect(result.current.data?.status).toBe("outdated"));
  });
});

describe("the cleaning plan on a new version", () => {
  it("says which version Sherlock checked while the data is newer", async () => {
    const plan: CleanPlan = {
      id: "pln_1", dataset_id: "ds_1", version: 2, status: "draft", source: "user", job_id: null, scope: null, depth: 5,
      created_at: "", updated_at: "", items: [],
    };
    mockApi({ "GET /api/v1/clean-plans/pln_1": plan });
    renderAt(<CleanPlanPanel dataset={DS} layout="centre" />);
    expect(await screen.findByText("Sherlock checked v2; the data is v3. Checking the plan again…")).toBeInTheDocument();
  });
});
