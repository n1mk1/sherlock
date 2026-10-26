// axe-core in the end-to-end flow (UI brief §8): each screen the flow reaches is checked against WCAG 2.2
// AA, so the live test's findings (separators without a value, a role-less drag handle, 22px story chips,
// faded undone steps) stay fixed. axe runs through page.evaluate, which the app's CSP doesn't apply to, so
// the same run also proves the CSP lets the app work.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { expect, type Page } from "@playwright/test";

const source = readFileSync(createRequire(import.meta.url).resolve("axe-core/axe.min.js"), "utf8");

interface Violation { id: string; impact: string | null; nodes: { target: string[]; failureSummary?: string }[] }
// The page's globals, typed here: the e2e project has no DOM lib.
type AxePage = {
  axe?: { run: (ctx: unknown, opts: object) => Promise<{ violations: Violation[] }> };
  document: { getAnimations: () => { playState: string; effect: { getTiming: () => { iterations?: number } } | null }[] };
};

export async function expectNoAxeViolations(page: Page, screen: string) {
  if (!(await page.evaluate(() => "axe" in globalThis))) await page.evaluate(source);
  // Contrast is measured on what's drawn, so a toast caught mid-fade would fail. Wait for the finite
  // animations and transitions to end; spinners and skeleton pulses repeat forever and don't count.
  await page.waitForFunction(() => (globalThis as unknown as AxePage).document.getAnimations()
    .every((a) => a.playState !== "running" || a.effect?.getTiming().iterations === Infinity), undefined, { timeout: 10_000 });
  const violations = await page.evaluate(async () => {
    const g = globalThis as unknown as AxePage;
    const result = await g.axe!.run(g.document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
    });
    return result.violations.map((v) => ({
      id: v.id, impact: v.impact, nodes: v.nodes.slice(0, 3).map((n) => ({ target: n.target, failureSummary: n.failureSummary })),
    }));
  });
  const report = violations.map((v) => `${v.impact} ${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`);
  expect(report, `axe on ${screen}`).toEqual([]);
}

/** Collects the browser's CSP refusals ("Refused to load … violates the following Content Security Policy"). */
export function watchCsp(page: Page): string[] {
  const refusals: string[] = [];
  page.on("console", (m) => {
    if (/Content Security Policy/i.test(m.text())) refusals.push(m.text());
  });
  return refusals;
}
