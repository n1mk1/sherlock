// The chat stream's hand-over: the server sends the saved answer, then keeps the stream open while it
// writes the thread summary (TRD §8.1 step 1). The answer must show once in that time, not as the
// streamed copy and the saved one together (the e2e flow saw both under load).
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Dataset, Message } from "@/api/types";
import { ChatBar, withAnswer } from "@/components/shell/ChatBar";
import { ME, mockApi, renderAt } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());
beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn(); // jsdom has no layout; the thread scrolls to its end
});

const DS = {
  id: "ds_1", name: "orders.csv", status: "ready", current_version: 3, row_count: 120, column_count: 4,
  created_at: "", last_opened_at: null, last_tab: null, error: null, clean_plan_id: null,
} as Dataset;

const SAID = "The top group has the highest average.";
const ANSWER: Message = {
  id: "msg_2", role: "assistant", text: SAID, created_at: "2026-10-26T00:00:00Z", clarification_of: null,
  blocks: [{ type: "text", body: { blocks: [{ type: "paragraph", runs: [{ type: "text", text: SAID }] }] } }] as Message["blocks"],
  sources: [{ kind: "sql", sql: "SELECT 1", label: "Query (r1)" }] as Message["sources"],
};

describe("the chat stream's hand-over", () => {
  it("shows a saved answer once while the stream stays open for the summary", async () => {
    let close = () => {};
    const enc = new TextEncoder();
    const fetchMock = mockApi({
      "GET /api/v1/me": ME,
      "GET /api/v1/datasets/ds_1/chat": [],
      "GET /api/v1/datasets/ds_1/widgets": { widgets: [], layout: {} },
      "POST /api/v1/datasets/ds_1/chat": () => new Response(new ReadableStream({
        start(c) {
          c.enqueue(enc.encode(`event: block\ndata: ${JSON.stringify(ANSWER.blocks[0])}\n\n`));
          c.enqueue(enc.encode(`event: message\ndata: ${JSON.stringify(ANSWER)}\n\n`));
          close = () => c.close(); // the summary call is still running
        },
      }), { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    });
    renderAt(<ChatBar dataset={DS} tab="dashboard" placeholder="Ask" />);
    const input = await screen.findByLabelText("Ask Sherlock");
    fireEvent.change(input, { target: { value: "which group is highest?" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await screen.findByText("How do you know?"); // the saved message is on screen
    expect(screen.getAllByText(SAID)).toHaveLength(1);
    expect(screen.getAllByText("which group is highest?")).toHaveLength(1);
    // The next question waits for the stream to end, so two answers never run at once: Enter queues it,
    // and the thread says so (finding 21 of the live test: Enter used to do nothing).
    const posts = () => fetchMock.mock.calls.filter(([, init]) => init?.method === "POST").length;
    fireEvent.change(input, { target: { value: "and the lowest?" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText("and the lowest?")).toBeInTheDocument();
    expect(screen.getByText(/Queued: sends when this answer finishes/)).toBeInTheDocument();
    expect(input).toHaveValue("");
    expect(posts()).toBe(1);

    await act(async () => close());
    await waitFor(() => expect(posts()).toBe(2)); // sent once the first stream ended
    expect(screen.queryByText(/Queued:/)).not.toBeInTheDocument();
  });

  it("gives a cancelled queued question back to the bar", async () => {
    mockApi({
      "GET /api/v1/me": ME,
      "GET /api/v1/datasets/ds_1/chat": [],
      "GET /api/v1/datasets/ds_1/widgets": { widgets: [], layout: {} },
      "POST /api/v1/datasets/ds_1/chat": () => new Response(new ReadableStream({ start() {} }), {
        status: 200, headers: { "Content-Type": "text/event-stream" },
      }), // never ends
    });
    renderAt(<ChatBar dataset={DS} tab="dashboard" placeholder="Ask" />);
    const input = await screen.findByLabelText("Ask Sherlock");
    fireEvent.change(input, { target: { value: "first" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.change(input, { target: { value: "second" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(input).toHaveValue("second");
    expect(screen.queryByText(/Queued:/)).not.toBeInTheDocument();
  });

  it("puts the question before its answer until the refetch brings the saved one", () => {
    const earlier = { ...ANSWER, id: "msg_0" };
    const list = withAnswer([earlier], "which group is highest?", ANSWER);
    expect(list.map((m) => [m.role, m.id])).toEqual([["assistant", "msg_0"], ["user", "local-msg_2"], ["assistant", "msg_2"]]);
    expect(list[1].text).toBe("which group is highest?");
  });
});
