import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { ME, mockApi, renderAt } from "./test/render";

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
    expect(screen.getByRole("button", { name: "Try with sample (Titanic)" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Load a CSV to start asking")).toBeDisabled();
    expect(screen.getByText("Stories appear once the dashboard is built.")).toBeInTheDocument();
  });

  it("lists datasets with their status and opens one on its tab", async () => {
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
    expect(await within(nav).findByText("sales.csv")).toBeInTheDocument();
    expect(within(nav).getByText(/ready · v5/)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /Here's what I found in titanic3.csv/ })).toBeInTheDocument();
    expect(await screen.findByText("1,014 missing values in cabin")).toBeInTheDocument();
    expect(screen.getByText("boat records the outcome")).toBeInTheDocument();
    // Dashboard and Flow wait for the dataset to be ready; CSV is open once it's typed.
    expect(screen.getByRole("tab", { name: "Flow" })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("tab", { name: "CSV" })).toHaveAttribute("href", "/d/ds_1/csv");
  });
});

describe("canvas details", () => {
  it("shows issue counts, the steps pill, and settings behind the gear", async () => {
    const calls = mockApi({
      "GET /api/v1/me": ME,
      "PUT /api/v1/me/settings": { ...ME.settings, theme: "dark" },
      "GET /api/v1/datasets": [{ ...DS, issue_count: 4, step_count: 1 }],
      "GET /api/v1/datasets/ds_1": { ...DS, issue_count: 4, step_count: 1 },
      "GET /api/v1/datasets/ds_1/datacard": { version: 2, row_count: 1, column_count: 1, quarantined: 0, columns: [], issues: [], target_candidates: [], leakage_candidates: [] },
    });
    renderAt(<App />, "/d/ds_1/dashboard");
    const nav = await screen.findByRole("navigation", { name: "Your CSVs" });
    expect(await within(nav).findByText("offer · 4 issues")).toBeInTheDocument();
    expect(await screen.findByText("v2 · 1 step")).toBeInTheDocument();
    fireEvent.click(within(nav).getByRole("button", { name: "Settings" }));
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("radio", { name: "Dark" }));
    await waitFor(() => expect(calls.mock.calls.some(([u]) => String((u as Request).url ?? u).includes("/me/settings"))).toBe(true));
    expect(screen.getByRole("radio", { name: /Brass/ })).toBeInTheDocument();
  });
});
