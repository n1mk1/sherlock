import { describe, expect, it } from "vitest";
import { drawMarks } from "./Grid";

/** A 2D context that records its styles, with a working save/restore stack. */
function fakeContext() {
  const stack: object[] = [];
  return {
    fillStyle: "#text", strokeStyle: "#border", lineWidth: 1,
    save() { stack.push({ fillStyle: this.fillStyle, strokeStyle: this.strokeStyle, lineWidth: this.lineWidth }); },
    restore() { Object.assign(this, stack.pop()); },
    strokeRect() {}, beginPath() {}, arc() {}, fill() {}, moveTo() {}, lineTo() {}, stroke() {}, setLineDash() {},
  };
}

const T = { accent: "#accent", info: "#info", warning: "#warning", destructive: "#red", muted: "#muted" };
const RECT = { x: 0, y: 0, width: 100, height: 32 };

describe("the CSV grid's cell marks", () => {
  it.each(["unsaved", "changed", "flagged", "invalid", "struck"])(
    "%s leaves the canvas styles as it found them, so the next cell's text keeps its colour",
    (mark) => {
      const ctx = fakeContext();
      drawMarks(ctx as unknown as CanvasRenderingContext2D, RECT, mark, mark === "unsaved", T);
      expect([ctx.fillStyle, ctx.strokeStyle, ctx.lineWidth]).toEqual(["#text", "#border", 1]);
    },
  );
});
