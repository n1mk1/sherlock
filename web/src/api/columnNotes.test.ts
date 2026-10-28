import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { columnNotesKey, notesByColumn, readDay, readDictionary, siteOf, useColumnNotes, type ColumnNote } from "@/api/columnNotes";
import { useDatasetEvents } from "@/api/queries";
import { stubEventSource } from "@/test/eventsource";
import { mockApi } from "@/test/render";

const note = (column: string, kind: ColumnNote["kind"], description: string): ColumnNote => ({
  column, kind, description, excerpt: null, source_url: "https://codebook.example.org", source_title: null, retrieved_at: "2026-10-26",
});

describe("column notes (PRD LOAD-7)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows a column's dictionary note before its found or web note", () => {
    const by = notesByColumn([note("region", "dictionary", "From the codebook."), note("region", "found", "Found."),
      note("region", "web", "From the web."), note("status", "web", "A status."), note("fare", "found", "A fare.")]);
    expect(by.region.description).toBe("From the codebook.");
    expect(by.status.kind).toBe("web");
    expect(by.fare.kind).toBe("found");
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

  it("reads the notes again when the stream says grounding found some (notes.updated)", async () => {
    const ES = stubEventSource();
    let reads = 0;
    mockApi({
      "GET /api/v1/datasets/ds_1/column-notes": () => ({ notes: reads++ ? [note("fare", "found", "The fare.")] : [], note: null }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client: qc }, children);
    const { result } = renderHook(() => {
      useDatasetEvents("ds_1");
      return useColumnNotes("ds_1");
    }, { wrapper });
    await waitFor(() => expect(result.current.data?.notes).toEqual([]));
    act(() => ES.last().emit("notes.updated", { dataset_id: "ds_1" }, 4));
    await waitFor(() => expect(result.current.data?.notes).toHaveLength(1));
    expect(result.current.data?.notes[0]).toMatchObject({ column: "fare", kind: "found" });
    expect(reads).toBe(2);
  });
});

describe("where a source is from and when it was read", () => {
  it("names a page by its domain, without www.", () => {
    expect(siteOf("https://www.kaggle.com/datasets/titanic")).toBe("kaggle.com");
    expect(siteOf("https://codebook.example.org/vars")).toBe("codebook.example.org");
    expect(siteOf("not a url")).toBe("not a url");
  });

  it("reads the day from a timestamp, and keeps a date as it is", () => {
    expect(readDay("2026-10-27T09:30:00Z")).toBe("2026-10-27");
    expect(readDay("2026-10-27")).toBe("2026-10-27");
    expect(readDay("yesterday")).toBe("yesterday");
  });
});
