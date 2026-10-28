// The cleaning plan by severity level (PRD CLEAN-8c, App Flow §4.1), in a real browser against the same
// server with recorded model replies: the sample's plan opens at once on code's default levels, grouped by
// level with "Worth a look" unticked; a level's box ticks the whole level; a check of your own is counted at
// once; a suggested check is kept; nothing is cleaned until Start.
import path from "node:path";
import { expect, test } from "@playwright/test";
import { expectNoAxeViolations } from "./axe";

test("the plan groups fixes by level and starts worth-a-look fixes unticked", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Try the Titanic sample" }).click();
  await page.getByRole("button", { name: "Clean with AI" }).click({ timeout: 120_000 });
  await expect(page.getByRole("heading", { name: "Cleaning plan" })).toBeVisible({ timeout: 60_000 });

  // The recorded replies have no rating, so the review falls back to code's default levels.
  await expect(page.getByText("Reviewing…")).toHaveCount(0, { timeout: 60_000 });
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

  // Suggested checks (PRD CLEAN-14): the recorded reply suggests one; code counted it; Keep runs it.
  const suggested = page.getByRole("region", { name: "Suggested checks" });
  await expect(suggested).toContainText("parch is between 0 and 5");
  await expect(suggested).toContainText("suggested by Sherlock");
  // Its threshold is a suggestion: edited before it's kept.
  await suggested.getByRole("button", { name: "Edit parch is between 0 and 5" }).click();
  await suggested.getByRole("textbox", { name: "Highest" }).fill("4");
  await suggested.getByRole("button", { name: "Save" }).click();
  await expect(suggested).toContainText("parch is between 0 and 4");
  await suggested.getByRole("listitem").filter({ hasText: "parch" }).getByRole("button", { name: "Keep" }).click();
  await expect(page.getByRole("checkbox", { name: "parch: your check" })).toBeVisible();
  // Dismiss the other: it goes for good, and the group with it.
  await expect(suggested).toContainText("embarked is one of S, C, Q");
  await suggested.getByRole("button", { name: "Dismiss" }).click();
  await expect(page.getByRole("region", { name: "Suggested checks" })).toHaveCount(0);

  await page.getByRole("button", { name: "Discard" }).click();
  await expect(page.getByRole("button", { name: "Clean with AI" })).toBeVisible();
});

test("a run from the plan reports what became of each issue", async ({ page }) => {
  // The small messy file the Cleaner's tests use, with their recorded replies (PRD CLEAN-6).
  await page.goto("/");
  await page.getByRole("navigation", { name: "Your CSVs" }).getByTestId("file-input").setInputFiles(path.join(import.meta.dirname, "messy.csv"));
  await page.getByRole("dialog").getByRole("button", { name: /^Import/ }).click();  // the import preview
  await page.getByRole("button", { name: "Clean with AI" }).click({ timeout: 120_000 });
  await expect(page.getByRole("heading", { name: "Cleaning plan" })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: /Start cleaning \(\d+\)/ }).click();
  // The run ends in `ready`: the grid opens, with Changes and its report in the right panel.
  await expect(page.getByRole("toolbar", { name: "CSV tools" })).toBeVisible({ timeout: 180_000 });
  await page.getByRole("button", { name: "Cleaning report" }).click();
  const report = page.getByRole("dialog");
  await expect(report).toContainText(/Step \d+ /);  // a step the run committed: a real run
  await expect(report.getByRole("term")).toHaveText(["fixed", "flagged", "checked and kept", "couldn't fix", "not attempted"]);
  await expect(report).toContainText(/\d+ found · \d+ marked, not changed \(leakage and ID columns\) · no rows deleted/);
});
