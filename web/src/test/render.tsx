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
    story_updates: "auto", spotlight: "subtle", reduce_motion: "system", default_tab: "dashboard",
  },
};

/** Stubs fetch with a route table: "GET /api/v1/datasets" → body (or a function of the request). */
export function mockApi(routes: Record<string, unknown>) {
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
