import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// Checks src/app/theme.css against the UI/UX brief §2.1 and the §8 contrast rules.
const css = readFileSync(path.resolve(process.cwd(), "src/app/theme.css"), "utf8");

function block(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`));
  if (!match) throw new Error(`no block for ${selector}`);
  return match[1];
}

function token(body: string, name: string): string {
  const match = body.match(new RegExp(`--${name}:\\s*([^;]+);`));
  if (!match) throw new Error(`no --${name}`);
  return match[1].trim();
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const ACCENTS = {
  verdigris: ["#2f6b62", "#6fb3a6"],
  arcane: ["#6a4c93", "#a88bd6"],
  ember: ["#9a4a2e", "#e08a62"],
  aether: ["#2f6690", "#6fb4d9"],
  brass: ["#8a5a33", "#c9a063"],
} as const;

const light = block(":root");
const dark = block(".dark");

describe("theme tokens", () => {
  it("has the brief's base surfaces in both modes", () => {
    expect(token(light, "background")).toBe("#eeece8");
    expect(token(light, "card")).toBe("#f7f6f3");
    expect(token(dark, "background")).toBe("#1e1f22");
    expect(token(dark, "card")).toBe("#25272b");
    expect(token(light, "accent")).toBe(ACCENTS.verdigris[0]); // default without data-accent
    expect(token(dark, "accent")).toBe(ACCENTS.verdigris[1]);
  });

  it.each(Object.entries(ACCENTS))("defines %s in light and dark", (name, [lightHex, darkHex]) => {
    expect(token(block(`:root[data-accent="${name}"]`), "accent")).toBe(lightHex);
    expect(token(block(`:root.dark[data-accent="${name}"]`), "accent")).toBe(darkHex);
  });

  it("switches info to brass under aether so chips stay distinct", () => {
    expect(token(block(':root[data-accent="aether"]'), "info")).toBe("#8a5a33");
    expect(token(block(':root.dark[data-accent="aether"]'), "info")).toBe("#c9a063");
  });

  it.each(Object.entries(ACCENTS))("%s passes 4.5:1 on ground and card", (_, [lightHex, darkHex]) => {
    for (const surface of ["background", "card"]) {
      expect(contrast(lightHex, token(light, surface))).toBeGreaterThanOrEqual(4.5);
      expect(contrast(darkHex, token(dark, surface))).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("keeps muted text at 4.5:1 and chart greys at 3:1 on cards", () => {
    for (const mode of [light, dark]) {
      expect(contrast(token(mode, "muted-foreground"), token(mode, "card"))).toBeGreaterThanOrEqual(4.5);
      for (let i = 1; i <= 5; i++) {
        expect(contrast(token(mode, `chart-${i}`), token(mode, "card"))).toBeGreaterThanOrEqual(3);
      }
    }
  });
});
