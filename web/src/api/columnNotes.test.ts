import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { columnNotesKey, notesByColumn, readDictionary, type ColumnNote } from "@/api/columnNotes";

const note = (column: string, kind: ColumnNote["kind"], description: string): ColumnNote => ({
  column, kind, description, excerpt: null, source_url: "https://codebook.example.org", source_title: null, retrieved_at: "2026-10-26",
});

describe("column notes (PRD LOAD-7)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows a column's dictionary note before its web note", () => {
    const by = notesByColumn([note("region", "dictionary", "From the codebook."), note("region", "web", "From the web."),
      note("status", "web", "A status.")]);
    expect(by.region.description).toBe("From the codebook.");
    expect(by.status.kind).toBe("web");
    expect(notesByColumn(undefined)).toEqual({});
  });

  it("reads a dictionary the user typed and refreshes the notes", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ notes: [note("region", "dictionary", "d")], note: null }),
      { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    const out = await readDictionary(qc, "ds_1", "https://codebook.example.org/vars");
    expect(out.notes).toHaveLength(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/datasets/ds_1/dictionary", expect.objectContaining({
      method: "POST", body: JSON.stringify({ url: "https://codebook.example.org/vars" }),
    }));
    expect(spy).toHaveBeenCalledWith({ queryKey: columnNotesKey("ds_1") });
  });
});
