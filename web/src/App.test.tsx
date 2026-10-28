import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { forwardRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { ME, mockApi, renderAt } from "./test/render";

// The real grid draws on a canvas, which jsdom lacks.
vi.mock("@/components/csv/Grid", () => ({
  Grid: forwardRef<unknown, { readOnly?: boolean }>(function Grid({ readOnly }, _ref) {
    return <div data-testid="grid" data-readonly={String(!!readOnly)} />;
  }),
}));

afterEach(() => vi.unstubAllGlobals());

const DS = {
  id: "ds_1", name: "titanic3.csv (sample)", status: "offer", current_version: 2, row_count: 1309, column_count: 14,
  created_at: "2026-10-24T00:00:00Z", last_opened_at: null, last_tab: null, error: null,
};

describe("App shell", () => {
  it("asks /me first, so a first visit's requests share one new user", async () => {
    let answer: (v: unknown) => void = () => {};
    const me = new Promise((r) => { answer = r; });
    const fetchMock = mockApi({ "GET /api/v1/me": () => me, "GET /api/v1/datasets": [] });
    renderAt(<App />);
    await new Promise((r) => setTimeout(r, 50));
    const paths = () => fetchMock.mock.calls.map(([input]) => new URL(typeof input === "object" && "url" in input ? (input as Request).url : String(input), "http://localhost").pathname);
    expect(paths()).toEqual(["/api/v1/me"]);
    answer(ME);
    expect(await screen.findByRole("heading", { name: "Drop a CSV anywhere" })).toBeInTheDocument();
    expect(paths()).toContain("/api/v1/datasets");
  });

  it("shows the new-visitor cap as its own screen, and Try again opens the app once it lifts", async () => {
    let calls = 0;
    const limited = () => new Response(JSON.stringify({ error: {
      code: "rate_limited", message: "Too many new visitors from your network. Try again in 2 minutes." } }), { status: 429 });
    mockApi({ "GET /api/v1/me": () => (++calls === 1 ? limited() : ME), "GET /api/v1/datasets": [] });
    renderAt(<App />);
    expect(await screen.findByRole("heading", { name: "Sherlock can't open a new workspace yet" })).toBeInTheDocument();
    expect(screen.getByText("Too many new visitors from your network. Try again in 2 minutes.")).toBeInTheDocument();
    expect(calls).toBe(1); // a 429 isn't retried behind the user's back
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Drop a CSV anywhere" })).toBeInTheDocument();
  });

  it("shows the empty library with Upload and Try with sample", async () => {
    mockApi({ "GET /api/v1/me": ME, "GET /api/v1/datasets": [] });
    renderAt(<App />);
    expect(await screen.findByRole("heading", { name: "Drop a CSV anywhere" })).toBeInTheDocument();
    expect(screen.getByText("No CSVs yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try the Titanic sample" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Load a CSV to start asking")).toBeDisabled();
    expect(screen.getByRole("heading", { name: "How it works" })).toBeInTheDocument(); // the right panel on `/`
  });

  it("lists datasets with their status, and an old tab link opens the dataset's one view", async () => {
    mockApi({
      "GET /api/v1/me": ME,
      "GET /api/v1/datasets": [DS, { ...DS, id: "ds_2", name: "sales.csv", status: "ready", current_version: 5 }],
      "GET /api/v1/datasets/ds_1": DS,
      "GET /api/v1/datasets/ds_1/datacard": {
        version: 2, row_count: 1309, column_count: 14, quarantined: 0, columns: [],
        issues: [
          { id: "i1", detector: "missing", column: "cabin", count: 1014, severity: 0.39, proposal: "", examples: [], details: {} },
          { id: "i2", detector: "missing", column: "age", count: 263, severity: 0.1, proposal: "", examples: [], details: {} },
          { id: "i3", detector: "leakage", column: "boat", count: 486, severity: 0.37, proposal: "", examples: [], details: {} },
        ],
        target_candidates: [], leakage_candidates: [],
      },
    });
    renderAt(<App />, "/d/ds_1/dashboard");
    const nav = await screen.findByRole("navigation", { name: "Your CSVs" });
    expect(await within(nav).findByText("sales")).toBeInTheDocument();
    expect(within(nav).getAllByText("Ready").length).toBeGreaterThan(0);
    expect(await screen.findByRole("heading", { name: "3 issues to look at" })).toBeInTheDocument();
    expect(await screen.findByText("1,014 missing values in cabin")).toBeInTheDocument();
    expect(screen.getByText("boat records the outcome")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).toBeNull(); // no tab switcher: one view per dataset
  });

  it("opens a ready dataset on its grid, with Changes in the right panel", async () => {
    const ready = { ...DS, status: "ready", current_version: 3, step_count: 2, clean_plan_id: null };
    mockApi({
      "GET /api/v1/me": ME,
      "GET /api/v1/datasets": [ready],
      "GET /api/v1/datasets/ds_1": ready,
      "GET /api/v1/datasets/ds_1/steps": [],
      "GET /api/v1/datasets/ds_1/chat": [],
      "GET /api/v1/jobs": [],
    });
    renderAt(<App />, "/d/ds_1");
    expect(await screen.findByTestId("grid")).toHaveAttribute("data-readonly", "false");
    expect(screen.getByRole("toolbar", { name: "CSV tools" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Changes" })).toBeInTheDocument();
    expect(screen.getByText("2 changes")).toBeInTheDocument();
    expect(screen.getByLabelText("Ask Sherlock")).toBeEnabled();
  });
});

describe("header details", () => {
  it("shows issue counts, the steps pill, and settings behind the gear", async () => {
    const calls = mockApi({
      "GET /api/v1/me": ME,
      "PUT /api/v1/me/settings": { ...ME.settings, theme: "dark" },
      "GET /api/v1/datasets": [{ ...DS, issue_count: 4, step_count: 1 }],
      "GET /api/v1/datasets/ds_1": { ...DS, issue_count: 4, step_count: 1 },
      "GET /api/v1/datasets/ds_1/datacard": { version: 2, row_count: 1, column_count: 1, quarantined: 0, columns: [], issues: [], target_candidates: [], leakage_candidates: [] },
    });
    renderAt(<App />, "/d/ds_1");
    const nav = await screen.findByRole("navigation", { name: "Your CSVs" });
    expect(await within(nav).findByText("4 issues")).toBeInTheDocument();
    expect(screen.getAllByText("4 issues")).toHaveLength(2); // the library row and the header's pill
    fireEvent.click(within(nav).getByRole("button", { name: "Settings" }));
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("radio", { name: "Dark" }));
    await waitFor(() => expect(calls.mock.calls.some(([u]) => String((u as Request).url ?? u).includes("/me/settings"))).toBe(true));
    expect(screen.getByRole("radio", { name: /Brass/ })).toBeInTheDocument();
  });
});
