import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

export const ME = {
  user_id: "usr_1",
  created_at: "2026-10-24T00:00:00Z",
  settings: {
    theme: "light", accent: "verdigris", chatbar: "pinned", after_upload: "ask", cleaning_mode: "auto",
    reduce_motion: "system",
  },
};

// The detector catalog as `GET /detectors` serves it (`cleaning/registry.py`), for the labels.
const CATALOG: [string, string, string, string | null][] = [
  ["leakage", "records the outcome", "other", null], ["mixed_types", "values of another type", "types", "skews"],
  ["duplicates", "duplicate rows", "records", "skews"], ["sentinels", "placeholder values", "missing", "skews"],
  ["impossible_values", "impossible values", "records", "skews"], ["numbers_as_text", "numbers stored as text", "types", "skews"],
  ["ambiguous_dates", "ambiguous dates", "types", "skews"], ["mojibake", "garbled characters", "text", "splits"],
  ["cross_column", "values out of order", "records", "skews"], ["missing", "missing values", "missing", "check"],
  ["near_duplicate_categories", "near-duplicate categories", "text", "splits"], ["unit_mixes", "mixed units", "types", "skews"],
  ["functional_dependency", "rows breaking a dependency", "records", "check"],
  ["whitespace_case", "spacing or case variants", "text", "splits"], ["outliers", "outliers", "outliers", "check"],
  ["id_candidates", "looks like an ID", "other", null], ["rule", "your check", "other", "skews"],
];
export const DETECTORS = {
  detectors: CATALOG.map(([id, label, group, default_level]) => ({ id, label, description: "", group, default_level, source: "builtin" })),
};

/** Stubs fetch with a route table: "GET /api/v1/datasets" → body (or a function of the request). The
 * detector catalog answers unless the table has its own. */
export function mockApi(routes: Record<string, unknown>) {
  routes = { "GET /api/v1/detectors": DETECTORS, ...routes };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = typeof input === "object" && "url" in input ? (input as Request) : null;
    const url = new URL(req ? req.url : String(input), "http://localhost");
    const method = (req?.method ?? init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url.pathname}`
    if (!(key in routes)) {
      return new Response(JSON.stringify({ error: { code: "not_found", message: `no mock for ${key}` } }), { status: 404 });
    }
    const value = routes[key];
    const body = typeof value === "function" ? await (value as (u: URL, i?: RequestInit) => unknown)(url, init) : value;
    if (body instanceof Response) return body; // a route can answer with an error status
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export function renderAt(ui: ReactElement, path = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}
