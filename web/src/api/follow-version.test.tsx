// Web state follows the version (plan 2b.5): what a tab shows is re-checked when the data moves on,
// and a change made in another tab reaches this one.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { applyStatus, keys, useCleanPlan, useDatasetEvents, useThread } from "@/api/queries";
import type { CleanPlan, DataCard, Dataset } from "@/api/types";
import { useFilterCheck } from "@/components/dashboard/Dashboard";
import { CleanPlanPanel } from "@/components/dataset/CleanPlanPanel";
import { filterGone, useFilters } from "@/state/filters";
import { stubEventSource } from "@/test/eventsource";
import { mockApi, renderAt } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());

const DS = {
  id: "ds_1", name: "messy.csv", status: "ready", current_version: 3, row_count: 120, column_count: 4,
  created_at: "", last_opened_at: null, last_tab: null, error: null, clean_plan_id: "pln_1",
} as Dataset;

const card = (version: number, values: string[]): DataCard => ({
  version, row_count: 120, column_count: 2, quarantined: 0, issues: [], target_candidates: [], leakage_candidates: [],
  columns: [
    { name: "region", type: "category", role: "dimension", missing: 0, missing_pct: 0, distinct: values.length,
      top_values: values.map((value) => ({ value, count: 10 })) },
    { name: "units", type: "integer", role: "measure", missing: 0, missing_pct: 0, distinct: 40, top_values: null },
  ],
});

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
      useDatasetEvents("ds_1", () => {});
      return { plan: useCleanPlan("pln_1"), thread: useThread("ds_1") };
    }, { wrapper: w });
    await waitFor(() => expect(result.current.plan.data?.version).toBe(2));
    const stream = ES.last();
    act(() => stream.emit("version.created", { version: 3 }, 11));
    await waitFor(() => expect(result.current.plan.data?.version).toBe(3)); // the server merged it on read
    act(() => stream.emit("chat.updated", {}, 12)); // another tab's question was answered
    await waitFor(() => expect(result.current.thread.data).toHaveLength(1));
  });

  it("reads the cards, steps and report again when the library stream says the status changed", () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    applyStatus(qc, { dataset_id: "ds_1", status: "ready", current_version: 3 } as Parameters<typeof applyStatus>[1]);
    const invalidated = spy.mock.calls.map(([f]) => JSON.stringify(f?.queryKey));
    for (const key of [["cards", "ds_1"], keys.steps("ds_1"), ["report", "ds_1"]]) expect(invalidated).toContain(JSON.stringify(key));
  });
});

describe("the dashboard filter on a new version", () => {
  it("is gone when its column or its value is", () => {
    const clause = { col: "region", op: "eq", value: "North" } as const;
    expect(filterGone(clause, card(3, ["North", "South"]))).toBeNull();
    expect(filterGone(clause, card(3, ["South"]))).toBe("no row of v3 has region = North");
    expect(filterGone({ ...clause, col: "area" }, card(3, ["North"]))).toBe("v3 has no column area");
    // A value typed by the click (1, true) matches the card's text ("1", "True").
    expect(filterGone({ ...clause, value: 1 }, card(3, ["1", "2"]))).toBeNull();
    expect(filterGone({ ...clause, value: true }, card(3, ["True", "False"]))).toBeNull();
    // A card that doesn't list every value can't say a value is gone.
    expect(filterGone(clause, { ...card(3, ["South"]), columns: [{ ...card(3, ["South"]).columns[0], distinct: 30 }] })).toBeNull();
  });

  it("is cleared when the new version's data card no longer has its value", () => {
    useFilters.getState().toggle("ds_1", { col: "region", op: "eq", value: "North" });
    const { rerender } = renderHook(({ ds, dc }: { ds: Dataset; dc: DataCard }) => useFilterCheck(ds, dc), {
      initialProps: { ds: { ...DS, current_version: 2 }, dc: card(2, ["North", "South"]) },
    });
    expect(useFilters.getState().byDataset.ds_1).not.toBeNull();
    rerender({ ds: { ...DS, current_version: 3 }, dc: card(2, ["North", "South"]) }); // the card of v3 isn't in yet
    expect(useFilters.getState().byDataset.ds_1).not.toBeNull();
    rerender({ ds: { ...DS, current_version: 3 }, dc: card(3, ["South"]) });
    expect(useFilters.getState().byDataset.ds_1).toBeNull();
  });
});

describe("the cleaning plan on a new version", () => {
  it("says which version Sherlock checked while the data is newer", async () => {
    const plan: CleanPlan = {
      id: "pln_1", dataset_id: "ds_1", version: 2, status: "draft", source: "user", job_id: null, scope: null,
      created_at: "", updated_at: "", items: [],
    };
    mockApi({ "GET /api/v1/clean-plans/pln_1": plan });
    renderAt(<CleanPlanPanel dataset={DS} layout="centre" />);
    expect(await screen.findByText("Sherlock checked v2; the data is v3. Checking the plan again…")).toBeInTheDocument();
  });
});
