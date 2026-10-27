import { describe, expect, it } from "vitest";
import { mergeCanvas, same, type CanvasDoc } from "@/api/canvas";
import { copyOf, History, pasteOf, toFlow, type FlowEdge, type FlowNode } from "@/components/flow/model";

const node = (id: string, x = 0, extra: object = {}) => ({ id, type: "text" as const, x, y: 0, width: 240, height: 170, ...extra });
const edge = (id: string, a: string, b: string) => ({ id, fromNode: a, toNode: b });

describe("mergeCanvas", () => {
  it("keeps this tab's changes and the server's (an AI synthesis placed meanwhile)", () => {
    const base: CanvasDoc = { nodes: [node("a"), node("b")], edges: [] };
    const local: CanvasDoc = { nodes: [node("a", 300), node("note", 0, { text: "mine" })], edges: [] }; // moved a, removed b, added a note
    const server: CanvasDoc = { nodes: [node("a"), node("b"), node("s", 600, { sherlock: { card_id: "crd_s" } })],
      edges: [edge("e1", "a", "s"), edge("e2", "b", "s")] };
    const out = mergeCanvas(base, local, server);
    expect(out.nodes.map((n) => [n.id, n.x])).toEqual([["a", 300], ["s", 600], ["note", 0]]);
    expect(out.edges.map((e) => e.id)).toEqual(["e1"]); // e2 went with b
  });

  it("keeps another tab's move when the base came from the server (keys sorted) and this tab wrote its own order", () => {
    // As the API sends it (sorted keys) and as FlowTab's toDoc writes it.
    const srv = (id: string, x: number) => ({ height: 170, id, sherlock: { card_id: `crd_${id}` }, text: "", type: "text" as const, width: 240, x, y: 0 });
    const loc = (id: string, x: number) => ({ id, type: "text" as const, x, y: 0, width: 240, height: 170, text: "", sherlock: { card_id: `crd_${id}` } });
    const base: CanvasDoc = { nodes: [srv("a", 0), srv("b", 0)], edges: [] };
    const local: CanvasDoc = { nodes: [loc("a", 0), loc("b", 500)], edges: [] }; // this tab moved b
    const server: CanvasDoc = { nodes: [srv("a", 900), srv("b", 0)], edges: [] }; // another tab moved a
    expect(mergeCanvas(base, local, server).nodes.map((n) => [n.id, n.x])).toEqual([["a", 900], ["b", 500]]);
    expect(same(srv("a", 0), loc("a", 0))).toBe(true);
  });

  it("puts a card on the canvas once when both sides placed it", () => {
    const base: CanvasDoc = { nodes: [], edges: [] };
    const local: CanvasDoc = { nodes: [node("mine", 0, { sherlock: { card_id: "crd_1" } })], edges: [] };
    const server: CanvasDoc = { nodes: [node("theirs", 50, { sherlock: { card_id: "crd_1" } })], edges: [] };
    expect(mergeCanvas(base, local, server).nodes.map((n) => n.id)).toEqual(["theirs"]);
  });
});

