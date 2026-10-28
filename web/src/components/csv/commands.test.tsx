// Cleaning commands from chat and the toolbar's Undo and Redo (docs/plans/chat-commands.md): the card shows the
// code and its effect, OK runs it (then sends the rest of the message), and Undo/Redo move one state at a time.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { forwardRef } from "react";
import { Toaster } from "sonner";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Dataset, Proposal } from "@/api/types";
import { ProposalView } from "@/components/shell/ChatBar";
import { useEdits } from "@/state/edits";
import { mockApi, renderAt } from "@/test/render";
import { CsvTab } from "./CsvTab";

vi.mock("./Grid", () => ({
  Grid: forwardRef<unknown, object>(function Grid(_props, _ref) {
    return <div data-testid="grid" />;
  }),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  useEdits.setState({ buffers: {} });
});

const DS = {
  id: "ds_1", name: "messy.csv", status: "ready", current_version: 4, row_count: 120, column_count: 4,
  created_at: "", last_opened_at: null, last_tab: null, error: null, clean_plan_id: null,
} as Dataset;

const COMMAND: Proposal = {
  id: "prp_1", kind: "clean_step", base_version: 4, status: "pending", summary: "Change 12 cells in 12 rows: city",
  code: 'result = df.copy()\nresult["city"] = result["city"].str.title()', columns: ["city"], new_columns: [],
  impact: { cells_changed: 12, rows_affected: 12, quarantined: 0, columns_added: [] },
  before_after: [{ row_id: 3, column: "city", old: "new york", new: "New York" }],
  checks: ["no rows lost", "no new blanks"], warnings: [], then: "the number of rows by city?",
};

function posted(calls: ReturnType<typeof mockApi>) {
  return calls.mock.calls.map(([input, init]) => {
    const req = typeof input === "object" && "url" in input ? (input as Request) : null;
    return { path: new URL(req ? req.url : String(input), "http://localhost").pathname,
             method: (req?.method ?? (init as RequestInit | undefined)?.method ?? "GET").toUpperCase() };
  }).filter((c) => c.method === "POST");
}

describe("a cleaning command's card", () => {
  it("shows the code and the effect, and OK runs it, then sends the rest of the message", async () => {
    const calls = mockApi({ "POST /api/v1/proposals/prp_1/approve": { step: { id: "stp_5" }, version: 5 } });
    const onSend = vi.fn();
    renderAt(<><ProposalView proposal={COMMAND} dataset={DS} onSend={onSend} /><Toaster /></>);
    expect(screen.getByLabelText("The code that will run")).toHaveTextContent('result["city"].str.title()');
    expect(screen.getByText("new york")).toBeInTheDocument();
    expect(screen.getByText(/no rows lost/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    expect(await screen.findByText(/Done · saved as v5/)).toBeInTheDocument();
    expect(posted(calls).map((c) => c.path)).toContain("/api/v1/proposals/prp_1/approve");
    expect(onSend).toHaveBeenCalledWith("the number of rows by city?");
  });

  it("waits for unsaved grid edits before running", async () => {
    useEdits.setState({ buffers: { ds_1: { base: 4, edits: { "1:city": { row_id: 1, column: "city", value: "x", old: "y" } },
      newRows: [], deleted: [], restored: [] } } } as never);
    const calls = mockApi({});
    renderAt(<><ProposalView proposal={COMMAND} dataset={DS} /><Toaster /></>);
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    expect(await screen.findByText(/1 unsaved edit in the grid/)).toBeInTheDocument();
    expect(posted(calls)).toEqual([]);
  });

  it("says when it is queued behind a clean, and when it couldn't run", () => {
    mockApi({});
    renderAt(<ProposalView proposal={{ ...COMMAND, status: "queued" }} dataset={DS} />);
    expect(screen.getByText("Waiting for cleaning to finish")).toBeInTheDocument();
    renderAt(<ProposalView proposal={{ ...COMMAND, status: "failed", error: "the code failed: KeyError" }} dataset={DS} />);
    expect(screen.getByText("Couldn't run: the code failed: KeyError")).toBeInTheDocument();
  });
});

describe("Undo and Redo in the toolbar", () => {
  it("undo goes back one state, and Ctrl+Y redoes it", async () => {
    const calls = mockApi({
      "GET /api/v1/datasets/ds_1/history": { version: 4, undo: { step_id: "stp_4", no: 4, summary: "Change 12 cells in 12 rows: city" },
        redo: { step_id: "stp_3", no: 3, summary: "Edited 1 cell by hand" }, depth_left: 2 },
      "POST /api/v1/datasets/ds_1/undo": { step: { id: "stp_6" }, version: 5 },
      "POST /api/v1/datasets/ds_1/redo": { step: { id: "stp_7" }, version: 5 },
    });
    renderAt(<><CsvTab dataset={DS} /><Toaster /></>);
    const undo = await screen.findByRole("button", { name: "Undo" });
    await waitFor(() => expect(undo).toBeEnabled());
    expect(undo).toHaveAttribute("title", "Undo: Change 12 cells in 12 rows: city (Ctrl+Z)");
    fireEvent.click(undo);
    expect(await screen.findByText("Undid: Change 12 cells in 12 rows: city · now v5")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "y", ctrlKey: true });
    await waitFor(() => expect(posted(calls).map((c) => c.path)).toContain("/api/v1/datasets/ds_1/redo"));
  });

  it("is off when nothing is left to undo in a row", async () => {
    mockApi({ "GET /api/v1/datasets/ds_1/history": { version: 4, undo: null, redo: null, depth_left: 0 } });
    renderAt(<CsvTab dataset={DS} />);
    const undo = await screen.findByRole("button", { name: "Undo" });
    await waitFor(() => expect(undo).toHaveAttribute("title", expect.stringContaining("up to 3 changes in a row")));
    expect(undo).toBeDisabled();
    expect(screen.getByRole("button", { name: "Redo" })).toBeDisabled();
  });
});
