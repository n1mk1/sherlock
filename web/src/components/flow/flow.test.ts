import { describe, expect, it } from "vitest";
import { mergeCanvas, same, type CanvasDoc } from "@/api/canvas";

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
