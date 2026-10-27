// The cleaning plan by severity level (PRD CLEAN-8c, App Flow §4.1), in a real browser against the same
// server with recorded model replies: the sample's plan opens at once on code's default levels, grouped by
// level with "Worth a look" unticked; a level's box ticks the whole level; nothing is cleaned until Start.
import { expect, test } from "@playwright/test";
import { expectNoAxeViolations } from "./axe";

test("the plan groups fixes by level and starts worth-a-look fixes unticked", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Try with sample (Titanic)" }).click();
  await page.getByRole("button", { name: "Clean with AI" }).click({ timeout: 120_000 });
  await expect(page.getByRole("heading", { name: /Cleaning plan · v\d+/ })).toBeVisible({ timeout: 60_000 });

  // The recorded replies have no rating, so the review falls back: every fix shows its default level.
  await expect(page.getByText("Reviewing…")).toHaveCount(0, { timeout: 60_000 });
  await expect(page.getByText("(default level)").first()).toBeVisible();
  const headings = await page.getByRole("heading", { level: 3 }).allTextContents();
  expect(headings).toContain("Worth a look");
  expect(headings).toContain("Marked, not changed");
  expect(headings.indexOf("Worth a look")).toBeLessThan(headings.indexOf("Marked, not changed"));

  // Missing ages are probably real: listed, but not ticked until the user asks.
  const look = page.getByRole("region", { name: "Worth a look" });
  const missingAge = look.getByRole("checkbox", { name: "age: missing values" });
  await expect(missingAge).not.toBeChecked();
  await look.getByRole("checkbox", { name: "Worth a look: tick all" }).click(); // saved, then shown
  await expect(missingAge).toBeChecked();
  await expectNoAxeViolations(page, "the cleaning plan by level");

  // Add a check (PRD CLEAN-13): code counts it on the current version as soon as it's saved.
  await page.getByRole("button", { name: "Add a check" }).click();
  const form = page.getByRole("group", { name: "Add a check" });
  await form.getByRole("combobox", { name: "Column" }).selectOption("fare");
  await form.getByRole("textbox", { name: "Highest" }).fill("100");
  await form.getByRole("button", { name: "Add check" }).click();
  const kept = page.getByRole("region", { name: "Marked, not changed" });  // flagged: listed, not changed
  const check = kept.getByRole("listitem").filter({ hasText: "your check" });
  await expect(check).toContainText("fare is at most 100");
  await expect(check).toContainText(/\d+/);
  await check.getByRole("button", { name: "Turn off your check on fare" }).click();
  await expect(kept.getByText("fare is at most 100")).toHaveCount(0);

  await page.getByRole("button", { name: "Discard" }).click();
  await expect(page.getByRole("button", { name: "Clean with AI" })).toBeVisible();
});
