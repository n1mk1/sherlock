// The flow a judge follows (Implementation Plan D8.6 and D9 exit), end to end in a real browser against
// one server with recorded model replies: sample → the offer → Clean it myself → the grid with Changes →
// a sourced number with "How do you know?" → a chart → what drives survival, with its model card → change
// a cell from chat (a proposal, approved) and see it in the grid → Export notebook → the .ipynb downloads →
// undo the cell edit. axe checks each screen on the way, and the app runs under its production CSP with no
// refusal.
import { expect, test, type Page } from "@playwright/test";
import { expectNoAxeViolations, watchCsp } from "./axe";

async function ask(page: Page, text: string) {
  const bar = page.getByLabel("Ask Sherlock");
  await bar.fill(text);
  await bar.press("Enter");
}

test("from the sample to a downloaded notebook", async ({ page }) => {
  const cspRefusals = watchCsp(page);
  const home = await page.goto("/");
  expect(home!.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(home!.headers()["x-content-type-options"]).toBe("nosniff");
  await expect(page.getByRole("button", { name: "Try with sample (Titanic)" })).toBeVisible();
  await expectNoAxeViolations(page, "the empty library");
  await page.getByRole("button", { name: "Try with sample (Titanic)" }).click();

  // The offer, then Clean it myself: the dataset is ready as it is, on its one view.
  await page.getByRole("button", { name: "Clean it myself" }).click({ timeout: 120_000 });
  await expect(page).toHaveURL(/\/d\/[^/?]+$/);
  const datasetId = page.url().match(/\/d\/([^/?]+)$/)![1];
  expect(datasetId).toBeTruthy();
  await expect(page.getByRole("tablist")).toHaveCount(0); // no tab switcher
  // The grid is editable: its toolbar is on, and its cells aren't read-only.
  await expect(page.getByRole("toolbar", { name: "CSV tools" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("button", { name: "Add row" })).toBeEnabled();
  // Glide draws on a canvas and keeps a visually hidden table of the visible cells beside it (role grid),
  // so it's found by CSS: role queries skip hidden elements.
  const grid = page.locator('table[role="grid"]');
  await expect(grid.locator('[role="gridcell"][aria-readonly="false"]').first()).toBeAttached({ timeout: 30_000 });
  // The right panel is the cleaning side panel: Changes, with the cleaning report one click away.
  const changes = page.getByRole("complementary").filter({ hasText: "Changes" });
  await expect(changes.getByRole("heading", { name: "Changes" })).toBeVisible();
  await expect(changes.getByRole("button", { name: "Full cleaning report" })).toBeVisible();
  await expectNoAxeViolations(page, "the grid with Changes");

  // A number: the answer's numbers are chips, and "How do you know?" shows the query.
  await ask(page, "average fare by class");
  await expect(page.getByText("First class paid the most on average")).toBeVisible({ timeout: 60_000 });
  const thread = page.getByRole("log", { name: "Chat with Sherlock" });
  await expect(thread.getByTitle("Computed from the query below").first()).toBeVisible();
  await thread.getByText("How do you know?").last().click();
  await expect(thread.getByText(/AVG\(/).last()).toBeVisible();

  // A chart: the answer carries a chart block, drawn in the thread.
  await ask(page, "survival rate by sex as a chart");
  const chart = thread.getByRole("figure", { name: "Chart" }).last();
  await expect(chart).toBeVisible({ timeout: 60_000 });
  await expect(chart.locator("svg").first()).toBeVisible();
  await expect(thread.getByRole("button", { name: /Pin to dashboard|Add to Flow/ })).toHaveCount(0);

  // What drives a column: the importance table and the model card.
  await ask(page, "what drives survival?");
  await expect(thread.getByRole("columnheader", { name: "importance" }).last()).toBeVisible({ timeout: 120_000 });
  await thread.getByRole("button", { name: "Model card" }).last().click();
  const card = page.getByRole("dialog", { name: "Model card" });
  await expect(card.getByRole("heading", { name: "Importance" })).toBeVisible();
  await card.getByRole("button", { name: "Close" }).click();
  await expect(card).toBeHidden();

  // Change a cell from chat: a proposal that applies only when approved, then the grid shows it.
  await ask(page, "set the fare of row 1 to 100");
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText(/Saved as v\d+/)).toBeVisible();
  // Glide's hidden table holds only the columns on screen, and fare is scrolled off, so the new version's
  // row is read through the rows API the grid itself reads.
  await expect.poll(async () => {
    const page1 = await (await page.request.get(`/api/v1/datasets/${datasetId}/rows?limit=5`)).json() as
      { rows: { _row_id: number; cells: Record<string, unknown> }[] };
    return page1.rows.find((r) => r._row_id === 1)?.cells.fare;
  }, { timeout: 30_000 }).toBe(100);
  await expect(grid.locator('[role="gridcell"]').first()).toBeAttached();
  await expectNoAxeViolations(page, "the grid with the thread open");

  // Export the notebook from the Dataset menu: it downloads.
  await page.getByRole("button", { name: "Close the thread" }).click();
  await page.getByRole("button", { name: "Dataset menu" }).click();
  await page.getByRole("menuitem", { name: /Export notebook/ }).click();
  const dialog = page.getByRole("dialog", { name: "Export notebook" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Include data").uncheck();
  const download = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Export" }).click();
  expect((await download).suggestedFilename()).toMatch(/\.ipynb$/);
  await expect(dialog).toBeHidden();

  // Undo the cell edit from the Changes panel: the undone step stays listed, set aside but readable.
  await changes.getByRole("button", { name: "Undo", exact: true }).first().click();
  await expect(changes.getByText("· undone").first()).toBeVisible({ timeout: 30_000 });
  await expectNoAxeViolations(page, "the Changes panel with an undone step");

  expect(cspRefusals).toEqual([]);
});
