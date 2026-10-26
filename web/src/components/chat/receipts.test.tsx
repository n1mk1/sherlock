import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CleaningReport } from "@/api/types";
import { FullReport } from "@/components/dataset/CleaningReport";
import { Sources } from "@/components/shell/ChatBar";
import { mockApi, renderAt } from "@/test/render";
import { type ModelCall, type Receipt, seconds, totalLine } from "./Receipts";

afterEach(() => vi.unstubAllGlobals());

const call = (over: Partial<ModelCall>): ModelCall => ({
  id: 1, role: "medium", model: "nvidia/nemotron-test-super", purpose: "sql", prompt_tokens: 900, completion_tokens: 100,
  tokens: 1000, latency_ms: 1200, ok: true, error: null, repaired: false, cached: false, created_at: "", ...over,
});

const ANSWER: Receipt = {
  calls: [
    call({ id: 1, role: "small", model: "nvidia/nemotron-test-nano", purpose: "route", tokens: 400, latency_ms: 800 }),
    call({ id: 2, purpose: "sql", tokens: 0, prompt_tokens: null, completion_tokens: null, latency_ms: 30000, ok: false,
           error: "APITimeoutError: Request timed out." }),
    call({ id: 3, purpose: "sql", repaired: true, tokens: 1200 }),
    call({ id: 4, purpose: "compose", tokens: 900, latency_ms: 2500 }),
    call({ id: 5, role: "web", model: "tavily-search", purpose: "web_search", tokens: 0, latency_ms: 0, cached: true }),
  ],
  total: { calls: 5, failed: 1, repaired: 1, cached: 1, prompt_tokens: 2000, completion_tokens: 500, tokens: 2500, latency_ms: 34500 },
};

describe("How I worked it out", () => {
  it("lists an answer's calls in order with a total, inside How do you know?", async () => {
    const fetchMock = mockApi({ "GET /api/v1/chat/messages/msg_1/calls": ANSWER });
    renderAt(<Sources sources={[{ kind: "sql", sql: "SELECT 1", label: "Query (r1)" }]} messageId="msg_1" />);
    expect(screen.getByText("How do you know?")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled(); // collapsed: nothing is read until it opens
    fireEvent.click(screen.getByText("How I worked it out"));
    const rows = (await screen.findAllByRole("row")).slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell")[0].textContent)).toEqual([
      "1. Read the question", "2. Wrote the query(failed)", "3. Wrote the query(repair)", "4. Wrote the answer", "5. Searched the web",
    ]);
    expect(within(rows[0]).getByText("nvidia/nemotron-test-nano")).toBeInTheDocument();
    expect(within(rows[0]).getByText("0.8 s")).toBeInTheDocument();
    expect(within(rows[2]).getByText("1,200")).toBeInTheDocument();
    expect(within(rows[4]).getByText("cached")).toBeInTheDocument();
    expect(screen.getByText(
      "Total: 5 calls · 34.5 s waiting on them · 2,500 tokens · 1 repair · 1 failed attempt · 1 from the cache",
    )).toBeInTheDocument();
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/v1/chat/messages/msg_1/calls");
  });

  it("says so when no model was called", async () => {
    mockApi({ "GET /api/v1/chat/messages/msg_2/calls": { calls: [], total: { ...ANSWER.total, calls: 0 } } });
    renderAt(<Sources sources={[]} messageId="msg_2" />);
    fireEvent.click(screen.getByText("How I worked it out"));
    expect(await screen.findByText("No model was called for this.")).toBeInTheDocument();
  });

  it("shows a clean's calls in the full cleaning report", async () => {
    mockApi({
      "GET /api/v1/jobs/job_1/calls": {
        calls: [call({ id: 7, role: "large", model: "nvidia/nemotron-test-ultra", purpose: "diagnose", tokens: 3000 }),
                call({ id: 8, purpose: "critic", tokens: 800 })],
        total: { calls: 9, failed: 0, repaired: 0, cached: 0, prompt_tokens: 9000, completion_tokens: 900, tokens: 9900, latency_ms: 9000 },
      },
    });
    const report = {
      job_id: "job_1", steps: [], skipped: [], hand_edited_skipped: [], decisions: [],
    } as unknown as CleaningReport;
    renderAt(<FullReport report={report} />);
    fireEvent.click(screen.getByText("How I worked it out"));
    expect(await screen.findByText("1. Diagnosed an issue")).toBeInTheDocument();
    expect(screen.getByText("2. Reviewed a fix")).toBeInTheDocument();
    expect(screen.getByText("and 7 more calls")).toBeInTheDocument(); // the API lists the first 500
    expect(screen.getByText(/^Total: 9 calls · 9\.0 s waiting on them · 9,900 tokens$/)).toBeInTheDocument();
  });

  it("formats times", () => {
    expect(seconds(40)).toBe("under 0.1 s");
    expect(seconds(1234)).toBe("1.2 s");
    expect(totalLine({ calls: 1, failed: 0, repaired: 0, cached: 0, prompt_tokens: 1, completion_tokens: 0, tokens: 1, latency_ms: 500 }))
      .toBe("1 call · 0.5 s waiting on them · 1 token");
  });
});
