// The Flow canvas's node and edge model (App Flow §12, TRD §4.7): conversions between the JSON Canvas
// document and React Flow's nodes and edges, the undo history (merged onto newer copies, so undoing
// never takes back what the AI or another tab did meanwhile), and copy, paste and duplicate.
import { MarkerType, type Edge, type Node } from "@xyflow/react";
import { mergeCanvas, same, type CanvasDoc } from "@/api/canvas";
import type { Card } from "@/api/types";

export const CARD_W = 240;
export const NOTE_W = 220;
export const WIDTH = { card: [CARD_W, 480], note: [160, 480] } as const; // what a resize may reach
export const GRID = 22; // the dot grid: nodes snap to it, and copies land two steps down and right

export type CardData = { cardId: string };
export type NoteData = { text: string; editing?: boolean };
export type CardNodeT = Node<CardData, "card">;
export type NoteNodeT = Node<NoteData, "note">;
export type FlowNode = CardNodeT | NoteNodeT;
export type EdgeData = { label?: string; madeBy: "user" | "ai"; kind: NonNullable<CanvasDoc["edges"][number]["sherlock"]>["kind"]; editing?: boolean };
export type FlowEdge = Edge<EdgeData, "labeled">;

export const ARROW = { type: MarkerType.ArrowClosed, width: 14, height: 14 };
export const newId = (p: string) => `${p}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
const clamp = (v: number, [lo, hi]: readonly [number, number]) => Math.min(hi, Math.max(lo, Math.round(v)));

export function toFlow(doc: CanvasDoc, cards: Map<string, Card>, prev: FlowNode[]): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const selected = new Set(prev.filter((n) => n.selected).map((n) => n.id));
  const nodes: FlowNode[] = doc.nodes.map((n) => {
    const base = { id: n.id, position: { x: n.x, y: n.y }, selected: selected.has(n.id) };
    if (n.sherlock?.card_id) {
      // A soft-deleted card's node stays hidden, so restoring the card puts it back in place.
      return { ...base, type: "card", data: { cardId: n.sherlock.card_id }, hidden: !cards.has(n.sherlock.card_id),
        width: clamp(n.width || CARD_W, WIDTH.card) } as CardNodeT;
    }
    return { ...base, type: "note", data: { text: n.text ?? "" }, width: clamp(n.width || NOTE_W, WIDTH.note) } as NoteNodeT;
  });
  const edges: FlowEdge[] = doc.edges.map((e) => ({
    id: e.id, source: e.fromNode, target: e.toNode, type: "labeled",
    data: { label: e.label, madeBy: e.sherlock?.made_by ?? "user", kind: e.sherlock?.kind ?? "custom" },
    markerEnd: ARROW,
  }));
  return { nodes, edges };
}

export function toDoc(all: FlowNode[], allEdges: FlowEdge[]): CanvasDoc {
  // A new note still being written for the first time isn't saved until it has words.
  const nodes = all.filter((n) => !(n.type === "note" && n.data.editing && !n.data.text));
  const kept = new Set(nodes.map((n) => n.id));
  const edges = allEdges.filter((e) => kept.has(e.source) && kept.has(e.target));
  return {
    nodes: nodes.map((n) => {
      const w = Math.round(n.width ?? n.measured?.width ?? (n.type === "card" ? CARD_W : NOTE_W));
      const h = Math.round(n.measured?.height ?? (n.type === "card" ? 170 : 80));
      const base = { id: n.id, type: "text" as const, x: Math.round(n.position.x), y: Math.round(n.position.y), width: w, height: h };
      return n.type === "card" ? { ...base, text: "", sherlock: { card_id: n.data.cardId } } : { ...base, text: n.data.text };
    }),
    edges: edges.map((e) => ({
      id: e.id, fromNode: e.source, toNode: e.target, ...(e.data?.label ? { label: e.data.label } : {}),
      sherlock: { made_by: e.data?.madeBy ?? "user", kind: e.data?.kind ?? "custom" },
    })),
  };
}

// --- undo and redo -------------------------------------------------------------------------------

export interface Step { id: number; label: string; before: CanvasDoc; after: CanvasDoc }
const MAX_STEPS = 50;

/** This tab's finished changes, newest last. Undoing a step applies its after → before change to the
 * current document (a three-way merge), so changes made since by the AI or another tab stay. */
export class History {
  past: Step[] = [];
  future: Step[] = [];

  push(step: Step) {
    if (same(step.before, step.after)) return;
    this.past = [...this.past, step].slice(-MAX_STEPS);
    this.future = [];
  }

  undo(current: CanvasDoc): CanvasDoc | null {
    const step = this.past.at(-1);
    if (!step) return null;
    this.past = this.past.slice(0, -1);
    this.future = [...this.future, step];
    return mergeCanvas(step.after, step.before, current);
  }

  redo(current: CanvasDoc): CanvasDoc | null {
    const step = this.future.at(-1);
    if (!step) return null;
    this.future = this.future.slice(0, -1);
    this.past = [...this.past, step];
    return mergeCanvas(step.before, step.after, current);
  }

  /** Undoes one step wherever it is (a toast's Undo after later steps); the latest is a plain undo. */
  revert(id: number, current: CanvasDoc): CanvasDoc | null {
    if (this.past.at(-1)?.id === id) return this.undo(current);
    const step = this.past.find((s) => s.id === id);
    if (!step) return null;
    this.past = this.past.filter((s) => s !== step);
    return mergeCanvas(step.after, step.before, current);
  }

  get undoLabel() { return this.past.at(-1)?.label ?? null; }
  get redoLabel() { return this.future.at(-1)?.label ?? null; }
}

// --- copy, paste, duplicate ----------------------------------------------------------------------

export interface Clip { nodes: FlowNode[]; edges: FlowEdge[] }

/** The selected nodes (hidden ones and empty new notes left out) and the edges among them. */
export function copyOf(nodes: FlowNode[], edges: FlowEdge[], pick: (n: FlowNode) => boolean): Clip {
  const picked = nodes.filter((n) => !n.hidden && pick(n) && !(n.type === "note" && !n.data.text));
  const ids = new Set(picked.map((n) => n.id));
  return { nodes: picked, edges: edges.filter((e) => ids.has(e.source) && ids.has(e.target)) };
}

/** A clip placed `offset` px down and right, as new nodes and edges. A card is on a canvas once
 * (TRD §4.7): a card already there isn't added again; it's selected, and edges join its node. */
export function pasteOf(clip: Clip, existing: FlowNode[], offset: number): { nodes: FlowNode[]; edges: FlowEdge[]; select: string[] } {
  const ids = new Map<string, string>();
  const nodes: FlowNode[] = [];
  for (const n of clip.nodes) {
    const there = n.type === "card" ? existing.find((x) => x.type === "card" && x.data.cardId === n.data.cardId) : undefined;
    if (there) { ids.set(n.id, there.id); continue; }
    const id = newId("nd");
    ids.set(n.id, id);
    nodes.push({ ...n, id, position: { x: n.position.x + offset, y: n.position.y + offset }, selected: true, measured: undefined,
      data: n.type === "note" ? { text: n.data.text } : n.data } as FlowNode);
  }
  const edges: FlowEdge[] = clip.edges.map((e) => ({
    ...e, id: newId("ed"), source: ids.get(e.source)!, target: ids.get(e.target)!, selected: false,
    data: { ...e.data!, madeBy: "user" as const, editing: false },
  })).filter((e) => e.source !== e.target);
  return { nodes, edges, select: [...ids.values()] };
}
