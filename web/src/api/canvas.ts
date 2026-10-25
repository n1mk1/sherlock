// The Flow canvas (TRD §4.7): one JSON Canvas document per dataset, saved with the etag it was read at.
// A save that loses the race (409), or a canvas.updated from the AI or another tab, merges this tab's
// unsaved changes onto the server's document (three-way, against the last synced copy), so neither
// side's change is lost.
import { useQuery } from "@tanstack/react-query";
import { request } from "./client";

export interface CanvasNode {
  id: string;
  type: "text" | "file" | "link" | "group";
  x: number;
  y: number;
  width: number;
  height: number;
  text?: string;
  color?: string;
  sherlock?: { card_id: string };
}

export interface CanvasEdge {
  id: string;
  fromNode: string;
  toNode: string;
  fromSide?: "top" | "right" | "bottom" | "left";
  toSide?: "top" | "right" | "bottom" | "left";
  label?: string;
  sherlock?: { made_by: "user" | "ai"; kind: "summarized_in" | "next" | "contrasts" | "custom" };
}

export interface CanvasDoc {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
}

export const canvasKey = (datasetId: string) => ["canvas", datasetId] as const;

// Etags this tab wrote: their canvas.updated events are our own saves coming back, not news.
export const ownEtags = new Set<string>();

export function useCanvas(datasetId: string) {
  return useQuery({
    queryKey: canvasKey(datasetId),
    queryFn: () => request<{ canvas: CanvasDoc; etag: string }>("GET", `/api/v1/datasets/${datasetId}/canvas`),
    staleTime: Infinity, // canvas.updated invalidates it
  });
}

export async function saveCanvas(datasetId: string, canvas: CanvasDoc, etag: string): Promise<string> {
  const { etag: next } = await request<{ etag: string }>("PUT", `/api/v1/datasets/${datasetId}/canvas`, { canvas, etag });
  ownEtags.add(next);
  return next;
}

const byId = <T extends { id: string }>(list: T[]) => new Map(list.map((x) => [x.id, x]));
// Compared with keys sorted: the server stores the canvas with sorted keys, and this tab writes its
// own order, so a plain JSON.stringify called every node "edited here" and undid other tabs' moves.
const canonical = (v: unknown): unknown =>
  Array.isArray(v) ? v.map(canonical)
    : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, canonical((v as Record<string, unknown>)[k])]))
      : v;
export const same = (a: unknown, b: unknown) => JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));

/** Three-way merge: what this tab changed since `base` (added, removed, edited), applied to `server`. */
export function mergeCanvas(base: CanvasDoc, local: CanvasDoc, server: CanvasDoc): CanvasDoc {
  const merge = <T extends { id: string }>(b: T[], l: T[], s: T[]) => {
    const bm = byId(b), lm = byId(l), out = byId(s);
    for (const [id, item] of lm) {
      const was = bm.get(id);
      if (!was) out.set(id, item); // added here
      else if (!same(was, item) && out.has(id)) out.set(id, item); // edited here (and still there)
    }
    for (const id of bm.keys()) if (!lm.has(id)) out.delete(id); // removed here
    return [...out.values()];
  };
  const nodes = merge(base.nodes, local.nodes, server.nodes);
  const ids = new Set(nodes.map((n) => n.id));
  const edges = merge(base.edges, local.edges, server.edges).filter((e) => ids.has(e.fromNode) && ids.has(e.toNode));
  // A card is on the canvas once: when both sides placed it, the server's node wins.
  const seen = new Set<string>();
  const unique = nodes.filter((n) => {
    const cid = n.sherlock?.card_id;
    if (!cid) return true;
    if (seen.has(cid)) return false;
    seen.add(cid);
    return true;
  });
  const kept = new Set(unique.map((n) => n.id));
  return { nodes: unique, edges: edges.filter((e) => kept.has(e.fromNode) && kept.has(e.toNode)) };
}
