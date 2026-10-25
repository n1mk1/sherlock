import { beforeEach, describe, expect, it } from "vitest";
import { fitsType, typeLabel } from "@/lib/cells";
import { pendingCount, toBatch, useEdits } from "@/state/edits";

describe("typed text in the grid", () => {
  it("knows what fits a column", () => {
    expect(fitsType("BIGINT", "42")).toBe(true);
    expect(fitsType("BIGINT", "4.2")).toBe(false);
    expect(fitsType("DOUBLE", "4.2e3")).toBe(true);
    expect(fitsType("DOUBLE", "abc")).toBe(false);
    expect(fitsType("BOOLEAN", "Yes")).toBe(true);
    expect(fitsType("DATE", "2024-02-30x")).toBe(false);
    expect(fitsType("VARCHAR", "anything")).toBe(true);
    expect(fitsType("BIGINT", "")).toBe(true);
    expect(typeLabel("TIMESTAMP")).toBe("datetime");
  });
});

describe("the pending edits buffer", () => {
  beforeEach(() => {
    localStorage.clear();
    useEdits.setState({ buffers: {} });
  });

  it("collects edits, rows and deletions into one batch, and survives a reload", () => {
    const s = useEdits.getState();
    s.setCell("ds", 7, { row_id: 3, column: "age", value: "30", old: 22 });
    const temp = s.addRow("ds", 7);
    useEdits.getState().setNewCell("ds", temp, "name", "New");
    useEdits.getState().toggleDelete("ds", 7, [5]);
    const b = useEdits.getState().buffers.ds;
    expect(pendingCount(b)).toBe(3);
    expect(toBatch(b)).toMatchObject({
      base_version: 7, edits: [{ row_id: 3, column: "age", value: "30" }],
      new_rows: [{ temp_id: temp, cells: { name: "New" } }], deleted_row_ids: [5],
    });
    expect(localStorage.getItem("sherlock:edits:ds:7")).toContain("\"age\"");
    useEdits.setState({ buffers: {} });
    useEdits.getState().hydrate("ds");
    expect(pendingCount(useEdits.getState().buffers.ds)).toBe(3);
  });

  it("drops an edit typed back to its original value, and edits of a deleted row", () => {
    const s = useEdits.getState();
    s.setCell("ds", 2, { row_id: 1, column: "age", value: "5", old: 22 });
    useEdits.getState().setCell("ds", 2, { row_id: 1, column: "age", value: "22", old: "5" });
    expect(pendingCount(useEdits.getState().buffers.ds)).toBe(0);
    useEdits.getState().setCell("ds", 2, { row_id: 4, column: "age", value: "9", old: 1 });
    useEdits.getState().toggleDelete("ds", 2, [4]);
    expect(Object.keys(useEdits.getState().buffers.ds.edits)).toEqual([]);
  });

  it("rebases onto a newer version, dropping the cells kept as theirs", () => {
    const s = useEdits.getState();
    s.setCell("ds", 2, { row_id: 1, column: "age", value: "5", old: 22 });
    useEdits.getState().setCell("ds", 2, { row_id: 2, column: "age", value: "6", old: 23 });
    useEdits.getState().rebase("ds", 3, ["1:age"]);
    const b = useEdits.getState().buffers.ds;
    expect(b.base).toBe(3);
    expect(Object.keys(b.edits)).toEqual(["2:age"]);
    expect(localStorage.getItem("sherlock:edits:ds:2")).toBeNull();
  });
});
