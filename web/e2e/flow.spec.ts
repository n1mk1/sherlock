// The flow a judge follows (Implementation Plan D8.6 and D9 exit), end to end in a real browser against
// one server with recorded model replies: sample → dashboard with stories → ask a question → change a
// cell from chat (a proposal, approved) → its stories update → Flow: place two cards, make sense of
// them → Export notebook → the .ipynb downloads.
import { expect, test, type Page } from "@playwright/test";

async function ask(page: Page, text: string) {
  const bar = page.getByLabel("Ask Sherlock");
  await bar.fill(text);
  await bar.press("Enter");
}

test("from the sample to a downloaded notebook", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Try with sample (Titanic)" }).click();
  await page.getByRole("button", { name: "Use as is" }).click();

  // The dashboard builds itself, then its story cards are written.
  await expect(page.getByRole("heading", { name: "Stories" })).toBeVisible();
  await expect(page.getByRole("article").first()).toBeVisible({ timeout: 120_000 });
  const datasetId = page.url().match(/\/d\/([^/]+)\//)![1];

  // Ask a question: a sourced answer.
  await ask(page, "average fare by class");
  await expect(page.getByText("First class paid the most on average")).toBeVisible({ timeout: 60_000 });
  await page.getByText("How do you know?").last().click();
  await expect(page.getByText(/AVG\(/).last()).toBeVisible();

  // Change a cell from chat on the CSV tab: a proposal that applies only when approved.
  await page.getByRole("tab", { name: "CSV" }).click();
  await ask(page, "set the fare of row 1 to 100");
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText(/Saved as v\d+/)).toBeVisible();
  // The cascade re-queries the widgets that read fare and tells their stories again.
  await expect(page.getByText(/stor(y|ies) updated/)).toBeVisible({ timeout: 90_000 });

  // Flow: two cards on the canvas, made sense of. The chat thread is closed first, as it covers the canvas.
  await page.getByRole("button", { name: "Close the thread" }).click();
  await page.getByRole("tab", { name: "Flow" }).click();
  const cards = await (await page.request.get(`/api/v1/datasets/${datasetId}/cards`)).json() as
    { kind: string; widget_id: string | null; facts: Record<string, unknown> }[];
  const widgets = (await (await page.request.get(`/api/v1/datasets/${datasetId}/widgets`)).json()).widgets as { id: string; title: string }[];
  const titles = cards.filter((c) => c.kind === "widget" && "n" in c.facts)
    .map((c) => widgets.find((w) => w.id === c.widget_id)!.title).slice(0, 2);
  expect(titles).toHaveLength(2);
  for (const title of titles) {
    const row = page.getByRole("button", { name: `${title}, not placed` });
    await row.focus();
    await row.press("Enter");
    await expect(page.getByRole("button", { name: `${title}, on canvas` })).toBeVisible();
  }
  const nodes = page.locator(".react-flow__node-card");
  await expect(nodes).toHaveCount(2);
  await nodes.nth(0).click({ position: { x: 20, y: 12 } });
  await nodes.nth(1).click({ position: { x: 20, y: 12 }, modifiers: ["Shift"] });
  await expect(page.getByText("2 cards selected")).toBeVisible();
  await page.getByRole("button", { name: "Make sense of this", exact: true }).click();
  await expect(page.locator(".react-flow__node-card")).toHaveCount(3, { timeout: 60_000 });
  await expect(page.getByText("summarized in").first()).toBeVisible();

  // Export the notebook: it downloads.
  await page.getByRole("button", { name: "Dataset menu" }).click();
  await page.getByRole("menuitem", { name: /Export notebook/ }).click();
  const dialog = page.getByRole("dialog", { name: "Export notebook" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Include data").uncheck();
  const download = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Export" }).click();
  expect((await download).suggestedFilename()).toMatch(/\.ipynb$/);
});
