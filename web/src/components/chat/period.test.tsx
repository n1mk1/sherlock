// "What happened around <period>?" (docs/plans/tavily.md §3.6): the button on a dated answer, and what a press sends.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { periodActions } from "@/api/period";
import type { Dataset, Message } from "@/api/types";
import { ChatBar } from "@/components/shell/ChatBar";
import { ME, mockApi, renderAt } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());
beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn(); // jsdom has no layout; the thread scrolls to its end
});

const DS = {
  id: "ds_1", name: "orders.csv", status: "ready", current_version: 3, row_count: 120, column_count: 4,
  created_at: "", last_opened_at: null, last_tab: null, error: null, clean_plan_id: null,
} as Dataset;

const LABEL = "What happened around May 2024?";
const ACTION = { kind: "ask_period", label: LABEL, period: "May 2024", start_date: "2024-04-17", end_date: "2024-06-14",
                 measure: "total", result: "r1" };
const text = (t: string) => [{ type: "paragraph", runs: [{ type: "text", text: t }] }];
const ANSWER = {
  id: "msg_2", role: "assistant", text: "The monthly total fell.", created_at: "2026-10-26T00:00:00Z", clarification_of: null,
  blocks: [{ type: "text", body: { blocks: text("The monthly total fell.") } }], sources: [], actions: [ACTION],
} as unknown as Message;

describe("outside context next to a dated answer", () => {
  it("reads the period button from the message's actions", () => {
    expect(periodActions(ANSWER)).toEqual([ACTION]);
    expect(periodActions({ ...ANSWER, actions: [{ kind: "open_rows", selection_id: "sel_1" }] })).toEqual([]);
    expect(periodActions({ ...ANSWER, actions: undefined })).toEqual([]);
  });

  it("shows the button, and a press sends the button's text as a choice on that message", async () => {
    const reply = { ...ANSWER, id: "msg_3", text: "From the web.", actions: undefined, clarification_of: "msg_2",
                    blocks: [{ type: "text", body: { blocks: text("From the web (not from your data): Shops paused orders.") } }] };
    let asked = false; // the thread the server keeps: the saved reply joins it once the press is answered
    const fetchMock = mockApi({
      "GET /api/v1/me": ME,
      "GET /api/v1/datasets/ds_1/chat": () => (asked ? [ANSWER, reply] : [ANSWER]),
      "POST /api/v1/datasets/ds_1/chat": () => (asked = true) && new Response(`event: message\ndata: ${JSON.stringify(reply)}\n\n`, {
        status: 200, headers: { "Content-Type": "text/event-stream" },
      }),
    });
    renderAt(<ChatBar dataset={DS} placeholder="Ask" />);
    fireEvent.focus(await screen.findByLabelText("Ask Sherlock")); // opens the thread
    const button = await screen.findByRole("button", { name: LABEL });
    expect(button).toBeEnabled();
    fireEvent.click(button);

    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([, i]) => i?.method === "POST")!;
    // The period itself stays on the saved message: the request names the message and the button.
    expect(JSON.parse(String(init!.body))).toEqual({
      text: LABEL, context: { tab: "csv" }, clarification_of: "msg_2", choice: LABEL,
    });
    expect(await screen.findByText(/Shops paused orders/)).toBeInTheDocument();
  });
});
