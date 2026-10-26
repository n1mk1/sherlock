# Sherlock · App Flow

Version 1.0 · 2026-10-19 · Every screen, state, transition and edge case. Read with the [PRD](01-PRD.md) for requirement IDs and the [UI/UX Brief](03-UIUX-BRIEF.md) for how things look.

---

## 1. Map of the app

```
First visit ──► Empty library ──► (drop / upload / sample) ──► Import preview ──► Profiling
                                                                                   │
                                                                                   ▼
                                                                          Cleaning offer
                                                               ┌──────────────┴───────────────┐
                                                         Clean with AI                 Clean it myself
                                                               │                              │
                                                               ▼                              │
                                                        Cleaning plan (§4.1) ◄── chat edits it│
                                                  Mode: Run on its own ·                      │
                                                  Ask me before each fix (P1)                 │
                                                       │ Start cleaning      │                │
                                                       ▼                     ▼                │
                                                Headless cleaning   Step-by-step thread       │
                                                       │                     │                │
                                                       └──────► Dashboard build ◄─────────────┘ (and the CSV tab opens)
                                                                                │
                            ┌──────────────────────────────────┬────────────────┴────────────────┐
                            ▼                                  ▼                                 ▼
                       CSV tab                           Dashboard tab                       Flow tab
                 (grid · Changes panel)           (widgets · story cards)              (canvas · palette)
                            └──────────────────── chat bar on every tab ─────────────────────────┘
                                                  settings overlay (gear)
```

Routes (client-side):

| Route | Screen |
|---|---|
| `/` | Library; redirects to the last opened dataset if one exists |
| `/d/:datasetId` | Redirects to the dataset's last tab (or the default-tab setting) |
| `/d/:datasetId/csv` | CSV tab |
| `/d/:datasetId/dashboard` | Dashboard tab |
| `/d/:datasetId/flow` | Flow tab |
| `?settings=1` | Settings overlay on top of any route |
| `?widget=:id` | Dashboard tab with that widget highlighted and scrolled into view |
| `?rows=:selectionId` | CSV tab filtered to a saved row selection (used by "open these rows") |
| `?export=notebook` | The Export notebook dialog on top of any dataset route |

`?widget=:id` works the way clicking a card does. Once the widgets load, the dashboard scrolls to that widget and flashes it, then drops the parameter, so a reload doesn't flash it again. An ID that's no longer on the dashboard just opens the dashboard. Chat's "Open the widget" uses it.

The left panel and the chat bar exist on every dataset route.

---

## 2. First visit and the library

**State: no datasets.**
- The left panel shows "Your CSVs" with an empty list, Upload, Try with sample, and the gear.
- The centre shows the **empty state**: a large drop zone ("Drop a CSV anywhere"), an Upload button, "Try with sample (Titanic)", and one sentence: "Sherlock cleans it, charts it, models it, and tells you what it means. Every number shows its source."
- The right panel shows three placeholder card outlines with the text "Stories appear once the dashboard is built."
- The chat bar is present but its input is disabled with the placeholder "Load a CSV to start asking".

**Identity.** On the first request the server sets a `sherlock_uid` cookie (a random 256-bit token stored hashed, 1-year expiry, `SameSite=Lax`, `HttpOnly`; the web app is served from the same origin as the API so the cookie is always sent). Everything the user does is keyed to it. There is no login.

**Returning visit.** `/` redirects to the last opened dataset. If it was deleted or expired, the library shows with a toast: "That CSV is no longer available."

---

## 3. Loading a CSV

### 3.1 Entry points

| Entry | Behaviour |
|---|---|
| **Drag anywhere** | On `dragenter` over the window, a full-window overlay appears: dashed border, "Drop to import". It accepts one file. Multiple files: the first is imported, a toast says "Imported the first file; drop the others one at a time." |
| **Upload button** | OS file picker, accepts `.csv, .tsv, .txt`. |
| **Try with sample** | Loads the bundled Titanic file. If a dataset named "titanic3.csv (sample)" already exists in the library, it opens that one instead of creating a duplicate. |
| **Paste (P1)** | Pasting tabular text into the empty state or the library creates a dataset from it. |

With the cached seed that ships in the image (TRD §4.2), Try with sample opens a copy that is already **ready**: its cleaning steps, dashboard, story cards, analysis and a synthesis on the canvas, as the real model made them. There's no import preview, profiling or offer for it. Without the seed, the file is imported and goes through §3.2–§6 live.

### 3.2 Import preview (modal)

Shown as soon as a file is chosen. The preview is parsed client-side from the local file; nothing is uploaded until Import.

Contents:
- File name and size.
- **Delimiter** (auto-detected; dropdown: comma, tab, semicolon, pipe, other).
- **Encoding** (auto-detected; dropdown: UTF-8, UTF-8 with BOM, Latin-1, Windows-1252, UTF-16).
- **Header row** (auto-detected; number input; 0 = no header, columns get `col_1…`).
- **Skip rows** before the header (number, default 0).
- **Data dictionary URL** (optional, PRD LOAD-7): the address of a page that describes the columns, such as a codebook.
- A preview table of the first 20 rows as currently parsed, with column names in the header.
- A line: "Detected 14 columns · about 1,309 rows".
- Buttons: **Import** (primary) and **Cancel**.

Rules:
- Changing any control re-parses the preview (client-side with Papa Parse) within 500 ms.
- Import is disabled while 0 columns or 0 rows parse, with the reason under the button. A zero-byte file, a header-only file, or one with nothing left after skip rows shows "This file has no data rows." The server applies the same rule and creates no dataset.
- Duplicate column names get suffixes (`name`, `name_2`) and a note appears.
- Files over 50 MB are refused before upload with "This file is 73 MB. The limit is 50 MB."
- Files that look binary (NUL bytes in the first 64 KB, outside UTF-16) show "Couldn't read this as text. Is it a spreadsheet or a zip? Export it as CSV first."
- As built, the delimiter dropdown lists Comma, Tab, Semicolon and Pipe, plus "Other (…)" only when the detected delimiter is none of those. There's no field to type another delimiter. Not built yet (docs/BACKLOG.md).

**The data dictionary (PRD LOAD-7).** When the field holds a URL, the web app sends it to `POST /datasets/{id}/dictionary` once the upload is accepted, and the dialog closes as usual without waiting. Sherlock reads the page with Tavily (TRD §7.1.1) while the file profiles. When it's done, a toast says "Read the data dictionary: notes on 3 columns.", or gives the one line saying why it wasn't read ("Web search isn't set up on this server, so I didn't look this up on the web.", "I couldn't find column descriptions on that page.", …). The import is never held up or failed by it. The notes show in the CSV tab's column headers (§8.1).

Import uploads the raw file (with a progress bar for files > 2 MB), creates the dataset, and navigates to `/d/:id/dashboard` (or the default tab) in the **profiling** state. As built, the Import button shows a spinner while the upload runs; the byte-level progress bar for large files isn't built yet. Only the settings the user changed from what the preview detected are sent as import options; the server detects the rest itself. Until the status is **ready**, the centre panel of every tab route shows the profiling, offer, cleaning or build screen, except that the CSV tab shows the grid once the dataset has left profiling (offer, cleaning and building too; read-only, with a banner, while cleaning or building; §5, §8.1). Dashboard and Flow are disabled until then, with the tooltip "Available after cleaning" during cleaning and "Available once the dataset is ready" otherwise.

### 3.3 Profiling state

Centre: a spinner with "Reading titanic3.csv…" then "Profiling 14 columns…". Left panel row shows status "profiling". Chat bar enabled with the placeholder "Ask about this CSV (profiling in progress)"; questions queue until profiling ends. The right panel shows the three placeholder cards.

As built, the spinner's line follows the profile job: "Reading titanic3.csv…", then "Typing 14 columns…" (the typing step), then "Profiling 14 columns…". The chat bar shows that placeholder but is disabled while profiling (and on a failed dataset), so questions don't queue. Not built yet (docs/BACKLOG.md).

Failure: "Profiling failed: <reason>. You can delete this CSV and try again." with a Delete button. The dataset stays in the library marked "failed". As built: the screen shows the heading "Profiling failed" and "<reason>. You can delete this CSV and try again." but has no Delete button of its own; Delete is in the dataset menu (⋯) and the library row's menu. Not built yet (docs/BACKLOG.md).

Once the dataset leaves profiling, the CSV tab shows the grid of the current version (§8), with the changed, flagged and invalid marks and quarantined rows struck through.