describe("History", () => {
  const doc = (...nodes: ReturnType<typeof node>[]): CanvasDoc => ({ nodes, edges: [] });

  it("undoes and redoes a step, giving back the same document", () => {
    const h = new History();
    const before = doc(node("a", 0));
    const after = doc(node("a", 300));
    h.push({ id: 1, label: "Move", before, after });
    expect(h.undoLabel).toBe("Move");
    const undone = h.undo(after)!;
    expect(same(undone, before)).toBe(true);
    expect(h.redoLabel).toBe("Move");
    expect(same(h.redo(undone)!, after)).toBe(true);
  });

  it("keeps a synthesis the AI placed after the step being undone", () => {
    const h = new History();
    h.push({ id: 1, label: "Add note", before: doc(node("a")), after: doc(node("a"), node("n", 0, { text: "mine" })) });
    const current = doc(node("a"), node("n", 0, { text: "mine" }), node("s", 600, { sherlock: { card_id: "crd_s" } }));
    expect(h.undo(current)!.nodes.map((n) => n.id)).toEqual(["a", "s"]);
  });

  it("reverts an older step from its toast and keeps the later ones", () => {
    const h = new History();
    h.push({ id: 1, label: "Remove", before: doc(node("a"), node("b")), after: doc(node("a")) });
    h.push({ id: 2, label: "Move", before: doc(node("a")), after: doc(node("a", 300)) });
    const out = h.revert(1, doc(node("a", 300)))!;
    expect(out.nodes.map((n) => [n.id, n.x])).toEqual([["a", 300], ["b", 0]]);
    expect(h.undoLabel).toBe("Move");
  });

  it("records nothing for a change that changed nothing, and a new step clears redo", () => {
    const h = new History();
    h.push({ id: 1, label: "Move", before: doc(node("a")), after: doc(node("a")) });
    expect(h.undoLabel).toBeNull();
    h.push({ id: 2, label: "Move", before: doc(node("a")), after: doc(node("a", 10)) });
    h.undo(doc(node("a", 10)));
    h.push({ id: 3, label: "Add note", before: doc(node("a")), after: doc(node("a"), node("n", 0, { text: "x" })) });
    expect(h.redoLabel).toBeNull();
  });
});

describe("copy, paste and duplicate", () => {
  const card = (id: string, cardId: string, x = 0): FlowNode =>
    ({ id, type: "card", position: { x, y: 0 }, data: { cardId }, selected: true }) as FlowNode;
  const note = (id: string, text: string, x = 0): FlowNode =>
    ({ id, type: "note", position: { x, y: 0 }, data: { text }, selected: true }) as FlowNode;
  const link = (id: string, s: string, t: string) =>
    ({ id, source: s, target: t, type: "labeled", data: { madeBy: "ai", kind: "summarized_in", label: "summarized in" } }) as FlowEdge;

  it("copies the picked nodes and only the edges among them", () => {
    const clip = copyOf([note("n1", "a"), note("n2", "b"), note("n3", "c")], [link("e1", "n1", "n2"), link("e2", "n2", "n3")],
      (n) => n.id !== "n3");
    expect(clip.nodes.map((n) => n.id)).toEqual(["n1", "n2"]);
    expect(clip.edges.map((e) => e.id)).toEqual(["e1"]);
  });

  it("pastes notes as new nodes, offset, joined by user edges", () => {
    const clip = copyOf([note("n1", "a"), note("n2", "b", 100)], [link("e1", "n1", "n2")], () => true);
    const out = pasteOf(clip, [], 44);
    expect(out.nodes.map((n) => n.position.x)).toEqual([44, 144]);
    expect(out.nodes.every((n) => !["n1", "n2"].includes(n.id))).toBe(true);
    expect(out.edges).toHaveLength(1);
    expect(out.edges[0]).toMatchObject({ source: out.nodes[0].id, target: out.nodes[1].id, data: { madeBy: "user" } });
  });

  it("selects a card that's already on the canvas instead of placing it twice", () => {
    const existing = [card("c1", "crd_1")];
    const clip = copyOf([card("c1", "crd_1"), note("n1", "a")], [link("e1", "n1", "c1")], () => true);
    const out = pasteOf(clip, existing, 44);
    expect(out.nodes.map((n) => n.type)).toEqual(["note"]);
    expect(out.select).toContain("c1");
    expect(out.edges[0]).toMatchObject({ target: "c1" });
  });

  it("leaves empty notes and hidden cards out of a copy", () => {
    const hidden = { ...card("c1", "crd_1"), hidden: true } as FlowNode;
    expect(copyOf([note("n1", ""), hidden, note("n2", "x")], [], () => true).nodes.map((n) => n.id)).toEqual(["n2"]);
  });
});

describe("toFlow", () => {
  it("keeps a saved width within what a resize may reach", () => {
    const out = toFlow({ nodes: [node("n1", 0, { text: "x", width: 900 }), node("n2", 0, { text: "y", width: 0 })], edges: [] }, new Map(), []);
    expect(out.nodes.map((n) => n.width)).toEqual([480, 220]);
  });
});
