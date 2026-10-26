// The flow a judge follows (Implementation Plan D8.6 and D9 exit), end to end in a real browser against
// one server with recorded model replies: sample → dashboard with stories → ask a question → change a
// cell from chat (a proposal, approved) → its stories update → Flow: place two cards, make sense of
// them → Export notebook → the .ipynb downloads → change a chart from chat, and undo it.
import { expect, test, type Page } from "@playwright/test";

async function ask(page: Page, text: string) {
  const bar = page.getByLabel("Ask Sherlock");
  await bar.fill(text);
  await bar.press("Enter");
}

test("from the sample to a downloaded notebook", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Try with sample (Titanic)" }).click();
  // Clean it myself: the dashboard builds on the data as it is while the CSV tab opens (read-only until then).
  await page.getByRole("button", { name: "Clean it myself" }).click();
  await expect(page).toHaveURL(/\/csv$/);
  const dashboardTab = page.getByRole("tab", { name: "Dashboard" });
  await expect(dashboardTab).not.toHaveAttribute("aria-disabled", /.*/, { timeout: 120_000 });
  await dashboardTab.click();

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
  // The second from the keyboard: a focused node is added with Shift+Enter.
  await nodes.nth(1).focus();
  await nodes.nth(1).press("Shift+Enter");
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
  await expect(dialog).toBeHidden();

  // Change a widget from chat (plan 1.5): the focused KPI becomes a pie drawn from its new query (the old
  // query's one-column rows can't show the slices), and the answer's Undo puts it back.
  const widget = (title: string) =>
    page.locator("article[data-widget-id]").filter({ has: page.getByRole("heading", { name: title, exact: true }) });
  await page.getByRole("tab", { name: "Dashboard" }).click();
  await widget("Average fare paid").getByRole("heading").click();
  await expect(page.getByTitle("Clear the context")).toHaveText("Average fare paid");
  await ask(page, "make it a pie chart");
  const pie = widget("Average fare by sex");
  await expect(pie.getByText("female", { exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(pie.getByText("male", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Undo", exact: true }).last().click();
  await expect(page.getByText("The widget is back as it was.")).toBeVisible();
  await expect(widget("Average fare paid")).toBeVisible();
  await expect(widget("Average fare paid").getByText("female", { exact: true })).toHaveCount(0);
});
