import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ColumnNote } from "@/api/columnNotes";
import { mockApi, renderAt } from "@/test/render";
import { drawMarks, Grid, NoteTooltip } from "./Grid";

// Glide draws on a canvas, which jsdom lacks: the editor is a stand-in that shows it was drawn, and it keeps
// the hover handler so a test can hover a header.
const editor = vi.hoisted(() => ({ onItemHovered: undefined as undefined | ((args: unknown) => void) }));
vi.mock("@glideapps/glide-data-grid", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@glideapps/glide-data-grid")>()),
  DataEditor: (props: { onItemHovered?: (args: unknown) => void }) => {
    editor.onItemHovered = props.onItemHovered;
    return <div data-testid="editor" />;
  },
}));
vi.mock("@/lib/tokens", () => ({ resolveTokens: (names: Record<string, string>) => names })); // reads colours off a canvas

afterEach(() => vi.unstubAllGlobals());

/** A 2D context that records its styles, with a working save/restore stack. */
function fakeContext() {
  const stack: object[] = [];
  return {
    fillStyle: "#text", strokeStyle: "#border", lineWidth: 1,
    save() { stack.push({ fillStyle: this.fillStyle, strokeStyle: this.strokeStyle, lineWidth: this.lineWidth }); },
    restore() { Object.assign(this, stack.pop()); },
    strokeRect() {}, beginPath() {}, arc() {}, fill() {}, moveTo() {}, lineTo() {}, stroke() {}, setLineDash() {},
  };
}

const T = { accent: "#accent", info: "#info", warning: "#warning", destructive: "#red", muted: "#muted" };
const RECT = { x: 0, y: 0, width: 100, height: 32 };

describe("the CSV grid's cell marks", () => {
  it.each(["unsaved", "changed", "flagged", "invalid", "struck"])(
    "%s leaves the canvas styles as it found them, so the next cell's text keeps its colour",
    (mark) => {
      const ctx = fakeContext();
      drawMarks(ctx as unknown as CanvasRenderingContext2D, RECT, mark, mark === "unsaved", T);
      expect([ctx.fillStyle, ctx.strokeStyle, ctx.lineWidth]).toEqual(["#text", "#border", 1]);
    },
  );
});

describe("the CSV grid's view", () => {
  const PAGE_BODY = { version: 2, offset: 0, total: 1, columns: [{ name: "_row_id", type: "BIGINT" }, { name: "fare", type: "DOUBLE" }],
    rows: [{ _row_id: 1, cells: { fare: 7.25 }, marks: {}, quarantined: false }] };
  const props = {
    datasetId: "ds_1", sort: null, onSort: () => {}, selectionId: null, matches: new Set<string>(), card: [],
    buffer: undefined, onEdit: () => {}, onLoaded: () => {},
  };

  it("asks for a failed page twice more, then says so with Retry", async () => {
    let calls = 0;
    let fail = true;
    mockApi({
      "GET /api/v1/datasets/ds_1/rows": () => {
        calls += 1;
        return fail ? new Response(JSON.stringify({ error: { code: "internal", message: "Server error" } }), { status: 500 }) : PAGE_BODY;
      },
    });
    renderAt(<Grid {...props} version={2} onSelection={() => {}} />);
    const retry = await screen.findByRole("button", { name: "Retry" }, { timeout: 4000 });
    expect(calls).toBe(3);
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load these rows");
    fail = false;
    fireEvent.click(retry);
    expect(await screen.findByTestId("editor")).toBeInTheDocument();
    expect(calls).toBe(4);
  });

  it("recovers by itself when a retry gets the page", async () => {
    let calls = 0;
    mockApi({
      "GET /api/v1/datasets/ds_1/rows": () => {
        calls += 1;
        return calls === 1 ? new Response("{}", { status: 503 }) : PAGE_BODY;
      },
    });
    renderAt(<Grid {...props} version={2} onSelection={() => {}} />);
    expect(await screen.findByTestId("editor", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(calls).toBe(2);
  });

  it("clears the selected cells when a new version is shown", async () => {
    mockApi({ "GET /api/v1/datasets/ds_1/rows": PAGE_BODY });
    const onSelection = vi.fn();
    function Host() { // the CSV tab passes the version; a new one comes as a new prop
      const [version, setVersion] = useState(2);
      return <><button type="button" onClick={() => setVersion(3)}>v3 arrives</button><Grid {...props} version={version} onSelection={onSelection} /></>;
    }
    renderAt(<Host />);
    await screen.findByTestId("editor");
    onSelection.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "v3 arrives" }));
    expect(onSelection).toHaveBeenCalledWith(expect.objectContaining({ rowIds: [], cells: 0, current: null }));
  });
});

describe("the column notes under a header", () => {
  const note = (kind: ColumnNote["kind"]): ColumnNote => ({
    column: "fare", kind, description: "The price paid for the ticket.", excerpt: "Fare: price paid, in pounds.",
    source_url: "https://www.codebook.example.org/vars", source_title: "Titanic codebook", retrieved_at: "2026-10-27",
  });

  it.each([
    ["dictionary", "From the data dictionary you linked at codebook.example.org, retrieved 2026-10-27."],
    ["found", "From a data dictionary Sherlock found at codebook.example.org, retrieved 2026-10-27."],
    ["web", "From the web at codebook.example.org, retrieved 2026-10-27."],
  ] as const)("says where a %s note is from", (kind, line) => {
    renderAt(<NoteTooltip note={note(kind)} bounds={{ x: 0, y: 0, width: 110, height: 32 }} />);
    expect(screen.getByTestId("column-note")).toHaveTextContent(line);
    expect(screen.getByTestId("column-note")).toHaveTextContent("Not computed from your data.");
  });

  it("shows a found dictionary's note when its column's header is hovered", async () => {
    const props = {
      datasetId: "ds_1", sort: null, onSort: () => {}, selectionId: null, matches: new Set<string>(), card: [],
      buffer: undefined, onEdit: () => {}, onLoaded: () => {}, version: 2, onSelection: () => {},
    };
    mockApi({
      "GET /api/v1/datasets/ds_1/rows": { version: 2, offset: 0, total: 1, columns: [{ name: "_row_id", type: "BIGINT" }, { name: "fare", type: "DOUBLE" }],
        rows: [{ _row_id: 1, cells: { fare: 7.25 }, marks: {}, quarantined: false }] },
      "GET /api/v1/datasets/ds_1/column-notes": { notes: [note("found")] },
    });
    renderAt(<Grid {...props} />);
    await screen.findByTestId("editor");
    // The notes arrive after the rows: hover again until the handler has them (column 1 is `fare`).
    await waitFor(() => {
      act(() => editor.onItemHovered?.({ kind: "header", location: [1, -1], bounds: { x: 0, y: 0, width: 110, height: 32 } }));
      expect(screen.getByTestId("column-note")).toHaveTextContent("From a data dictionary Sherlock found");
    });
  });
});