---

## 4. Cleaning offer

Shown in the centre when profiling finishes and the "After upload" setting is "Ask me".

Contents:
- Heading: "Here's what I found in titanic3.csv".
- The one-line summary: top 3 issues by impact ("263 missing ages · 1,014 missing cabins · 2 columns look like they record the outcome").
- Every issue, with its count, examples and planned fix, is in the cleaning plan (§4.1).
- Two buttons: **Clean with AI** (primary) and **Clean it myself**.
- A checkbox: "Remember my choice" (writes the "After upload" setting), with the hint "· You can change this in Settings" beside it. Checked, Clean with AI saves `after_upload: always` and Clean it myself saves `never`.
- As built, under the heading, a line "1,309 rows · 14 columns · 7 issues", then the top three issues by severity as a list with icons ("263 missing in age", "boat records the outcome"); "Nothing that needs cleaning." when there are none.

Transitions:
- **Clean with AI** → §4.1 Cleaning plan: the centre shows "Diagnosing v2 of titanic3.csv…", then the plan. Nothing is cleaned until **Start cleaning**, which goes to §5 Headless cleaning.
- **Clean it myself** → §6 Dashboard build on the typed version (version 1 plus the automatic typing step, which runs on every path), and the CSV tab opens at once. Its grid is read-only while the build runs, with the banner "Building your dashboard · editing opens when it finishes"; then the user edits by hand or asks the chat (§8, §10). The CSV tab's "Clean with AI" button later shows a small dot until cleaning has run once. As built: the button has no dot. Not built yet (docs/BACKLOG.md).
- **Ask me before each fix (P1, the plan's Mode, PRD CLEAN-10)** → when it's built, Start opens the Dashboard tab with the chat thread expanded and the first proposed step as an approval card. Until then the Mode row shows it disabled with "comes later".

After upload set to skip the offer (an inline line says why, since a toast vanishes):
- **"Open the cleaning plan"** (stored as `always`): the profile job makes a draft plan and stops at `offer`, so the plan screen opens by itself. It says "Opened because After upload is “Open the cleaning plan” · Change"; Change opens Settings scrolled to After upload. **Discard** on the plan goes back to the offer, so the choice is always one click away. Nothing is cleaned without a click.
- **"I'll clean it myself"** (stored as `never`): the dashboard builds directly. The building screen says "Building without cleaning because After upload is “I'll clean it myself” · Change".

### 4.1 Cleaning plan (PRD CLEAN-8a)

What Clean with AI will try, shown before anything runs. Sherlock's code detectors diagnose the **current** version (its data card), so every count comes from code and no model is called. A plan made on an older version (the user edited cells, or undid a step, before starting) is diagnosed again and merged before it's shown or started: ticks are kept by issue, fixes that are no longer needed go, new ones come in ticked, and a toast says what changed.

Where it lives: not a modal, so the chat bar stays usable. From the offer the centre becomes the plan screen; from the CSV tab the plan opens in the right panel in place of Changes, so the grid stays visible (§8.4).

Contents:
- Header: "Cleaning plan · v2" and "Sherlock checked v2. Untick, edit or add steps, or ask in chat." While it's being made: "Diagnosing v2 of titanic3.csv…".
- The fixes in modules, in this order: Your steps · Types and parsing · Missing and placeholder values · Spelling and formatting · Duplicates and broken records · Outliers · Other checks · Marked, not changed. A module with nothing in it isn't shown. Each module header except Marked, not changed has a tri-state checkbox and "n of m" ticked.
- One row per fix, **every fix ticked**: checkbox, the column, the issue ("missing", "spacing or case variants"), the count, and Sherlock's planned action in one muted line. ▸ shows up to 5 example values as chips. When two findings would be the same fix (exact and near duplicates), the row is the more severe one, the one the Cleaner attempts.
- **Marked, not changed**: leakage and ID-like columns, and any issue on such a column, with the flag icon and the reason ("ticket looks like an ID column, so it is left as is") and no checkbox. They are never changed.
- **✎ on a fix** (PRD CLEAN-8b) turns its planned action into an instruction the user rewrites, in a textarea with Save, Cancel and Reset (Reset puts Sherlock's wording back). A rewritten fix shows the instruction marked "edited", with Sherlock's wording struck through and muted beneath.
- **An ambiguous-dates fix** (plan 2b.9) asks "Which order are these dates in?" under its action: a small table of up to three of its values with their day-first and month-first readings ("03/04/2021 · 3 Apr 2021 · 4 Mar 2021") and two toggle buttons, **Day first** and **Month first**. Picking one saves at once and marks that column of the table; picking it again clears it. Until one is picked, a muted line says "Every date here reads both ways, so Sherlock won't guess: without an order they stay text." (or, when some dates show their order, "Sherlock reads the dates that show their order; pick one to decide the rest."). The picked order runs as the user's instruction for the fix, with one diagnosis instead of the three-way vote, and the report lists it under "Your steps".
- **"+ Add a step"**: a column select (the file's columns, plus "Rows") and "What to do", then Add. The step goes under **Your steps** (first), ticked, with ✎ to reword it and × to remove it. A step added from chat says "· from chat".
- **Chat** stays usable: while the plan is open, the chat bar's placeholder reads "Ask Sherlock to change the plan…", and a message like "don't touch outliers", "leave cabin alone" or "also trim spaces in name" changes the plan at once. The reply, written by code, says what changed ("Unticked 1 fix: missing values in cabin."; "Added 1 step on name."), and the plan updates live (§10.3).
- Mode: "Run on its own" (selected) and "Ask me before each fix", disabled with "comes later" (PRD CLEAN-10).
- Footer: "n of m ticked" (and, past 20, "Sherlock tries up to 20 per run; your steps first, then the most severe"), "Cells you edited by hand are left alone and listed in the report.", **Discard** and **Start cleaning (n)**, disabled with nothing ticked, or while a ✎ editor or the Add a step form holds text that isn't saved.

Transitions:
- Ticking or unticking saves at once (nothing touches the data until Start).
- **Start cleaning** → §5 Headless cleaning with the plan: unticked fixes are skipped without a model call and logged "not in your plan"; the report lists them with "You left this out of the plan". Issues a fix exposes mid-run, which the plan didn't list, are still attempted. The user's steps run first; they and rewritten fixes follow the user's instruction, still under every hard check.
- A plan made on an older version keeps the user's steps while their column exists; a step on a column that's gone is dropped, and the toast says so.
- **Discard** → the offer again (from the CSV tab, the Changes panel).

---

## 5. Headless cleaning

**Centre panel (cleaning state).**
- Title "Cleaning titanic3.csv" and the sentence "Running on its own. You can switch CSVs; it keeps going."
- A progress bar: "Step 7 · embarked" and elapsed time.
- **Live log** (newest at the bottom, auto-scroll unless the user scrolled up): one entry per event with timestamp, an icon (✓ committed, ⚑ flagged, ↷ skipped, ● running), the column, what was tried (candidate chips), what was chosen, the gate outcome.
- **So far** card: issues found / fixed / flagged / rows deleted (always 0).
- **Checks** card: the verifiers with ✓ as they pass on the latest step; the budget line "7 of 20 issues tried · 0:24 of 5:00".
- Button: **Pause and review** (P1: switches to step-by-step for remaining issues). P0: **Stop** (ends the run; committed steps stay; the report is produced for what ran).

**Tabs.** CSV is enabled (shows the latest committed version, read-only while the job runs, with a banner "Cleaning in progress · editing resumes when it finishes"). Dashboard and Flow are disabled with the tooltip "Available after cleaning". The banner shows above the grid while the status is `cleaning` (and, with "Building your dashboard · editing opens when it finishes", while it's `building`); cells can't be edited, and Add row, Delete row and Restore are disabled with the reason. Clean with AI is disabled ("Cleaning is running.").

**Right panel.** The story placeholders with "Stories appear once the dashboard is built."

**Chat.** Enabled. Questions about the data run against the latest committed version and say so ("as of step 5"). As built: they run on the latest committed version, but the answer doesn't name the version or step. Not built yet (docs/BACKLOG.md).

**Leaving.** Switching to another dataset keeps the job running; the left panel row shows the progress bar and percentage. Coming back restores the log from the server.

**End of run.**
- The centre shows the **report** for 3 seconds (counts and the first three steps) with "View full report", then transitions automatically to the dashboard build. The full report lives in the CSV tab's Changes panel.
- On failure (server error, budget exceeded with zero steps): the centre shows the error and two buttons: **Build dashboard without cleaning** (uses the typed version) and **Try cleaning again**. As built, the dataset goes back to `offer` with `error` "Cleaning stopped: <reason>". The offer screen shows "<error>. Your data is safe; you can build the dashboard without cleaning or try again." above its buttons, and its two buttons read **Try cleaning again** (in place of Clean with AI; it opens a new cleaning plan) and **Build dashboard without cleaning** (in place of Clean it myself; it stays on the build screen rather than opening the CSV tab).
- **Stop**: the job is cancelled at once (a sandbox worker that's running is killed), committed steps stay, the report covers what ran (`ended_by: stopped`), and the dashboard build starts.
- **As built.**
  - The log is the dataset's event stream replayed from the start, keeping this job's `job.log` lines. An issue's "running" line ("263 missing values", "checking candidates") is replaced by its outcome when it arrives: the effect or the skip reason, the candidate chips with the chosen one filled, and the gate line in the gate's color.
  - A committed or flagged step's outcome line is written by code from the step's full-data verifier report, never by the model: "Changed 263 cells, quarantined 4 rows; 263 → 0 missing values" (the cells changed, the rows quarantined, then the issue's count before → after; a step the user added has no count). Under it, in smaller grey text, comes the model's own one-sentence description of the fix, only when it has no digits and no number in words; otherwise it's left out. Every outcome line of an issue the model worked on ends with that issue's model calls: "3 model calls · Nemotron-3-Ultra-550b-a55b, nemotron-3-super-120b-a12b · 12.3 s" (how many, which models in the order used, and their summed latency, from `llm_calls`).
  - Two skips explain a guess the Cleaner wouldn't make (PRD CLEAN-4b). When two candidates that pass every check give different values to the same cells, the line reads "Skipped: the candidates disagree on 57% of the cells they both change (Title case vs Most frequent spelling: mcdonald → Mcdonald vs McDonald; MCDONALD → Mcdonald vs McDonald)". A date column whose every value reads both ways shows "Left as text: every date reads both ways (03/04/2021 is 3 Apr 2021 or 4 Mar 2021; …), so the order is yours to choose: pick it in the cleaning plan", with the detail "needs your choice of order" and no "checking candidates" line before it, since no model is called.
  - The same digit rule covers the model's other words on the cleaning screens: a "Left as is" skip shows the diagnosis' cause only without numbers ("Left as is: the values look legitimate" otherwise), a decision's reason is left out when it has one, and a flag's reason and the step's review keep only the critic's concerns without one.
  - A run from a cleaning plan (§4.1) logs each fix the plan left unticked as a skip line, "You left this out of the plan" with the detail "not in your plan", with no "checking candidates" line before it: no model is called for it and it doesn't count against the 20-issue budget.
  - The user's own steps come first, each as "Your step: trim spaces in name" (running), then its outcome like any issue. One that would be skipped for low confidence commits with a flag instead: "low confidence (0.42); kept because you asked for it". The report's "Your steps" lists each step the user added or fix they rewrote with "done", "done with a flag", "skipped" (with the reason) or "not reached", and the decisions show "You asked: …".
  - "So far" and the budget line read the run's report, refreshed on every log line.
  - "Checks on the latest step" lists the hard verifiers of the last committed step, "No look-alike categories merged" (`merge_safety`) among them.
  - During `building`, the centre shows "Building your dashboard…" above the report summary: counts, the first three steps, and "View full report", a dialog with every step, skipped issue, hand-edited cell and decision.
  - The ready Dashboard tab shows the widgets. The same summary, titled "Last cleaning report", opens from the Changes panel's "Full cleaning report" (§8.5).
  - The full report ends with **How I worked it out** (collapsed): the run's model calls in order ("Diagnosed an issue", "Proposed fixes", "Reviewed a fix"), each with its model, time, tokens and repairs, then the total. A long run lists its first 500 calls and says how many more there were; the total counts them all (TRD §4.10 receipts).

---

## 6. Dashboard build

Centre: the grid appears with skeleton widgets in the layout the builder chose; each fills in as its query returns. Right panel: cards stream in as they pass verification, overview first. A card that still fails verification after one regeneration shows its fact sheet as bullets. A top banner "Building your dashboard… 6 of 8 widgets" disappears when done.

If the builder produces fewer than 3 valid widgets (odd file), the dashboard shows what it has plus an empty-state card: "I could only build 2 widgets for this file. Add one from chat, or tell me which columns matter."

When done, the dataset status becomes **ready**.

As built, while the status is `building`, the centre shows "Building your dashboard…" above the cleaning report summary (§5), and the job tray shows the build's progress ("Choosing charts", "Picking the story", "Adding widgets · 3 of 8"). The grid appears all at once when the status turns **ready**; the stories job then writes the cards, with "Writing the stories…" under three placeholders in the right panel (§7.4). The skeleton layout, widgets filling in one by one, cards streaming in during the build and the "6 of 8 widgets" banner are not built yet (docs/BACKLOG.md). A card whose story fails after one repair shows its fact sheet as bullets, as specified.

---

## 7. Dashboard tab

### 7.1 Layout and header

- Tabs CSV | Dashboard | Flow centred at the top.
- Under them: dataset name, "v7 · 6 steps" (click opens the Changes panel in the CSV tab), the **filter bar** (active global filter chip, selection chip, and a "Filter" button that opens a small filter builder), then **Add widget**, **Edit layout**, and the dataset menu (⋯): Export notebook · Download CSV · Rename · Delete. The dataset menu is the same on all three tabs.
- Grid of widgets. Chat bar at the bottom per its setting.

As built, the context row is the dataset name, the "v7 · 6 steps" pill, the filter chip ("pclass = 3" with ×) when a filter is set, then Add widget, Edit layout, the job tray and the dataset menu. The pill isn't clickable, and there's no Filter button or filter builder. Not built yet (docs/BACKLOG.md). The selection chip is removed by cut 8 (Implementation Plan §2.0).

### 7.2 Widget anatomy and states

Header: drag handle · title · scope chip ("All rows" / "3rd class · 709") · analysis dropdown · menu (⋯).
Body: the chart or table.
Footer: version stamp ("v7") · "How do you know?" link · status (outdated / updating / error).

States: loading (skeleton) · ready · updating (dimmed with a thin progress line) · outdated (footer badge with "Re-run") · error (message in the body with "Retry" and "Show query").

Menu (⋯): Change view (list of compatible views) · Duplicate · Collapse · Pin number as KPI (P1, for single-value results) · Copy as image (P1) · Show as table · Delete.

As built, the menu is Change view · Duplicate · Collapse (Expand when collapsed) · Show as table (a check item) · Delete, with a toast "Widget deleted" and Undo for 10 s. Pin number as KPI and Copy as image (P1) aren't built. The scope chip reads "All rows" ("Some rows" or "Selection" for a scoped widget), plus " · pclass = 3" when the widget applies the dashboard filter; it hides on narrow widgets. The footer adds "Model card" on an analysis, "Outdated" with Re-run, and "first 2,000 rows" when a result is capped.

### 7.3 Interactions

| Action | Result |
|---|---|
| Hover a widget | Its story card highlights and scrolls into view in the right panel; related widgets get the spotlight. Suppressed during drag, resize and brush. |
| Click a bar / slice / heatmap cell | Sets the global filter (e.g. `pclass = 3`). Every widget with `inherit_global_filters` re-queries. The filter chip appears. Clicking the same element again, or the chip's ×, clears it. |
| Brush (drag inside a chart body) | Creates a row selection shown as a selection chip with the count. It's available to the analysis dropdown ("Rows: selection") and the chat ("selected rows"). Esc or the chip's × clears it. |
| Drag the handle (⠿) | Moves the widget (react-grid-layout). Layout saves on drop. |
| Drag the corner | Resizes. Charts re-measure. |
| Edit layout toggle | Adds resize corners and makes the whole header a drag handle on all widgets; off by default so brushing isn't accidentally a drag. |
| How do you know? | Opens a drawer: for SQL widgets, the SQL with a "Copy" button and the row count; for ML widgets, the recipe, scope, params and the model card. As built, the SQL includes the global filter only when the widget applies it, so a chart filtered on its own category shows its query without that clause (TRD §6.3). |
| Analysis dropdown | See §9. |
| Add widget | Opens a drawer with: "Describe it" (text to chat), and quick templates by column (bar of X by Y, histogram of X, KPI of X, table). |
| Delete | Removes the widget and its card; toast with Undo for 10 s. |

As built:
- **Hover.** Widget-to-card hover linking and the spotlight work as described in §7.4.
- **Focus.** Pressing on a widget makes it the chat's context.
- **Filtering.** A chart's click doesn't filter that chart (its clicked element is accented and the rest fade). Only bars, pie slices and ring slices filter, and only when the widget's category column is a column of the file. Lines and tables don't filter.
- **Brushing** is cut (cut 8).
- **Layout saving.** Moves and resizes save when the drag or resize ends. Collapsing a widget saves `collapsed: true` and keeps its height for when it expands.
- **Fewer than 3 widgets.** A dashed card above the grid gives the "I could only build n widgets" message. With none, the tab shows "No widgets yet" and Add widget.
- **Add widget.** The drawer has "Describe it" (a text box and Add) and "Quick templates": Bar of X by Y, KPI of X and Table. Adding one closes the drawer with a toast "Added “<title>”". The histogram template isn't there. Not built yet (docs/BACKLOG.md).

### 7.4 Story panel interactions

| Action | Result |
|---|---|
| Hover a card | Its widget gets the spotlight. |
| Click a card | Dashboard scrolls to its widget and flashes it. |
| Click a number chip | Opens the evidence drawer with the SQL or run behind it. |
| Related chip | Scrolls to and spotlights that widget. |
| Edit | The card becomes an inline editor (see §11). |
| Ask why | Expands the chat thread with "Why <headline>?" pre-filled and the card as context. |
| "Changed" badge | Tooltip "Updated after v8"; P1 shows what changed. Click dismisses. |
| "Outdated, click to refresh" | Triggers the card's update. |

---

As built:
- **Panel.** The overview card first ("Overview" overline, bullets), then a card per widget in builder order. While the stories job writes them, three placeholders and "Writing the stories…" show.
- **Hover.** Hovering a widget lights its card (accent border and spotlight) and scrolls it into view; widgets its card lists as related get the accent border at 45%. Hovering a card lights its widget. Hover linking is off in Edit layout.
- **Click.** Clicking a card (not a button or chip) scrolls the dashboard to its widget and flashes it for 1.2 s. A related chip spotlights its widget on hover and flashes it on click.
- **Evidence.** A chip opens "How do you know?": the value, what it is, the version, and the SQL (with Copy) or how it was derived. The footer's Evidence opens the card's first chip.
- **Badges.** "changed" (click to dismiss), "edited", "outdated, click to refresh".
- **Ask why** focuses the card's widget as the chat context and fills the bar with "Why <headline>?".

## 8. CSV tab

### 8.1 Layout

- Toolbar: Add row · Add column (P1) · Find · Filter · Clean with AI · Download (a menu: CSV · Notebook (.ipynb)) · and on the right the legend (changed / flagged / unsaved).
- Header line: dataset name, version, "n unsaved changes", **Discard**, **Save changes (n)**.
- The grid.
- Status bar (bottom of the grid): selection stats · row count · "Row 9, col home.dest".
- Right panel: **Changes**, or the cleaning plan while one is open (§8.4).
- While a job owns the data (the status is `cleaning` or `building`), the grid is read-only with a banner (§5), and Add row, Delete row and Restore are disabled.

As built (cut 5):
- **Toolbar.** Add row · Delete row (the rows of the selected cells) · Restore (shown when the selection includes quarantined rows) · Find · Clean with AI · Download (CSV · Notebook (.ipynb)) · the legend. Add column, the Filter row and quick views aren't there (P1 and cut 5).
- **Header.** "n unsaved changes", Discard and Save changes (n) sit in the context row on the right, before the job tray, when there are pending edits. Review changes is cut (cut 5); the Changes panel's "Unsaved (yours)" list removes single lines instead.
- **Column notes (PRD LOAD-7).** A column with a note (from a data dictionary the user linked) has ⓘ before its type line. Hovering its header shows the note: Sherlock's sentence, the source's own words in quotes, and "From the data dictionary at <site>, retrieved <date>. Not computed from your data." Hover only: the canvas header has no keyboard focus, so the same meaning is also answered in chat ("what does <column> mean?").
- **Grid.** A frozen first column shows `_row_id` ("new" for a pending row), struck through for quarantined rows and rows marked for deletion. New rows appear at the top until saved. A header click sorts by that column (ascending, descending, off); the status bar says the sort is a view only.
- **Status bar.** The number of selected cells, the row count (and sort), the unsaved count, and the current cell ("Row 9 · home.dest"). Selection stats are cut (cut 5).

### 8.2 Editing flow

1. The user edits cells, adds or deletes rows, pastes, fills, or uses find-and-replace. Each action creates **pending edits** (client-side buffer, mirrored to local storage keyed by dataset and version).
2. Pending cells show the "unsaved" style. The Save button shows the count. The Changes panel lists them under "Unsaved (yours)".
3. **Undo/redo** operate on the pending buffer.
4. **Review changes** (link next to Save) opens a drawer with one line per edit (row, column, old → new) and a per-line discard.
5. **Save changes** sends the batch. The server validates types (invalid values are saved but flagged), writes one step and a new version, and starts the cascade. The grid reloads the new version; a toast says "Saved as v8 · 12 changes" with Undo (which undoes the step).
6. If new rows were added, the toast also offers "Run cleaning on the 3 new rows".
7. **Discard** clears the buffer after confirmation.

Conflicts: if a background job commits a new version while edits are pending (e.g. "Clean with AI" started from chat), the Save button becomes "Rebase and save" and the edits are reapplied on the new version by `_row_id`; edits to cells that the job also changed are listed for the user to resolve (keep mine / keep theirs).

As built, double-click, Enter or typing edits a cell in place with a text editor; a value that doesn't fit the column's type gets the invalid underline and can be kept. Typing a cell's original value back removes that edit. Undo/redo of pending edits, block paste and fill down are cut (cut 5). The grid library's default keys still copy a selected range with Ctrl+C and paste the clipboard's text into one cell (PRD CSV-6). A save whose base is stale is resent automatically when no edited cell changed in between; otherwise a dialog lists each conflict (row, column, yours, theirs) with Mine or Theirs, then "Rebase and save". The save toast's Undo undoes the step; a second toast offers "Clean them" for new rows, which opens the cleaning plan in the right panel with "The n rows you just added" as its scope; nothing is cleaned until Start cleaning (PRD CLEAN-1).

### 8.3 Cell interactions

| Action | Result |
|---|---|
| Hover a changed (tinted) cell | Tooltip: `"C22 C26" → "C"` · "Step 3 · Extract deck from cabin" · "Undo step 3". |
| Hover a flagged cell | Tooltip with the flag reason ("zero fare: flagged for review"). |
| Hover a predicted cell | Tooltip: "Predicted by run r_12 · 78% survive · why?" |
| Double-click / Enter | Opens the type-aware editor. |
| Right-click a cell | Menu: Copy · Paste · Fill down · Clear · Ask about this cell · Clean this. |
| Right-click a row number | Insert above · Insert below · Duplicate · Delete · Restore (quarantined rows only; creates a step) · Ask about this row. |
| Right-click a column header | Sort asc/desc · Filter… · Auto-fit · (P1) Rename · Change type · Hide · Delete · Add computed column. |
| Select a range then type in chat | The chat context shows "n cells selected"; "clean this" or "standardize these" proposes "Clean n cells in <column>?"; Approve opens the cleaning plan in the right panel with those rows as its scope ("The n rows you asked to clean"), and the toast says "The cleaning plan is open for those rows. Look it over, then press Start cleaning." Nothing is cleaned until Start (PRD CLEAN-1). |

As built, the provenance tooltip, right-click menus and jump to row are cut (cut 5). Ctrl+arrow still jumps to the data's edge, and Shift+click, drag and Ctrl+A still select ranges, because they're the grid library's default keys (`Grid.tsx` sets none; PRD CSV-3, CSV-4); a step's changed cells are listed under the step in the Changes panel instead. **Find** (toolbar) searches every cell; the grid then shows only the matching rows, with the matching cells highlighted, until the find bar is closed (Esc or ×).

### 8.4 Clean with AI (any time)

Clicking opens the **cleaning plan** (§4.1) in the right panel in place of Changes, so the grid stays visible; a plan already open stays as it was. On a narrow window the right panel slides over. The side plan adds, above the modules:
- Scope: Whole dataset · Current selection (n rows; disabled with nothing selected) · Rows added since the last clean. A plan opened for some rows (the toast's "Clean them", chat's "clean these rows") adds a first radio for them, picked: "The n rows you just added" or "The n rows you asked to clean". The plan stores that scope, so it survives a reload; from the centre (the offer) the plan says "Only the n rows …" under its title and runs on them. With a selection or new-rows scope: "Counts are for the whole file; changes stay inside the rows in scope."
- With unsaved edits: "Save or discard your 12 unsaved changes first." with Discard edits, and Start is disabled.

Start cleaning starts the job and toasts "Cleaning started. Its steps appear in Changes as they commit."; the right panel goes back to Changes, which shows the running clean as below. Discard also gives the panel back to Changes.

The clean runs as a job with the same live log, shown in the right panel (Changes) so the grid stays visible. Hand-edited cells are skipped and listed in the report with "Include these next time" as an option (that option is not built yet: docs/BACKLOG.md).

As built, the plan's selection scope uses the rows of the selected cells (saved as a selection). While the job runs, the Changes panel shows a "Cleaning…" card with its progress and Stop; each committed step appears in Steps. A whole-dataset clean also sets the dataset to `cleaning`, so the Dashboard tab shows the live log.
- The Clean with AI button is disabled with its reason while the dataset is profiling, cleaning or building.
- The report lists hand-edited cells under "Cells you edited (left as they are)" with a count and an example. "Include these next time" isn't offered. Not built yet (docs/BACKLOG.md).

### 8.5 Changes panel

Sections, top to bottom:
- **Unsaved (yours)**: pending edits with a count, each line removable.
- **Steps**: newest first. Each: number, summary, affected columns and cell count, confidence/flag, **Undo**. Expanding shows the code (for cleaning steps) or the edit list (for edit batches), the impact report and the decision entries.
- Links: Full cleaning report · Export notebook (.ipynb) · Export pipeline as Python (P1).

Undo of a non-latest step: a confirmation explains "This undoes step 3 and replays the later steps still in effect (4–7) on top. 2 later steps touch the same column and will be re-run." If a replay fails, the undo is aborted and the reason shown. Undoing the automatic typing step (step 1) also asks first, even when it is the latest step: "Undoing typing turns every column back into text; charts and models that need numbers will stop working."

---

As built, steps that aren't in the current data are dimmed and struck through ("undone"); undo steps have no Undo. The undo confirmation names the steps to replay; undoing the typing step gives the typing warning (and the replay sentence too when later steps follow). A failed replay shows its reason in a toast and changes nothing. "Full cleaning report" opens the last report in a drawer.

## 9. ML from a widget

1. The user opens a widget's **analysis dropdown**. Options are grouped: Explain (What drives this?) · Predict (Predict a column) · Group (Find groups, P1) · Unusual (Find unusual rows, P1) · Time (Forecast, P1) · Plain chart (SQL). Incompatible options are disabled with the reason.
2. Choosing one flips the widget body into **setup**: Target (dropdown, pre-filled) · Features (chips; excluded ones crossed out with reasons on hover; click to toggle, with a warning when re-including an excluded one) · Rows (scope chip; "Use selection" if a brush selection exists) · Method (Auto · Linear regression · Logistic regression; incompatible ones disabled) · More (advanced params from the recipe manifest) · baselines preview for this scope · **Run** and **Cancel**.
3. **Run** starts a job. The widget shows plain-language progress ("checking for leakage → baselines → testing models → explaining"). The job tray (small icon in the header) lists it.
4. On completion the widget shows the result view with the verdict line, the chart, the view switcher, and a **Model card** link (drawer). Its story card updates.
5. Digging in: clicking a factor bar shows a partial-dependence mini chart; "Who did it get wrong?" opens the CSV tab filtered to those rows (`?rows=`); clicking a predicted cell shows its explanation.
6. If the data changes later, the footer shows "Outdated" with **Re-run** (or it re-runs automatically per the story-update setting).

"Compare with Auto" in the model card runs Auto with the same setup and shows both model cards side by side.

As built (within cuts 4 and 7):
- **Step 1.** The dropdown is a flask button in each widget's header. Its groups and options come from `GET /recipes`. Disabled options show their reason under the label: Predict "Not in this release", Find groups and Find unusual rows "Coming later", Forecast "needs a date column" on Titanic. "Plain chart (SQL)" is checked on a chart. On an analysis it goes back to the chart the analysis replaced (widget Undo), with its title. An analysis the builder made has no chart, so that says so.
- **Step 2.** "What drives this?" flips the body into the setup.
  - The target is pre-filled with the analysis's own target, else the chart's measure or category when it can be explained, else the best guess.
  - The feature chips come from the preview. Re-including a struck-through column shows a warning line, and the model card keeps a warning.
  - The rows chip shows the widget's rows and the count with the target. With a dashboard filter active, "Only the filtered rows" (on by default) runs on those rows (cut 8: ML scope comes from a filter or the whole dataset).
  - Method shows Auto alone with what it tries (cut 4). More holds Folds and Time budget.
  - The baselines come from the preview, with "Model: pending" (or "already run" when the same request is cached), and the estimate is "about N s".
  - Run turns the widget into the analysis, titled "What drives <target>?".
- **Step 3.** The widget shows "What drives <target>: <label>…", a progress bar and the steps ticked off, with Cancel. The job tray lists the `ml_run` job.
- **Step 4.** The widget shows the verdict line ("Beats the best simple rule by 2.4 points. Gradient boosting: Accuracy 80.4% vs 78.0%."), then the importance bars, with the top factor in the accent. The footer has "Model card" (the drawer) and "How do you know?" (the run's reproduction code). Its story card is narrated from the run's fact sheet when the run finishes. On a fresh dashboard the builder's "What drives <target>?" widget does the same by itself.
- **Step 5.** Clicking a factor bar opens its partial-dependence mini chart (the probability or prediction as the factor varies) under the bar. For categories the widget has a view switcher (Importance · Confusion · ROC, the last for two classes), and the model card shows the confusion matrix and the ROC curve.
  - **"Who did it get wrong?"** is in the model card with the count. It saves a selection of the rows the out-of-fold predictions got wrong and opens the CSV tab on `?rows=<selection_id>` ("256 rows selected" on Titanic), with a toast.
  - Predicted cells stay cut (cut 7).
- **Step 6.** After a new version that changes its columns, the footer shows "Outdated" with **Re-run** under "Story updates: Ask first". Under "Automatic" it re-runs by itself and shows the progress again. Story updates isn't in the Settings dialog (cut 1), so it stays at its default, Automatic, unless set through `PUT /me/settings`.
- **Compare with Auto** is not built (cut 4: Auto is the only method). A failed or cancelled run says why, with Re-run.

---

## 10. Chat (ask anything)

### 10.1 The bar and thread

- Collapsed: a single input with the placeholder "Ask Sherlock, or tell it what to build…", a `/` hint, and a send button. Under it, three **suggested questions** as chips.
- Focus or typing expands the thread above the input (max 40% of the centre height), showing the dataset's conversation. Esc collapses it.
- A **context chip** on the left of the input shows what the next message applies to: "All rows", "Selection: 709 rows", "3 cards selected", "Cell B12", or the widget name when a widget is focused. Clicking it clears the context.

As built, the suggested-question chips are removed by cut 9 (Implementation Plan §2.0); an empty thread shows one hint line instead. The thread's header reads "Ask about <file name>" with a close button. The context chip reads "All rows"; on the Dashboard, the filter ("pclass = 3") or else the focused widget's title, with × to clear it; on the CSV tab "3 rows selected"; on the Flow tab "3 cards selected" or "Whole canvas". The brush selection chip is cut (cut 8).

The answerers behind the bar:
- **"Is fare significantly different between men and women?"** answers with the test chosen by the column types (Welch's t-test and Mann-Whitney here), the p-value, the effect size and n as chips, a plain verdict, and the test and group tables.
- **"What drives survival?"** answers from the analysis (the dashboard's, from the cache, or a new one waited for up to a minute): the verdict, the metric against the best simple rule, the strongest factors, the importance table and a **Model card** button that opens the drawer.
- **"How accurate is the model?"**, **"why was boat left out?"** answer from the model card. **"Who did the model get wrong?"** answers with the count, the first rows and "Open these rows in CSV".
- **"What does sibsp mean?"** answers with what the data says (counts, range and common values), then a dashed box "In general (not from your data): …" from the model's general knowledge.
- **"How do I undo a step?"** answers from the help pages (`docs/help`), naming the page in How do you know?.
- **Tabs.** Each tab offers its own tools. On the CSV tab "add a chart … to the dashboard" answers with a chart and Pin instead of adding a widget, and the Dashboard tab adds it.

### 10.2 Message lifecycle

1. The user sends a message.
2. A reply bubble appears immediately with "Thinking…" then a one-line status as the agent works ("Running a query", "Starting driver analysis"). For multi-step plans, the plan appears as a checklist that ticks off.
3. The answer renders in its shape:
   - **Number**: large value with its source link.
   - **Table**: up to 20 rows inline, "Open all 143 rows in CSV" link.
   - **Chart**: a Bklit chart with **Pin to dashboard**.
   - **Text**: markdown with number chips; **Add to Flow** when it's a narrative answer.
   - **Proposal**: a card with Approve / Reject for data changes or step-by-step cleaning.
   - **Clarification**: the question and 2–3 buttons; the thread waits.
4. Every answer has a **How do you know?** disclosure (SQL, recipe run, step references) and a copy button.
   - Inside it, **How I worked it out** (collapsed) lists the model calls that made the answer, in order: what each step did ("Read the question", "Wrote the query", "Wrote the answer"), the model that ran it, its time and its tokens, a repair call marked "(repair)", a failed attempt "(failed)", and a call Ultra answered because Super was failing or out of time "(in place of the medium model)" (TRD §3.5), then the total ("Total: 3 calls · 4.1 s waiting on them · 5,120 tokens"). A web request, once the web client logs them, shows as "Searched the web" with "cached" when the web cache answered it. Every Sherlock message has the disclosure, so a clarification or a failed answer shows the calls it made too (TRD §4.9 receipts).
5. Follow-ups reuse the saved focus (scope, columns, result ids).

As built:
- The thread opens on focus or typing, and `/` (when nothing editable has focus) focuses the bar. Esc closes it.
- Step 2's status lines come from the stream ("Thinking…", "Running a query", "Writing the answer"). The first table appears as soon as its query has run, and the final message replaces what streamed.
- A clarification shows its options as buttons, which work on the latest message only.
- Row answers link to the CSV tab with `?rows=<selection>`. The interim table there shows a "n rows selected" chip and "Show all rows".
- A plan shows as a checklist above the answer (○ waiting, ◌ running, ✓ done, × failed) and stays on the saved message.
- On the CSV tab, selected cells are the context: the chip reads "3 rows selected". "Set this age to 1" or "make these empty" answers "Nothing has changed yet. Approve to apply this, or reject it." with a dashed proposal card listing each cell (row, column, now struck through, after). **Approve** saves it as a new version ("Saved as v3. Undo it from the Changes panel."), and the card then reads Approved. **Reject** reads Rejected. A proposal whose data moved on reads "Expired: the data changed since". "Clean these rows" proposes Clean with AI on the selected rows; approving opens the cleaning plan for them (above).
- On the Dashboard, with a widget clicked (the context chip names it), "make it a pie chart" changes that widget at once, shows it, and offers **Undo**. The widget on the dashboard redraws from its new query at once, not with the old query's rows, and Undo puts it back the way the widget's own undo does.
- "Export a notebook without the data" opens the export dialog with Include data off, and the answer keeps an **Export notebook** button.

Failure modes: "I couldn't turn that into a query. Try naming the columns, e.g. “the average <measure> by <group>”." (the example uses the file's own columns) · "There's no column for <what was asked>. The closest is <a column>; want that?" (button) · "That needs about 100 rows and this selection has 41."

As built, a question no column answers gets "This file has no column that answers that. The closest I can answer: “…”" as text, with no button. Not built yet (docs/BACKLOG.md). A query that still fails after its repair gets "I couldn't build a working query for that. Try naming the columns, e.g. “…”", with an example in the file's own columns (a measure or an outcome by a small category, `agent/loop.py::example_question`), or no example when the file has none. An analysis with too few rows says "This needs at least N rows with <target> filled in; …". If the router still picks an action that lives on another tab, the answer says where ("Adding a widget works from the Dashboard tab; ask there, or use Add widget.").

Quality of life as built (the `?` sheet is cut 9):
- **Toasts with Undo (10 s)** after deleting a widget, a dataset, a story card (the trash button on each card) or nodes on the canvas. Deleted rows are pending until Save, and a saved step has Undo in the Changes panel.
- **Remember where I was**, per dataset in this browser: the last tab (server-side), the dashboard's scroll position (restored once its widgets are tall enough), the canvas's pan and zoom, and unsaved CSV edits.
- **Empty states** say what goes there and offer one action: the library ("Drop a CSV anywhere", Try with sample), the dashboard ("No widgets yet", Add widget), the stories panel, the palette, the canvas.
- **Error boundaries** around the page, each tab's content, the library and the side panel: a crash shows "Something went wrong showing the …" with Try again and Reload, and the rest keeps working.
- **Offline banner** when the network or the server is unreachable; it clears itself.

### 10.3 Chat on each tab

| Tab | Context | Typical actions |
|---|---|---|
| Dashboard | global filter, brush selection, focused widget | questions, create/edit widgets, run analyses |
| CSV | selected cells/rows/columns | questions about cells, "clean this", "standardize these", (P1) computed columns |
| Flow | selected nodes or whole canvas | "make sense of this", "take it toward X", "rewrite this card", "what's missing?" (P1) |
| Any | — | "export a notebook" / "give me this as a Jupyter notebook" opens the Export notebook dialog (§17) with the options pre-filled from the request ("without the stories" unticks Include story cards) |
| Any, while a cleaning plan is open (PRD CLEAN-8b) | the open plan (`plan_id`) | "don't touch outliers", "leave cabin alone", "also trim spaces in name", "fill age by class instead": the plan changes at once (§4.1), and the reply says what changed. Without an open plan the same words answer "Changing a cleaning plan from chat works while the plan is open; press Clean with AI to open one." |

---

## 11. Editing a story card

1. Click **Edit** (or double-click the card on the canvas). The card becomes an inline editor with the headline and body editable.
2. Number chips are atomic: they can be deleted or moved, not edited character by character. Typing `/` opens a picker of this card's fact-sheet values to insert a new chip.
3. Typing a number by hand creates an "unverified" chip (dashed outline) with a tooltip "Typed by you, not computed".
4. **Save** or **Cancel**. Saving marks the card as user-edited (an "edited" pencil badge).
5. Later data changes: chips update in place; the card gets a "data changed" badge with **See suggestion** (opens a side-by-side: your text vs the AI's revision, with Accept / Keep mine).

As built, Edit turns the card into two TipTap editors, Headline (one line) and Body. Chips and labels are atoms that move as a whole. `/` opens a picker of the card's facts (filter by typing, Enter or click inserts the chip, Esc closes). Save sends the card; the server marks typed numbers unverified (dashed chip, "Typed by you, not computed"). When the data changes, an edited card keeps its text and shows "The data changed. Suggested revision:" with Accept, Edit (opens the suggestion in the editor) and Dismiss.

The editors hold only what a card can store: paragraphs and bullets in the body, one paragraph in the headline, and text, chips and labels. Numbered lists, line breaks, bold, italic, strike, code, underline and links aren't offered.

---

## 12. Flow tab

### 12.1 Layout

- Header: dataset name, "Story canvas · 6 cards · 3 selected", **Add note**, **Connect**, **Fit view**.
- The canvas (dot grid), zoom buttons bottom-left, minimap bottom-right.
- Right panel: the **palette**: search, then every story card as a draggable row (placed ones marked), then "Try asking" suggestions, then Export: Notebook (.ipynb) and (P1) Obsidian (.canvas).
- The chat bar with the context chip ("3 cards selected" / "Whole canvas").

### 12.2 Interactions

| Action | Result |
|---|---|
| Drag a palette row onto the canvas | Places that card as a node at the drop point. The palette row becomes "on canvas". |
| Drag a node | Moves it; saved on drop. |
| Click a node | Selects it (shift-click adds). Selection is the chat context. |
| Double-click a card node | Inline edit (§11). |
| Connect mode, then click A then B | Creates an edge; a small label input appears at the midpoint; Enter saves, Esc leaves it unlabeled. |
| Click an edge | Selects it; Delete removes it; double-click edits the label. |
| Add note | Places a note node at the viewport centre in edit mode. |
| Delete key with nodes selected | Removes nodes (cards stay in the panel; notes are deleted). Toast with Undo. |
| "Open widget" on a card node | Navigates to `?widget=:id` on the Dashboard tab. |
| Scroll / pinch | Zoom; drag the background to pan. |

### 12.3 AI actions on the canvas

| Request | What happens |
|---|---|
| "Make sense of this" (needs ≥ 2 selected cards) | A **synthesis** card appears at the centroid of the selection, with edges labeled "summarized in" from each source. Its chips come from the sources' fact sheets. It carries "Cites n cards". |
| "Take the story toward X" | The chat shows a plan ("Build: survival by age band"). A **direction** card appears immediately in a "building" state (checklist: widget query → fact sheet → story → verify), connected to the selection with the label "next: X". When done, it becomes a normal widget card. The widget also appears on the dashboard. If a stage fails, the card shows that stage with the error and Retry. |
| "Rewrite this card" (1 selected) | A proposal in the chat with the new text (chips only, verified like a story card); Accept replaces the card text (the card then counts as user-edited, so later data changes produce suggestions instead of overwrites); Reject discards. |
| "Argue against this" (P1) | Adds cards for widgets that weaken the claim, connected with "contrasts with". |
| "Order this into a story" (P1) | Proposes a numbered path; Accept numbers the nodes and enables Present mode. |

Failures: "Select at least two cards to make sense of them." · "I couldn't find a column about X. The closest are: age, fare." (buttons).

As built (cuts 2 and 3 applied: no "take the story toward X", no direction cards, no "Rewrite this card"):
- **Header.** **Add note**, **Connect** (pressed while on) and **Fit view** sit with the job tray and the ⋯ menu. "Story canvas · 6 nodes · 3 selected" sits at the canvas's top left instead, with **Make sense of this** beside it whenever two or more cards are selected, so the header row never changes width as the selection does.
- **Palette rows** can also be placed from the keyboard: Enter or Space on a focused row (or a double-click) puts the card in the middle of the view, below any card already there. A row's accessible name is the card's title and "on canvas" or "not placed". Synthesis and answer cards are listed by their headline. The "Try asking" lines fill the chat bar.
- **Selecting.** Click selects; Shift-, Ctrl- or Cmd-click adds to the selection. There is no box selection (Shift is the add key). The chat chip reads "3 cards selected", or "Whole canvas" with none.
  - From the keyboard: Tab reaches each node (and the chips and "Open widget" inside it), Enter selects the focused node, and holding Shift, Ctrl or Cmd while pressing Enter adds it to the selection (React Flow's own keyboard selection). The flow test selects its second card this way. Then `/` and "Make sense of this" in the chat bar.
- **Connect mode.** A hint at the top reads "Click the first node, then the second". The second click makes the edge, opens its label input, and turns connect mode off. Dragging from a node's side handle to another node also connects them.
- **Notes.** A new note opens in edit mode. Ctrl+Enter or clicking away saves it, and Esc cancels. A new note left empty is removed and never saved. Double-clicking a note edits it again.
- **Card nodes** show the overline (the widget's title, "Overview", or "Synthesis" in the accent colour), the headline and the body with live chips; a chip opens the evidence drawer. They also show "Cites n cards" on a synthesis, "Open widget" on a widget card, and the badges: changed, edited, outdated, and "sources changed" (click to write it again). Double-clicking a card edits it in place with the card editor, the same object as in the stories panel.
- **Delete** (or Backspace) removes the selected nodes or edges with a toast "Removed 2 items from the canvas" and Undo for 10 s. Cards stay in the palette.
- **Saving.** Every change saves within a second. When another tab or the AI changed the canvas meanwhile, this tab's changes are merged onto the newer copy and saved again; nothing is lost. A synthesis from chat appears without a reload.
- **Remember where I was.** The pan and zoom are kept per dataset in this browser. A canvas opened for the first time with nodes fits them in view; an empty one opens at 100%.
- **Empty canvas.** "The canvas is empty", then how to add cards and notes, and that two selected cards can be made sense of.
- **Chat.** "Make sense of this" with two or more cards selected writes a synthesis card and places it right of them with "summarized in" edges. Any other question about the cards is answered from them, with **Add to Flow**. Add to Flow on any answer's text (any tab) makes an "Answer" card on the canvas with its numbers and their evidence.

---

## 13. Settings overlay

Opened from the gear or `?settings=1`. A centred dialog over a dimmed app. Contents per PRD §7.10 as segmented controls. Changes apply immediately and save to the server; "Done" closes. Esc or clicking outside closes. The mode and accent switches preview live behind the dialog. As built (cut 1): mode, accent, chat bar and after upload (UI/UX brief §5.11).

After upload reads "Ask me · Open the cleaning plan · I'll clean it myself" (the stored values are `ask|always|never`), with the help "What happens once a new CSV is profiled. Nothing is cleaned until you start a plan." `?settings=1&field=after_upload` opens the dialog scrolled to that field and outlines it: the "Change" links on the plan and building screens use it (§4).

---

## 14. Left panel (library) interactions

| Action | Result |
|---|---|
| Click a row | Opens that dataset on its last tab. |
| Row menu (⋯) | Rename (inline) · Delete (confirm, then toast with Undo) · Download original CSV. |
| Status badge | profiling / offer / cleaning n% / building / ready / failed. Hover shows the last event. |
| Collapse (« / ») | Panel becomes an icon rail: dataset initials as buttons, Upload, Sample, gear. |
| Upload / Try with sample | §3. |

As built, the panel's buttons read "Upload CSV" and "Try with sample", and an empty list says "No CSVs yet." The row menu is Rename · Download original CSV · Delete. The status line reads "ready · v7" when ready and "offer · 7 issues" at the offer; cleaning and building show a thin progress bar under the word.

---

## 15. Background jobs tray

A small icon in the centre header shows the number of running jobs. Clicking lists them (cleaning, dashboard build, story updates, ML runs) with progress and **Cancel**. Completed jobs show for 1 minute. Errors stay until dismissed, with "Retry".

As built, the tray lists the jobs of all your CSVs, each with its CSV's name. Dismissing a failed job only hides it in this tab.

---

## 16. The update cascade, as the user sees it

Trigger: a save in the CSV tab, a cleaning step commit, a widget added/changed/removed, an ML result.

1. A thin progress line appears under the header: "Updating 4 widgets and 3 stories".
2. Affected widgets dim and show "updating"; others are untouched.
3. Affected ML widgets show "Outdated · Re-run" (or re-run automatically).
4. Story cards update one by one; each gets the "changed" badge (or "outdated, click to refresh" in Ask-first mode).
5. The progress line disappears. A toast summarizes: "v8: 4 widgets re-queried, 3 stories updated."

The cascade is debounced: multiple saves within 2 seconds produce one cascade.

As built, the progress line reads "Updating 4 widgets and 4 stories". Only widgets that read a changed column dim; their cards show a spinner while they're rewritten, then the "changed" badge. The toast reads "v3: 4 widgets re-queried, 4 stories updated." 

Also as built (TRD §7.6):
- A second save while a cascade runs queues the next cascade behind it; the two never run at once, so the cards end on the newer version.
- A cascade that fails or is cancelled leaves no card spinning: the cards it hadn't finished show "outdated, click to refresh", and the next cascade rewrites them.
- An analysis card shows the spinner while its run re-runs, and "outdated, click to refresh" if the run fails.
- A widget changed while the cascade runs keeps the change.

---

## 17. Notebook export

Available from every tab in every status except `profiling` and `failed`.

### 17.1 Entry points

| Entry | Where |
|---|---|
| Dataset menu (⋯) → Export notebook | Header, all tabs |
| Download → Notebook (.ipynb) | CSV toolbar |
| Changes panel → Export notebook | CSV tab, right panel |
| Palette → Export → Notebook | Flow tab, right panel |
| Chat: "export a notebook" | Any tab; options pre-filled from the wording |
| Keyboard: Ctrl+Shift+E | Any tab |
| `?export=notebook` | Deep link |

As built: the dataset menu (⋯, with the shortcut shown, disabled with its reason while profiling or failed), the CSV Download menu, the Changes panel link, Ctrl+Shift+E and `?export=notebook`. The Flow palette's Export → Notebook (.ipynb) opens the dialog, and so does chat's "export a notebook" (§10.2), with the options it asked for.

### 17.2 The dialog

Title "Export notebook". Body:
- One line: "A runnable Jupyter notebook that rebuilds **titanic3.csv v7** from the raw file: 6 steps, 8 widgets, 2 model runs, 9 story cards."
- Options (checkboxes, remembered per user): **Include data** (raw CSV next to the notebook; default on) · **Include story cards** (on) · **Include canvas notes** (off) · **Include ML runs** (on).
- Order (segmented): **Steps, then dashboard order** (default) · **Flow reading path** (P1; disabled with "Order the canvas first" until a path exists).
- A note when a cleaning or ML job is running: "A job is still running. This export uses v7, the latest committed version."
- A note when pending edits exist: "You have 12 unsaved edits. They are not included; save first to include them." with a **Save and export** button.
- Footer: Cancel · **Export** (primary).

The notes box also shows the preview's own notes (TRD §4.2), for example "There are no story cards yet, so this notebook has the widgets only." The preview's running-job note is left out there, because the dialog says that itself in the words above.

### 17.3 Flow

1. Export → the dialog closes; a toast "Preparing notebook…" with a progress bar (job in the tray).
2. On completion the browser downloads `titanic3-v7.ipynb` and, if ticked, `titanic3-raw.csv` (two downloads; on browsers that block the second, the toast offers a link). The toast becomes "Notebook ready" with **Download again** for 1 minute.
3. A repeat export with nothing changed (same version, same dataset state, same options) downloads instantly from the cache.

As built, the toast is a loading toast that becomes "Notebook ready" with Download again for 1 minute. The notebook downloads from `/exports/{id}/download`; with Include data the raw CSV follows 0.4 s later from `raw.csv`. The dialog's unsaved-edits note doesn't have the Save and export button yet: it asks the user to save first.

### 17.4 What's in the file, in order

1. Title and provenance (Markdown): dataset name, version, export time, Sherlock version, "every number below was computed by code".
2. Parameters (code): `DATA_PATH = "titanic3-raw.csv"`, `RANDOM_SEED = 42`.
3. Requirements (code, pinned `pip install` line). Its comment says `%pip` needs pip in the kernel's environment: make a uv venv with `uv venv --seed`, or install the pins with `uv pip install` and skip the cell.
4. Helpers (code): the vendored cleaning helpers used by any step in this notebook (only those).
5. Load (code): decode the raw file with the recorded encoding into a UTF-8 copy in the working directory, then DuckDB's `read_csv` with the recorded delimiter, header and skip options and `all_varchar`, the same reader, `_row_id` expression and empty `_quarantine_reason` column the app uses, then `.df()`.
6. Overview (Markdown): the overview card.
7. For each step in the current version's effective chain (undone steps left out), in order: a Markdown cell (step number, summary, gate, decision, impact line) and a code cell (the stored pandas for cleaning steps, or the stored DuckDB statement for the typing step, ending in `df = result`; generated pandas assignments by `_row_id` for edit batches). An undo appears only as a Markdown note. A final assertion cell checks row count and columns against the version.
8. For each widget in dashboard order: Markdown (title), code (DuckDB SQL on the DataFrame → table, output embedded), code (matplotlib chart), then its story card as Markdown. ML widgets get their run's reproduction cell and its importance or coefficients table instead of the SQL and chart cells.
9. For each ML run: Markdown (what and why, excluded columns with reasons), code (reproduction), output tables embedded; its story card.
10. Synthesis and direction cards after their sources; canvas notes where they sit in the Flow path (when that order is chosen).
   As built, synthesis and answer cards come in a section "From the Flow canvas" after the dashboard, oldest first, each with its numbers and evidence like any card. With **Include canvas notes**, the canvas's notes follow as quoted Markdown in reading order (top to bottom, then left to right).
11. Closing cell: "How to continue" (how to add cells, where the helpers are documented, a link back to Sherlock).

### 17.5 Edge cases

| Situation | Behaviour |
|---|---|
| Dataset is `profiling` or `failed` | The menu item is disabled with the reason. |
| Export job fails (e.g. a step's code can't be re-rendered) | Toast with the error and "Export up to step k": the notebook stops before the failing step, asserts against that earlier version, and says so in its first cell. |
| Widget SQL uses a global filter | Not applied; a comment in the cell says so. |
| ML run is `outdated` | Included with a Markdown note "computed on v6; re-run reproduces it on v7". |
| Card edited by the user | Exported with the user's text; unverified numbers get a `*` and a footnote. |
| No story cards yet (export during the build) | The notebook says so and includes widgets only. |
| 50 MB file with "Include data" | The raw CSV download is the original file; the notebook's load cell reads it the same way. Export time ≤ 60 s. |

---

## 18. Error and edge-case catalogue

| Situation | Behaviour |
|---|---|
| Token Factory unavailable | Jobs that need the LLM pause with "Waiting for the model…" and retry with backoff for at most 2 minutes (time that counts against the cleaning budget), then fail with "The model service is unavailable. Your data is safe; try again in a minute." Chat shows the same message. Non-LLM features (grid, SQL widgets, filters) keep working. |
| The app-wide daily model budget is used up | Model features answer "Sherlock has used today's model budget for everyone. It resets at midnight UTC." (chat as a text answer, cleaning and stories as their budget-exceeded paths). Uploads, the grid, edits, widgets and exports keep working (PRD §9, TRD §3.5). |
| Too many new visitors from one network | A first visit past 300 new users an hour from one IP gets `429` with "Too many new visitors from your network. Try again in N minutes." Anyone who already has a cookie is unaffected (TRD §15). The web app shows it as a whole page, not the shell: "Sherlock can't open a new workspace yet", the server's message, "A browser that has opened Sherlock before isn't affected." and Try again. Any other failure of that first request shows "Sherlock couldn't start" with the error and Try again. |
| Rows with different numbers of fields | The file imports with its real columns. Short rows are padded with empty cells. A row with extra fields keeps them in `col_N` columns and is quarantined ("extra fields…"), shown in the CSV tab's flagged view, and can be restored (PRD LOAD-3a). As built: the flagged view (a quick view) is removed by cut 5 (Implementation Plan §2.0); the row shows in the grid with its row number struck through, and Restore brings it back. |
| LLM returns invalid JSON | One repair retry; then the pipeline step is skipped (cleaning) or the answer falls back to the raw results table (chat). Logged. |
| SQL from the model fails | One repair retry with the error; then "I couldn't build a working query for that." |
| Sandbox timeout (30 s) | The candidate fix is discarded; the issue is skipped with "took too long". |
| Browser offline | A banner "You're offline. Edits are kept locally." Pending edits persist in local storage; Save retries when back online. As built: the banner reads "Can't reach Sherlock. Your data is safe, and unsaved CSV edits stay in this browser; this clears when the connection is back." It also shows when an API call can't reach the server, and clears once `/healthz` answers (checked every 5 s). Save doesn't retry by itself; pressing it again after the banner clears saves. Not built yet (docs/BACKLOG.md). |
| Session cookie cleared | The library appears empty. There is no recovery (documented in the README and the empty state's small print: "No sign-up: your CSVs stay with this browser. Clearing its cookies, or another browser, starts an empty library."). |
| Dataset expired (7 days) | Removed from the library; opening a stale link shows "This CSV expired." As built: a stale link opens the library with the toast "That CSV is no longer available.", the same as for a deleted CSV (§2). |
| Two tabs open on the same dataset | Both receive cascade events (SSE); pending edits are per tab; a save in one tab makes the other show "A new version exists. Reload to see it." As built: the other tab follows the new version by itself through its event stream (version pill, grid, Changes panel and dashboard refresh), so there's no reload message; its own pending edits then save through "Rebase and save" (§8.2). |
| Wide file (> 30 columns) | Auto-dashboard uses the 30 most interesting columns; a note says so. The grid shows all. As built: the builder keeps the 30 most informative columns (with the target, time and first ID columns), but no note says so in the app. Not built yet (docs/BACKLOG.md). |
| No numeric columns | Dashboard shows counts and top-value charts; ML options are disabled with reasons. |
| Tiny file (< 100 rows) | Dashboard builds; supervised ML refuses with the row count needed; stories mention the small sample. |
| All-text file | Profiling detects free-text columns; the dashboard shows top values and lengths; chat can search text. |
| Column with no values | Profiling types it `empty`; it stays in the data, is flagged in the data card, and is left out of widgets, targets and features. |
| Page reloaded while a chat answer streams | The server finishes the answer and saves it; after the reload the thread shows the completed reply. |
| Header not on the first row | The import preview's header-row control fixes it; auto-detection tries the first 5 rows. |
