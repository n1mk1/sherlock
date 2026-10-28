import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// Checks src/app/theme.css: the base surfaces, the accents and hues, and contrast (4.5:1 for text, 3:1 for charts).
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

const ACCENTS = ["verdigris", "arcane", "ember", "aether", "brass"] as const;
const HUES = ["violet", "blue", "teal", "green", "amber", "red"] as const;

const light = block(":root");
const dark = block(".dark");

describe("theme tokens", () => {
  it("has a canvas, chrome and default accent in both modes", () => {
    expect(token(light, "card")).toBe("#ffffff");
    expect(token(light, "background")).toMatch(/^#[0-9a-f]{6}$/);
    expect(token(dark, "background")).toMatch(/^#[0-9a-f]{6}$/);
    expect(token(light, "accent")).toBe(token(block(':root[data-accent="verdigris"]'), "accent")); // default without data-accent
    expect(token(dark, "accent")).toBe(token(block(':root.dark[data-accent="verdigris"]'), "accent"));
  });

  it.each(ACCENTS)("%s passes 4.5:1 on chrome and canvas", (name) => {
    for (const surface of ["background", "card"]) {
      expect(contrast(token(block(`:root[data-accent="${name}"]`), "accent"), token(light, surface))).toBeGreaterThanOrEqual(4.5);
      expect(contrast(token(block(`:root.dark[data-accent="${name}"]`), "accent"), token(dark, surface))).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each(HUES)("the %s hue reads as text in both modes", (hue) => {
    for (const mode of [light, dark]) {
      for (const surface of ["background", "card"]) {
        expect(contrast(token(mode, hue), token(mode, surface))).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("keeps muted text at 4.5:1 and chart greys at 3:1 on the canvas", () => {
    for (const mode of [light, dark]) {
      expect(contrast(token(mode, "muted-foreground"), token(mode, "card"))).toBeGreaterThanOrEqual(4.5);
      expect(contrast(token(mode, "muted-foreground"), token(mode, "background"))).toBeGreaterThanOrEqual(4.5);
      for (let i = 1; i <= 5; i++) {
        expect(contrast(token(mode, `chart-${i}`), token(mode, "card"))).toBeGreaterThanOrEqual(3);
      }
    }
  });
});
