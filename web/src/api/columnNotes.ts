// Column notes (PRD LOAD-7, TRD §4.2): what a column means, from a data dictionary the user linked or
// from the web. Metadata, not data: they have no version, so one query per dataset.
import { useQuery, type QueryClient } from "@tanstack/react-query";
import { request } from "./client";

export interface ColumnNote {
  column: string;
  kind: "dictionary" | "web";
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

/** The first note per column: a data dictionary's before the web's (the server orders them so). */
export function notesByColumn(notes: ColumnNote[] | undefined): Record<string, ColumnNote> {
  const out: Record<string, ColumnNote> = {};
  for (const n of notes ?? []) if (!out[n.column]) out[n.column] = n;
  return out;
}

/** Read the data dictionary at a URL the user typed. A plain promise, not a hook: the import preview closes
 * as the upload ends, and the reading (up to a minute) finishes after it. */
export async function readDictionary(qc: QueryClient, datasetId: string, url: string): Promise<ColumnNotes> {
  const out = await request<ColumnNotes>("POST", `/api/v1/datasets/${datasetId}/dictionary`, { url });
  qc.invalidateQueries({ queryKey: columnNotesKey(datasetId) });
  return out;
}
