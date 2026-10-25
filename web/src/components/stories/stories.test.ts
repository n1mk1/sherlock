import { describe, expect, it } from "vitest";
import { plainText } from "@/api/stories";
import type { Card, CardBody } from "@/api/types";
import { fromDoc, toDoc } from "./CardEditor";

const body: CardBody = {
  blocks: [
    {
      type: "paragraph",
      runs: [
        { type: "label", ref: "sex", text: "Women" },
        { type: "text", text: " survived at " },
        { type: "chip", id: "c1", key: "rate_female", value: "74%", unverified: false },
        { type: "text", text: "." },
      ],
    },
    { type: "bullets", runs: [{ type: "text", text: "Men at " }, { type: "chip", id: "c2", key: "rate_male", value: "19%", unverified: false }] },
    { type: "bullets", runs: [{ type: "text", text: "Typed by hand: " }, { type: "chip", id: "u1", key: null, value: "42", unverified: true }] },
    { type: "paragraph", runs: [{ type: "text", text: "Closing line." }] },
  ],
};

describe("the card editor document", () => {
  it("round-trips a body through the TipTap document", () => {
    expect(fromDoc(toDoc(body))).toEqual(body);
  });

  it("groups consecutive bullets into one list and keeps paragraphs apart", () => {
    const doc = toDoc(body);
    expect(doc.content?.map((n) => n.type)).toEqual(["paragraph", "bulletList", "paragraph"]);
    expect(doc.content?.[1].content).toHaveLength(2);
  });

  it("gives an empty body one empty paragraph, and drops empty paragraphs on the way back", () => {
    const doc = toDoc({ blocks: [] });
    expect(doc).toEqual({ type: "doc", content: [{ type: "paragraph" }] });
    expect(fromDoc(doc)).toEqual({ blocks: [] });
  });

  it("gives a chip inserted without an id a fresh one", () => {
    const out = fromDoc({ type: "doc", content: [{ type: "paragraph", content: [{ type: "chip", attrs: { key: "n", value: "891" } }] }] });
    const run = out.blocks[0].runs[0];
    expect(run).toMatchObject({ type: "chip", key: "n", value: "891", unverified: false });
    expect(run.type === "chip" && run.id).toMatch(/^e/);
  });
});

describe("a card as plain words", () => {
  it("joins blocks, shows labels, and prefers the fact sheet's value for bound chips", () => {
    const facts = { rate_female: { formatted: "74.2%" } } as unknown as Card["facts"];
    expect(plainText(body, facts)).toBe("Women survived at 74.2%. Men at 19% Typed by hand: 42 Closing line.");
  });

  it("falls back to the chip's own value without facts", () => {
    expect(plainText({ blocks: [body.blocks[0]] })).toBe("Women survived at 74%.");
  });
});
