import { describe, expect, it } from "vitest";
import { mergeCanvas, type CanvasDoc } from "@/api/canvas";

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

  it("puts a card on the canvas once when both sides placed it", () => {
    const base: CanvasDoc = { nodes: [], edges: [] };
    const local: CanvasDoc = { nodes: [node("mine", 0, { sherlock: { card_id: "crd_1" } })], edges: [] };
    const server: CanvasDoc = { nodes: [node("theirs", 50, { sherlock: { card_id: "crd_1" } })], edges: [] };
    expect(mergeCanvas(base, local, server).nodes.map((n) => n.id)).toEqual(["theirs"]);
  });
});
