// Column notes (PRD LOAD-7, TRD §4.2): what a column means, from a data dictionary the user linked or
// from the web. Metadata, not data: they have no version, so one query per dataset.
import { useQuery, type QueryClient } from "@tanstack/react-query";
import { request } from "./client";

export interface ColumnNote {
  column: string;
  // "found": a data dictionary Sherlock found on the web itself (docs/plans/tavily.md §3.2), not one the user linked.
  kind: "dictionary" | "found" | "web";
  description: string; // Sherlock's sentence from the source, with no digits
  excerpt: string | null; // the source's own words, as the page has them
  source_url: string;
  source_title: string | null;
  retrieved_at: string;
}

export interface ColumnNotes {
  notes: ColumnNote[];
  note?: string | null; // the one line shown when a dictionary couldn't be read
}

export const columnNotesKey = (id: string) => ["column-notes", id] as const;

export function useColumnNotes(datasetId: string | undefined) {
  return useQuery({
    queryKey: columnNotesKey(datasetId ?? ""),
    enabled: !!datasetId,
    staleTime: 60_000,
    queryFn: () => request<ColumnNotes>("GET", `/api/v1/datasets/${datasetId}/column-notes`),
  });
}

/** The first note per column: the user's dictionary, then one Sherlock found, then the web's (the server orders them so). */
export function notesByColumn(notes: ColumnNote[] | undefined): Record<string, ColumnNote> {
  const out: Record<string, ColumnNote> = {};
  for (const n of notes ?? []) if (!out[n.column]) out[n.column] = n;
  return out;
}

/** A web page's domain for display: its hostname without `www.`, or the address as given when it doesn't parse. */
export function siteOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** The day a page was read, as the date part of its timestamp (`2026-10-27T…` reads `2026-10-27`). */
export function readDay(retrievedAt: string): string {
  return /^\d{4}-\d{2}-\d{2}/.test(retrievedAt) ? retrievedAt.slice(0, 10) : retrievedAt;
}

/** Read the data dictionary at a URL the user typed. A plain promise, not a hook: the import preview closes
 * as the upload ends, and the reading (up to a minute) finishes after it. */
export async function readDictionary(qc: QueryClient, datasetId: string, url: string): Promise<ColumnNotes> {
  const out = await request<ColumnNotes>("POST", `/api/v1/datasets/${datasetId}/dictionary`, { url });
  qc.invalidateQueries({ queryKey: columnNotesKey(datasetId) });
  return out;
}
