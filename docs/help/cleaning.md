# Cleaning

## What the cleaner does
The cleaner works through the issues it found (spacing and case, typos in categories, numbers stored as text, dates in mixed formats, placeholders like N/A) one at a time. Each fix is code that runs in a sandbox, is checked, and becomes a step with a version of its own. While it runs, a live log shows each issue it tries, and the CSV grid is read-only; Stop ends the run and keeps the steps it committed. Clean with AI in the CSV toolbar opens the cleaning plan in the right panel any time, with the scope: the whole file, the selected rows, or the rows added since the last clean. Cells you edited by hand are left alone.

## The cleaning plan
Clean with AI first shows the plan: what Sherlock found in the current version, in groups such as types and parsing, missing values, and spelling, each with how many rows it affects, a few example values and the fix it would try. Every fix starts ticked. Untick one to leave it out, or untick a whole group with the box on its header; the run skips those, and the report lists them as left out of the plan. Columns that look like IDs or record the outcome are listed under Marked, not changed, and are never changed. Nothing changes until you press Start cleaning; Discard closes the plan.

## Edit the plan
Press the pencil on a fix to say in your own words what to do instead; Reset puts Sherlock's wording back. Add a step adds one of your own: pick a column (or Rows) and write what to do. Your steps run first. You can also ask in the chat while the plan is open, for example "don't touch outliers" or "also trim spaces in name"; the plan changes at once and the reply says what changed. The cleaner writes code that follows your words, but every check still applies: a step that would fill gaps with a word like Unknown, or hide more than a fifth of the rows, is skipped with the reason. A step you asked for that Sherlock isn't sure about is kept with a flag, so you can undo it in Changes. The report lists your steps and what happened to each.

## Quarantined rows
Rows the cleaner can't trust are quarantined, not deleted. They stay in the CSV tab, dimmed with their row number struck through, and are left out of charts, answers and models. To bring one back, select a cell in it, press Restore in the CSV toolbar, then Save changes.

## Undo a step
Open the CSV tab and its Changes panel. Each step still in the data has Undo. Undoing an earlier step asks first, then replays the later ones, so nothing else is lost; if a replay fails, nothing changes. Undoing the automatic typing step (step 1) warns that every column turns back into text.

## Missing values
Missing values stay missing unless a fix is clearly safe. Sherlock doesn't invent values to fill gaps.
