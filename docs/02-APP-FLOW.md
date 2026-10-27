# Sherlock · App Flow

Version 1.0 · 2026-10-19 · Every screen, state, transition and edge case, as the user sees them. Read with the [PRD](01-PRD.md) for requirement IDs, the [UI/UX Brief](03-UIUX-BRIEF.md) for how things look, and the [TRD](04-TRD.md) for the API and pipelines behind each screen. "Cut N" refers to the cut order in Implementation Plan §5; all nine cuts apply (§2.0).

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

Routes (client-side, `web/src/App.tsx`):

| Route | Screen |
|---|---|
| `/` | Library; redirects to the last opened dataset if one exists. The "Sherlock" wordmark links here and stays on the library. |
| `/d/:datasetId` | Redirects to the dataset's last tab (or the default-tab setting, else Dashboard) |
| `/d/:datasetId/csv` | CSV tab |
| `/d/:datasetId/dashboard` | Dashboard tab (an unknown tab name shows this too) |
| `/d/:datasetId/flow` | Flow tab |
| `?settings=1` | Settings overlay on top of any route; `&field=after_upload` scrolls to that field and outlines it |
| `?widget=:id` | Dashboard tab with that widget highlighted and scrolled into view |
| `?rows=:selectionId` | CSV tab filtered to a saved row selection (used by "open these rows") |
| `?export=notebook` | The Export notebook dialog on top of any dataset route |
| anything else | The library |

`?widget=:id` acts like clicking a card: once the widgets load, the dashboard scrolls to the widget, flashes it, then drops the parameter so a reload doesn't flash it again. An ID no longer on the dashboard just opens the dashboard. Chat's "Open the widget" uses it.

The left panel and the chat bar exist on every dataset route.

---

## 2. First visit and the library

**State: no datasets.**
- Left panel: the "Sherlock" wordmark, the gear, the collapse button («), "Your CSVs" with "No CSVs yet.", then **Upload CSV** and **Try with sample**.
- Centre: the **empty state**. A large drop zone reads "Drop a CSV anywhere", then "or", **Upload**, **Try with sample (Titanic)**, ".csv, .tsv or .txt · up to 50 MB", and the small print "No sign-up: your CSVs stay with this browser. Clearing its cookies, or another browser, starts an empty library." Under it, one sentence: "Sherlock cleans it, charts it, models it, and tells you what it means. Every number shows its source."
- Right panel: "Stories" with three placeholder card outlines and "Stories appear once the dashboard is built."
- The chat bar sits under the pitch, disabled, with the placeholder "Load a CSV to start asking".

**Identity.** There is no login. The app first calls `GET /me`, which creates the user and sets the `sherlock_uid` cookie; nothing else loads until it answers (TRD §3.1, §4.1). Everything the user does is keyed to that cookie. If that first call fails, see §18.

**Returning visit.** `/` redirects to the last opened dataset. If it was deleted or expired, the library shows with a toast: "That CSV is no longer available."

---

## 3. Loading a CSV

### 3.1 Entry points

| Entry | Behaviour |
|---|---|
| **Drag anywhere** | When a file is dragged over the window, a full-window overlay appears: dashed border, "Drop to import". It takes one file. With several, the first is imported and a toast says "Imported the first file; drop the others one at a time." |
| **Upload button** | OS file picker for `.csv, .tsv, .txt`. |
| **Try with sample** | Loads the bundled Titanic file as "titanic3.csv (sample)". If the user already has the sample, it opens that one instead of making a duplicate. |
| **Paste (P1)** | Pasting tabular text into the empty state or the library creates a dataset from it. Not built yet. |

When the image ships the cached seed (TRD §4.2), Try with sample opens a copy that is already **ready**: its cleaning steps, dashboard, story cards, analysis and a synthesis on the canvas, as the real model made them. There's no import preview, profiling or offer for it. Without the seed, the file goes through §3.2–§6 live.

### 3.2 Import preview (modal)

Shown as soon as a file is chosen. The preview is parsed in the browser from the first 256 KB of the file; nothing uploads until Import.

Contents:
- Title: "Import <file name> · <size>".
- **Delimiter**: Comma, Tab, Semicolon, Pipe, auto-detected. "Other (…)" is listed only when the detected delimiter is none of those. There's no field to type another delimiter. Not built yet.
- **Encoding**: UTF-8, UTF-8 with BOM, Latin-1, Windows-1252, UTF-16. Detected from a byte-order mark, else UTF-8 if the bytes are valid UTF-8, else Windows-1252.
- **Header row**: a number (0–100), starting at 1; 0 means no header, and columns get `col_1…`.
- **Skip rows** before the header: a number (0–1000), starting at 0.
- **Data dictionary URL (optional)** (PRD LOAD-7): the address of a page that describes the columns, such as a codebook.
- A preview table of the first 20 rows as currently parsed.
- The footer line "Detected 14 columns · about 1,309 rows", any notes under it, or the reason Import is blocked ("Reading the file…" until the sample is read). Then **Cancel** and **Import**.

The preview doesn't detect the header row or skip rows itself; the server's sniffer does when the user leaves them alone (TRD §7.1). PRD LOAD-2's header-row detection in the preview is not built yet.

Rules:
- Changing any control re-parses the preview at once (Papa Parse, in the browser).
- Import is disabled, with the reason in the footer, while nothing parses. A zero-byte file, a header-only file, or one with nothing left after Skip rows shows "This file has no data rows." The server applies the same rule and creates no dataset.
- Repeated column names get suffixes (`name`, `name_2`) and the note "Some column names repeat, so the later ones get a suffix (name_2)."
- Files over 50 MB are refused before upload: "This file is 73 MB. The limit is 50 MB."
- Files that look binary (NUL bytes in the first 64 KB, outside UTF-16) show "Couldn't read this as text. Is it a spreadsheet or a zip? Export it as CSV first."

**Import.** The raw file uploads (the Import button shows a spinner), the dataset is created, and the app opens `/d/:id`, which lands on the default tab in the **profiling** state. A progress bar for uploads over 2 MB is not built yet. Only the settings the user changed from what the preview detected are sent; the server detects the rest. Server-side refusals show as an error toast (§18).

**The data dictionary (PRD LOAD-7).** With a URL in the field, Sherlock reads that page once the upload is accepted (TRD §7.1.1), while the file profiles; the dialog doesn't wait. When it's done, a toast says "Read the data dictionary: notes on 3 columns.", or gives the one line saying why it wasn't read ("Web search isn't set up on this server, so I didn't look this up on the web.", "I couldn't find column descriptions on that page.", …). It never holds up or fails the import. The notes show in the CSV tab's column headers (§8.1).

**Until the dataset is ready**, the centre of every tab route shows the profiling, offer, plan, cleaning, building or failed screen. The exception is the CSV tab: once the dataset has left profiling it shows the grid (read-only, with a banner, while cleaning or building; §5, §8.1). Dashboard and Flow are disabled until then, with the tooltip "Available after cleaning" during cleaning and "Available once the dataset is ready" otherwise.

### 3.3 Profiling state

- Centre: a spinner and one line that follows the profile job: "Reading titanic3.csv…", then "Typing 14 columns…", then "Profiling 14 columns…".
- Left panel row: status "profiling".
- Right panel: the three placeholder cards.
- Chat bar: shows the placeholder "Ask about this CSV (profiling in progress)" but is disabled while profiling (and on a failed dataset). Questions queuing until profiling ends is not built yet.

**Failure.** The dataset stays in the library marked "failed", and the centre shows (`StatusScreens.tsx` `FailedScreen`):
- The heading "Profiling failed".
- Under it: "Sherlock ran into a problem of its own while profiling this CSV, so uploading it again won't help. Try again, and if it fails again, this file can't be loaded yet." The profile job runs after the file was read and checked (§3.2), so its failures are Sherlock's, not the file's.
- A cancelled profile says instead "Profiling was stopped before it finished. Try again to profile this CSV."
- **Try again** retries the failed or cancelled profile job (TRD §4.10), which moves the dataset back to profiling. It shows once the dataset's jobs have loaded and include that job.
- The raw error sits behind a closed "Technical details" toggle (none for a cancel); the server log has the traceback. The reason shown is always in plain words, per UI/UX brief §7.
- Delete is in the dataset menu (⋯) and the library row's menu. A Delete button on the screen itself is not built yet. The jobs tray still shows the raw error under the failed job (not built yet: plain words there too).

Once the dataset leaves profiling, the CSV tab shows the grid of the current version (§8), with the changed, flagged and invalid marks and quarantined rows struck through.

---

## 4. Cleaning offer

Shown in the centre when profiling finishes and the "After upload" setting is "Ask me".

Contents:
- Heading: "Here's what I found in titanic3.csv".
- A line: "1,309 rows · 14 columns · 7 issues".
- The three most severe issues as a list with icons ("263 missing in age", "boat records the outcome"), or "Nothing that needs cleaning." when there are none. Every issue, with its count, examples and planned fix, is in the cleaning plan (§4.1).
- Two buttons: **Clean with AI** (primary) and **Clean it myself**.
- A checkbox "Remember my choice" (writes the After upload setting), with "· You can change this in Settings" beside it. Checked, Clean with AI saves `after_upload: always` and Clean it myself saves `never`.

Transitions:
- **Clean with AI** → §4.1 Cleaning plan. The centre shows "Diagnosing v2 of titanic3.csv…", then the plan. Nothing is cleaned until **Start cleaning**, which goes to §5.
- **Clean it myself** → §6 Dashboard build on the typed version (version 1 plus the automatic typing step, which runs on every path), and the CSV tab opens at once. Its grid is read-only while the build runs, with the banner "Building your dashboard · editing opens when it finishes"; then the user edits by hand or asks the chat (§8, §10). The CSV tab's Clean with AI button showing a dot until cleaning has run once is not built yet.
- **Ask me before each fix** (P1, the plan's Mode, PRD CLEAN-10) → when built, Start opens the Dashboard tab with the chat thread expanded and the first proposed step as an approval card. Until then the Mode row shows it disabled with "comes later".

When After upload skips the offer, an inline line says why (a toast would vanish):
- **"Open the cleaning plan"** (stored as `always`): the profile job makes a draft plan and stops at `offer`, so the plan screen opens by itself. It says "Opened because After upload is “Open the cleaning plan” · Change"; Change opens Settings at After upload. **Discard** on the plan goes back to the offer. Nothing is cleaned without a click.
- **"I'll clean it myself"** (stored as `never`): the dashboard builds directly. The building screen says "Building without cleaning because After upload is “I'll clean it myself” · Change".

### 4.1 Cleaning plan (PRD CLEAN-8a)

What Clean with AI will try, shown before anything runs. Sherlock's code detectors diagnose the **current** version (its data card), so every count comes from code and no model is called. A plan made on an older version (the user edited cells or undid a step before starting) is diagnosed again and merged before it's shown or started: ticks are kept by issue, fixes no longer needed go, new ones come in ticked, and a toast says what changed.

Where it lives: not a modal, so the chat bar stays usable. From the offer it fills the centre; from the CSV tab it opens in the right panel in place of Changes, so the grid stays visible (§8.4).

Contents:
- Header: "Cleaning plan · v2" and "Sherlock checked v2. Untick, edit or add steps, or ask in chat." While it's being made: "Diagnosing v2 of titanic3.csv…".
- The fixes in modules, in this order: Your steps · Types and parsing · Missing and placeholder values · Spelling and formatting · Duplicates and broken records · Outliers · Other checks · Marked, not changed. Empty modules aren't shown. Each module header except Marked, not changed has a tri-state checkbox and "n of m".
- One row per fix, **every fix ticked**: checkbox, the column, the issue ("missing", "spacing or case variants"), the count, and Sherlock's planned action in one muted line. ▸ shows up to 5 example values as chips. With nothing to fix: "Nothing that needs cleaning yet. Add a step of your own below."
- Exact and near duplicate rows share one issue, so the plan shows only the more severe of the two, the one the Cleaner attempts (a known gap).
- **Marked, not changed**: leakage and ID-like columns, and any issue on such a column, with the flag icon, the reason ("ticket looks like an ID column, so it is left as is") and no checkbox. They are never changed.
- **✎ on a fix** (PRD CLEAN-8b) turns its planned action into an instruction the user rewrites (up to 500 characters), with Save, Cancel and Reset (Reset puts Sherlock's wording back). A rewritten fix shows the instruction marked "edited", with Sherlock's wording struck through beneath.
- **An ambiguous-dates fix** asks "Which order are these dates in?": a small table of up to three of its values with their day-first and month-first readings ("03/04/2021 · 3 Apr 2021 · 4 Mar 2021"), and two toggle buttons, **Day first** and **Month first**. Picking one saves at once and marks that column of the table; picking it again clears it. Until one is picked, a muted line says "Every date here reads both ways, so Sherlock won't guess: without an order they stay text." (or, when some dates show their order, "Sherlock reads the dates that show their order; pick one to decide the rest."). The picked order runs as the user's instruction for the fix, with one diagnosis instead of the three-way vote, and the report lists it under "Your steps".
- **"+ Add a step"**: a Column select (the file's columns, plus "Rows") and "What to do", then Add. The step goes under **Your steps** (first), ticked, with ✎ to reword it and × to remove it. A step added from chat says "· from chat".
- **Chat**: while the plan is open the chat bar's placeholder reads "Ask Sherlock to change the plan…". A message like "don't touch outliers" or "also trim spaces in name" changes the plan at once; the reply, written by code, says what changed ("Unticked 1 fix: missing values in cabin."; "Added 1 step on name."), and the plan updates live (§10.3).
- Mode: "Run on its own" (selected) and "Ask me before each fix", disabled with "comes later" (PRD CLEAN-10).
- Footer: "n of m ticked" (past 20 it adds "Sherlock tries up to 20 per run; your steps first, then the most severe"), "Cells you edited by hand are left alone and listed in the report.", **Discard** and **Start cleaning (n)**. Start is disabled with nothing ticked, or while a ✎ editor or the Add a step form holds unsaved text.

Transitions:
- Ticking or unticking saves at once; nothing touches the data until Start.
- **Start cleaning** → §5 with the plan. Unticked fixes are skipped without a model call and logged "not in your plan"; the report lists them with "You left this out of the plan". Issues a fix exposes mid-run, which the plan didn't list, are still attempted. The user's steps run first; they and rewritten fixes follow the user's instruction, still under every hard check.
- If the data changed before Start, the toast says "The data changed; the plan was updated." and nothing starts.
- A plan made on an older version keeps the user's steps while their column exists; a step on a column that's gone is dropped, and the toast says so.
- **A new version while the plan is open** (an edit saved, a step undone, in this tab or another): the plan is read again and merged onto that version, with the toast above. Until it arrives the header reads "Sherlock checked v4; the data is v5. Checking the plan again…".
- **Discard** → the offer again (from the CSV tab, the Changes panel).

---

## 5. Headless cleaning

**Centre panel (cleaning state).**
- Title "Cleaning titanic3.csv", the sentence "Running on its own. You can switch CSVs; it keeps going.", and **Stop** on the right.
- A progress line with the job's label ("Step 7 · embarked") and the elapsed time (mm:ss), over a progress bar. Until the stream's first progress event, it shows the job's stored progress.
- **Live log** (newest at the bottom, auto-scrolls unless the user scrolled up; "Waiting for the first step…" while empty): one entry per event with its time since the start, an icon (✓ committed, ⚑ flagged, ↷ skipped, ● running, a clock while waiting for the model, × error), the column, what was tried (candidate chips, the chosen one filled), the outcome and the gate line in the gate's colour.
- **So far**: issues found, fixed, flagged, and rows deleted (always 0). Read from the run's report, refreshed on every log line.
- **Checks on the latest step**: the hard verifiers of the last committed step with ✓ or ×, such as "No look-alike categories merged" (`merge_safety`) and "Missing values stay missing" (`missing_fill`) (labels in `CleaningProgress.tsx` `CHECK_LABELS`). Then the budget line "7 of 20 issues tried · 00:24 of 05:00".
- A dashed note: "When cleaning finishes, the dashboard builds itself."
- **Pause and review** (P1: switch to step-by-step for the remaining issues) is not built yet. **Stop** (P0) ends the run; committed steps stay and the report covers what ran.

**The log's lines.**
- The log is the job's own log so far (kept 24 h, TRD §4.10) followed by the live lines from the dataset's event stream, each line once. An issue's running line ("263 missing values", "checking candidates") is replaced by its outcome when it arrives.
- **Outcome lines are written by code** from the step's full-data verifier report, never by the model: "Changed 263 cells, quarantined 4 rows; 263 → 0 missing values" (a step the user added has no before → after count).
- **The model's words** appear only without numbers (no digits, no number words): its one-sentence description of the fix, in small grey text under the outcome; a "Left as is" skip's cause (otherwise "Left as is: the values look legitimate"); a decision's reason; the critic's concerns in a flag reason or review.
- **Model calls**: each outcome of an issue the model worked on ends with "3 model calls · Nemotron-3-Ultra-550b-a55b, nemotron-3-super-120b-a12b · 12.3 s" (count, models in the order used, summed latency, from `llm_calls`).
- **Guesses the Cleaner won't make** (PRD CLEAN-4b):
  - Two candidates that pass every check but give the same cells different values: "Skipped: the candidates disagree on 100% of the cells they both change (Thousands separator vs Decimal comma: 1,250 → 1250 vs 1.25; …)". Values that differ only in spelling ("plan a", "Plan A") don't count.
  - A date column whose every value reads both ways: "Left as text: every date reads both ways (03/04/2021 is 3 Apr 2021 or 4 Mar 2021; …), so the order is yours to choose: pick it in the cleaning plan", detail "needs your choice of order". No model is called.
- **Unticked fixes** log "You left this out of the plan", detail "not in your plan". No model is called, and they don't count against the 20-issue budget.
- **The user's steps** come first, as "Your step: trim spaces in name", then their outcome. One that would be skipped for low confidence commits with a flag instead: "low confidence (0.42); kept because you asked for it".

**Tabs.** CSV is enabled: the latest committed version, read-only, with the banner "Cleaning in progress · editing resumes when it finishes". Cells can't be edited, and Add row, Delete row and Restore are disabled with the reason; Clean with AI is disabled ("Cleaning is running."). Dashboard and Flow are disabled with the tooltip "Available after cleaning".

**Right panel.** The story placeholders with "Stories appear once the dashboard is built."

**Chat.** Enabled. Questions about the data run against the latest committed version. Saying so in the answer ("as of step 5") is not built yet.

**Leaving.** Switching to another dataset keeps the job running; its library row shows "cleaning 40%" with a thin progress bar. Coming back restores the log from the server.

**End of run.**
- A run that ends normally (every issue looked at, or a budget reached, even with no step committed) or by **Stop** moves to `building` (§6). During `building` the centre shows "Building your dashboard…" above the report summary. Whether a budget-ended run with zero steps should return to the offer instead is an open decision.
- **The report summary**: "Cleaning report", how the run ended ("Every issue was looked at.", "Stopped at the 20-issue budget.", "You stopped the run.", …) with "v2 → v9" (and "waited 12 s for the model" when it did), the counts found · fixed · flagged · skipped · rows deleted, the first three steps, and **View full report**. It shows until the dashboard is ready, so a fast build can skip it; showing it for at least 3 seconds is not built yet. The same summary, titled "Last cleaning report", opens from the Changes panel's "Full cleaning report" (§8.5).
- **The full report** (a dialog): **Your steps** (each step the user added or fix they rewrote, with "done", "done with a flag", "skipped" with the reason, or "not reached"), **Steps**, **Skipped** (with reasons), **Cells you edited (left as they are)** with a count and an example, **Decisions** ("You asked: …" above the user's own), and **How I worked it out** (collapsed): the run's model calls in order ("Diagnosed an issue", "Proposed fixes", "Reviewed a fix"), each with its model, time, tokens and repairs, then the total. A long run lists its first 500 calls and says how many more there were; the total counts them all (TRD §4.10).
- **Stop**: the job is cancelled at once (a running sandbox worker is killed), committed steps stay, the report covers what ran (`ended_by: stopped`), and the dashboard build starts.
- **Failure** (an error before the run could finish): the dataset goes back to `offer` with the error "Cleaning stopped: <reason>". The offer screen shows "<error>. Your data is safe; you can build the dashboard without cleaning or try again." above its buttons, which now read **Try cleaning again** (it opens a new cleaning plan) and **Build dashboard without cleaning** (it builds on the typed version and stays on the build screen).

---

## 6. Dashboard build

- Centre: a spinner and "Building your dashboard…", above the cleaning report summary when cleaning ran (§5), or the After upload line when the setting skipped cleaning (§4).
- The job tray shows the build's progress: "Choosing charts", "Picking the story", "Adding widgets · 3 of 8".
- When done, the dataset status becomes **ready** and the dashboard's widgets appear all at once. The stories job then writes the cards: the right panel shows three placeholders and "Writing the stories…" until they arrive (§7.4).
- A card that still fails verification after one regeneration shows its fact sheet as bullets.
- If the builder produces fewer than 3 valid widgets (an odd file), the dashboard shows what it has plus a dashed card: "I could only build 2 widgets for this file. Add one from chat, or tell me which columns matter."

Not built yet: skeleton widgets in the chosen layout filling in as their queries return, cards streaming into the right panel during the build, and the top banner "Building your dashboard… 6 of 8 widgets".

---

## 7. Dashboard tab

### 7.1 Layout and header

- Tabs CSV | Dashboard | Flow centred at the top.
- The context row: dataset name, the version pill "v7 · 6 steps", the filter chip ("pclass = 3" with ×) when a filter is set, then **Add widget**, **Edit layout**, the job tray and the dataset menu (⋯): Export notebook (with Ctrl+Shift+E shown) · Download CSV · Rename (a small dialog) · Delete (the confirm in §14). The dataset menu is the same on all three tabs.
- The grid of widgets, then the chat bar per its setting.

Not built yet: clicking the version pill to open the Changes panel, and a **Filter** button with a small filter builder (a filter comes only from clicking a chart). The selection chip is cut (cut 8).

### 7.2 Widget anatomy and states

- Header: drag handle (⠿) · title · scope chip · analysis button (flask, §9) · menu (⋯). The scope chip reads "All rows" ("Some rows" or "Selection" for a scoped widget), plus " · pclass = 3" when the widget applies the dashboard filter; it hides on narrow widgets.
- Body: the chart or table.
- Footer: version stamp ("v7") · "How do you know?" · "Model card" on an analysis · "Outdated" with **Re-run** on an outdated analysis · "first 2,000 rows" when a result is capped.

States: loading (skeleton) · ready · updating (dimmed with a thin progress line, during a filter re-query or the cascade) · outdated (analysis widgets: footer "Outdated" with Re-run) · error (the message in the body with **Retry** and **Show query**) · collapsed (header only).

Menu (⋯): Change view (the views that fit the result, the current one checked) · Duplicate · Collapse (Expand when collapsed) · Show as table (a check item) · Delete. Delete gives the toast "Widget deleted" with Undo for 10 s. Pin number as KPI and Copy as image (both P1) are not built yet.

### 7.3 Interactions

| Action | Result |
|---|---|
| Hover a widget | Its story card lights (accent border and spotlight) and scrolls into view in the right panel; widgets its card lists as related get a 45% accent border. Off in Edit layout. |
| Press on a widget | Makes it the chat's context (the chat chip shows its title). |
| Click a bar, pie slice or ring slice | Sets the global filter (e.g. `pclass = 3`) when the widget's category column is a column of the file. Every widget with `inherit_global_filters` re-queries; the filter chip appears. The clicked chart doesn't filter itself: its element is accented and the rest fade. Clicking the same element again, or the chip's ×, clears it. Lines and tables don't filter. |
| Brush (drag inside a chart body) | Cut (cut 8). |
| Drag the handle (⠿) | Moves the widget (react-grid-layout). The layout saves when the drag ends. |
| Edit layout toggle | Adds resize corners and makes the whole header a drag handle; off by default so a drag in a chart isn't a move. Resizes save when they end. |
| Collapse | Saves `collapsed: true` and keeps the widget's height for when it expands. |
| How do you know? | A drawer: for SQL widgets, the SQL as it runs now with **Copy** and the result row count; for analyses, the run's reproduction code. The SQL includes the global filter only when the widget applies it, so a chart filtered on its own category shows its query without that clause (TRD §6.3). The model card is the footer's "Model card". |
| Analysis button | See §9. |
| Add widget | A drawer with "Describe it" (a text box and Add) and "Quick templates": Bar of X by Y, KPI of X and Table, then "Add template". Adding closes the drawer with a toast "Added “<title>”". A histogram template is not built yet. |
| Delete | Removes the widget; toast "Widget deleted" with Undo for 10 s. |

Also:
- **Loading**: four skeleton cards until the widget list arrives; if it fails, its error message in their place.
- **Fewer than 3 widgets**: the dashed card above the grid (§6). With none, the tab shows "No widgets yet", "Widgets you add, or ask for in chat, appear here." and **Add widget**.
- **A new version**: the dashboard checks its filter against the new version's data card once. A filter whose column is gone, or whose value no row has (when the card lists every value of the column), is cleared with a toast like "Cleared the filter region = North: no row of v5 has region = North.", so the widgets don't all read "No rows match the current filter".

### 7.4 Story panel interactions

The panel shows the overview card first ("Overview" overline, bullets), then a card per widget in dashboard order, then synthesis and answer cards. While the stories job writes them, three placeholders and "Writing the stories…" show.

| Action | Result |
|---|---|
| Hover a card | Its widget gets the spotlight. Off in Edit layout. |
| Click a card (not a button or chip) | The dashboard scrolls to its widget and flashes it for 1.2 s. |
| Click a number chip | Opens "How do you know?": the value, what it is, the version, and the SQL (with Copy) or how it was derived. A hand-typed number says it has no evidence. |
| Evidence (card footer) | Opens the card's first chip. |
| Related chip | Spotlights that widget on hover and flashes it on click. |
| Edit | The card becomes an inline editor (§11). |
| Delete (trash) | Removes the card; toast "Card deleted" with Undo for 10 s. |
| Ask why (not on the overview) | Makes the card's widget the chat context, opens the thread and fills the bar with "Why <headline>?". |
| "changed" badge | Tooltip "Updated after v8. Click to dismiss."; a click dismisses it. P1: showing what changed. |
| "outdated, click to refresh" | Writes the card again. |

The "edited" badge marks a card the user changed; §11 covers its version badges.

---

## 8. CSV tab

### 8.1 Layout

- **Toolbar**: Add row (toast "Row added at the top. Fill it in, then save.") · Delete row ("Delete 3 rows" for several; the rows of the selected cells) · Restore (shown when the selection includes quarantined rows) · Find · Clean with AI · Download (a menu: CSV · Notebook (.ipynb)) · and on the right the legend (changed / flagged / unsaved). Add column (P1) is not built; the Filter control and quick views are cut (cut 5).
- **Header**: when edits are pending, "n unsaved changes", **Discard** and **Save changes (n)** sit in the context row on the right, before the job tray. Review changes is cut (cut 5); the Changes panel's "Unsaved (yours)" list removes single lines instead.
- **Grid**: a frozen first column shows `_row_id` ("new" for a pending row), struck through for quarantined rows and rows marked for deletion. New rows appear at the top until saved. Each header shows the name, the type and the missing share. A header click sorts by that column (ascending, descending, off); the sort is a view only.
- **Column notes (PRD LOAD-7)**: a column with a note (from a data dictionary the user linked, or from the web when chat explained the column) has ⓘ before its type line. Hovering the header shows Sherlock's sentence, the source's own words in quotes, and "From the data dictionary at <site>, retrieved <date>. Not computed from your data." (or "From the web at …"). A dictionary note wins over a web note. Hover only, since the canvas header has no keyboard focus; chat answers the same meaning ("what does <column> mean?").
- **Status bar**: the number of selected cells, the row count (and "sorted by age ↑ (view only)"), "n unsaved", and the current cell ("Row 9 · home.dest"). Selection stats are cut (cut 5).
- **Right panel**: **Changes** (§8.5), or the cleaning plan while one is open (§8.4).
- **While a job owns the data** (`cleaning` or `building`): the grid is read-only with a banner (§5), and Add row, Delete row and Restore are disabled with the reason.

Behaviour:
- **A new view.** A new version, sort or Find clears the selected cells, since they're row positions that now hold other rows; the chat's "3 rows selected" goes with them. An open Find runs again on a new version, so its rows and count are that version's ("No cells match." closes it).
- **A page that fails** to load is asked for twice more (after 0.5 s and 1 s). Then the grid reads "Couldn't load these rows: <reason>" with **Retry**.
- **`?rows=`** shows only those rows, with a "n rows selected" chip and **Show all rows**.
- **Two tabs.** Pending edits made in one tab show in the other (the browser's `storage` event), and a save or Discard in one clears the other's buffer, so the same edits can't be saved twice.

### 8.2 Editing flow

1. The user edits cells, adds rows, or marks rows for deletion or restore. Each action creates **pending edits** (a client-side buffer, mirrored to local storage keyed by dataset and version).
2. Pending cells show the "unsaved" style. The Save button shows the count. The Changes panel lists them under "Unsaved (yours)", each removable.
3. **Save changes** sends the batch. The server validates types (invalid values are saved but flagged), writes one step and a new version, and starts the cascade. The grid reloads the new version; a toast says "Saved as v8 · 12 changes" with **Undo** (which undoes the step; "Undone: back to the data before step 6 (v9).").
4. If rows were added, a second toast asks "Run cleaning on the 3 new rows?" with **Clean them**, which opens the cleaning plan in the right panel scoped to "The 3 rows you just added". Nothing is cleaned until Start cleaning (PRD CLEAN-1).
5. **Discard** asks first ("Discard 12 unsaved changes? They were never saved, so this can't be undone."), then clears the buffer.

Editing a cell: double-click, Enter or typing edits it in place as text. A value that doesn't fit the column's type gets the invalid underline and can be kept. Typing a cell's original value back removes that edit. Type-aware editors (PRD CSV-5: category dropdown, boolean toggle, date picker, autocomplete) are not built yet. Undo/redo of pending edits, block paste and fill down are cut (cut 5). The grid library's default keys still copy a selected range with Ctrl+C and paste the clipboard's text into one cell (PRD CSV-6).

**Conflicts.** If a background job or another tab commits a new version while edits are pending, the Save button becomes **Rebase and save**. The edits are reapplied on the new version by `_row_id`:
- When no edited cell changed in between, the save is resent automatically.
- Otherwise a dialog, "The data changed while you edited", lists each conflict (Cell, Yours, Theirs) with Mine or Theirs, then **Rebase and save**.

### 8.3 Cell interactions

| Action | Result |
|---|---|
| Double-click, Enter or type | Edits the cell in place as text (§8.2). |
| Click, Shift+click, drag, Ctrl+A | Select cells and ranges (the grid library's default keys; `Grid.tsx` sets none; PRD CSV-3, CSV-4). Ctrl+arrow jumps to the data's edge. |
| Delete or Backspace on selected cells | Empties them, as pending edits (the grid library's default). |
| Select cells, then use chat | The chat chip shows "3 rows selected". "Set this age to 1" or "make these empty" makes a proposal (§10.2). "Clean these rows" proposes Clean with AI on them; **Approve** opens the cleaning plan in the right panel scoped to "The n rows you asked to clean", with the toast "The cleaning plan is open for those rows. Look it over, then press Start cleaning." Nothing is cleaned until Start (PRD CLEAN-1). |
| Find (toolbar) | A find bar ("Find in every cell…"). The grid then shows only the matching rows, with the matching cells highlighted and "12 matches in 9 rows; only those rows are shown", until the bar is closed (Esc or ×). No match toasts "No cells match." |

Cut (cut 5): the hover tooltips on changed and flagged cells (`"C22 C26" → "C"` · "Step 3 · Extract deck from cabin" · "Undo step 3"), the right-click menus on cells, row numbers and headers, and jump to row. A step's changed cells are listed under the step in the Changes panel instead. Predicted cells and their tooltip are cut (cut 7).

### 8.4 Clean with AI (any time)

Clicking opens the **cleaning plan** (§4.1) in the right panel in place of Changes, so the grid stays visible; a plan already open stays as it was. On a narrow window the right panel slides over. The button is disabled with its reason while the dataset is profiling, cleaning or building ("Cleaning is running.").

The side plan adds, above the modules:
- **Scope**: Whole dataset · Current selection (n rows; disabled with nothing selected; it uses the rows of the selected cells, saved as a selection) · Rows added since the last clean. A plan opened for some rows (the toast's Clean them, chat's "clean these rows") adds a first radio for them, picked: "The n rows you just added" or "The n rows you asked to clean". The plan stores that scope, so it survives a reload; from the centre (the offer) the plan says "Only the n rows …" under its title and runs on them. With a selection or new-rows scope: "Counts are for the whole file; changes stay inside the rows in scope."
- **With unsaved edits**: "Save or discard your 12 unsaved changes first." with **Discard edits**, and Start is disabled.

Start cleaning starts the job and toasts "Cleaning started. Its steps appear in Changes as they commit."; the right panel goes back to Changes. Discard also gives the panel back to Changes.

While the job runs, the Changes panel shows a "Cleaning…" card with its progress label, a bar and **Stop**; each committed step appears in Steps. A whole-dataset clean also sets the dataset to `cleaning`, so the Dashboard tab shows the live log (§5). Hand-edited cells are skipped and listed in the report under "Cells you edited (left as they are)". Offering "Include these next time" is not built yet.

### 8.5 Changes panel

Header: "Changes" and the version pill. Sections, top to bottom:
- **Cleaning…** while a clean runs (§8.4).
- **Unsaved (yours) · n**: pending edits, one line each ("Row 9 · age: 22 → 23", "New row: …", "Delete row 12", "Restore row 40 from quarantine"), each removable with ×.
- **Steps**, newest first. Each: number, summary, and a detail line (affected columns, cells changed, rows added, deleted or quarantined, "flagged · 0.62", and who made it: automatic, Cleaner, you, chat), with **Undo** on steps in the current data. Expanding shows the code (cleaning and typing steps) or the edit list (edit batches), the impact line, the flag reason, the decisions and, for a code step, up to 6 changed cells as "Row 9 · age: — → 28". With no steps: "No steps yet. Edits you save and cleaning fixes appear here."
- Links: **Full cleaning report** (opens the last report in a drawer) · **Export notebook**. Export pipeline as Python (P1) is not built.

Steps not in the current data read "undone": dashed border, muted and struck through. Undo steps themselves have no Undo.

**Undo.** Undoing the latest step happens at once, with a toast "Undid step 7 · now v9". Undoing an earlier step asks first: "This undoes step 3 and replays the later steps still in effect (steps 4–7) on top. If a replay fails, nothing changes." If a replay fails, the undo is aborted and a toast gives the reason. Saying which replayed steps touch the same column is not built yet. Undoing the automatic typing step (step 1) also asks first, even when it is the latest: "Undoing typing turns every column back into text; charts and models that need numbers will stop working." (with the replay sentence when later steps follow). TRD §7.8 has the replay rules.

---

## 9. ML from a widget

Within cuts 4 and 7: "What drives this?" is the only analysis that runs, and Auto the only method.

1. **The analysis button** (a flask in each widget's header) opens a menu grouped Explain (What drives this?) · Predict (Predict a column) · Group (Find groups, P1) · Unusual (Find unusual rows, P1) · Time (Forecast, P1) · Plain chart (SQL). The options come from `GET /recipes` (TRD §4.8). Disabled options show their reason under the label: Predict "Not in this release", Find groups and Find unusual rows "Coming later", Forecast "Coming later" (or "needs a date column" on a file without one). What drives this? itself is disabled on a file with nothing to explain ("needs a column to explain (a yes/no, a category or a number)") or under 100 rows ("needs 100 rows; this has 80").
   - "Plain chart (SQL)" is checked on a chart. On an analysis it goes back to the chart the analysis replaced (the widget's Undo), with its title. An analysis the builder made has no chart behind it, and a toast says so.
2. **Setup.** "What drives this?" flips the widget body into the setup:
   - **Target**: pre-filled with the analysis's own target, else the chart's measure or category when it can be explained, else the best guess.
   - **Features**: chips from the preview. Excluded ones are struck through, with "Left out: <reason>" on hover. A click toggles a chip; putting an excluded one back shows a warning line, and the model card keeps the warning.
   - **Rows**: the widget's rows and the count with the target. With a dashboard filter active, "Only the filtered rows" (on by default) runs on those rows (cut 8: ML scope comes from a filter or the whole dataset).
   - **Method**: Auto alone, with what it tries ("tries logistic regression, gradient boosting and a random forest on the same folds and keeps the best"; ridge regression in place of logistic for a number target). Choosing Linear or Logistic regression is cut (cut 4).
   - **More**: Folds and Time budget, from the recipe manifest.
   - **Baselines** for this scope from the preview, then "Model: pending" (or "already run" when the same request is cached).
   - "about N s", **Cancel** and **Run**. Run turns the widget into the analysis, titled "What drives <target>?". The same settings as a finished run show its result with the toast "Same settings as an earlier run: showing its result." A recipe that can't run shows "<label> isn't available here: <reason>." with **Back**.
3. **Progress.** The widget shows "What drives <target>: <label>…", a progress bar and the steps ticked off ("preparing data → checking for leakage → setting baselines → testing models → explaining"), with Cancel. The job tray lists the analysis job.
4. **Result.** The verdict line ("Beats the best simple rule by 2.4 points. Gradient boosting: Accuracy 80.4% vs 78.0%."), then the importance bars, the top factor in the accent. The footer has "Model card" (a drawer: excluded columns, method, baselines vs model, importance, who it got wrong, warnings, limits, and Show the code) and "How do you know?" (the run's reproduction code). Its story card is narrated from the run's fact sheet when the run finishes. On a fresh dashboard the builder's "What drives <target>?" widget does the same by itself.
5. **Digging in.**
   - Clicking a factor bar opens its partial-dependence mini chart (the probability or prediction as the factor varies) under the bar.
   - For a category target the widget has a view switcher (Importance · Confusion · ROC, the last for two classes), and the model card shows the confusion matrix and the ROC curve.
   - **"Who did it get wrong?"** in the model card, with the count, saves a selection of the rows the out-of-fold predictions got wrong and opens the CSV tab on `?rows=<selection_id>` ("256 rows selected" on Titanic).
   - Predicted cells and their explanation are cut (cut 7).
6. **Outdated.** After a new version that changes its columns, the footer shows "Outdated" with **Re-run** under "Story updates: Ask first", and the model card says "Outdated: the data changed after this ran on v6." with **Re-run**. Under "Automatic" it re-runs by itself and shows the progress again. Story updates isn't in the Settings dialog (cut 1), so it stays at its default, Automatic, unless set through `PUT /me/settings`.

A failed or cancelled run says so ("The analysis was cancelled.", "The analysis failed: <reason>"), with **Re-run**. "Compare with Auto" in the model card (runs Auto with the same setup and shows both model cards side by side) is cut (cut 4).

---

## 10. Chat (ask anything)

### 10.1 The bar and thread

- **The bar**: a context chip on the left, the input with the placeholder "Ask Sherlock, or tell it what to build…", a `/` hint, and a send button. The "Chat bar" setting pins it, hides it until pointed at or tabbed to (Auto-hide), or hides it.
- **The thread** opens above the bar on focus or typing (at most 40% of the window height) and shows the dataset's conversation. Its header reads "Ask about <file name>" with a close button. Esc closes it. An empty thread shows one hint line: "Ask about the data (“the average of one column for each value of another”), find rows (“the rows where …”), or ask for a widget (“add a chart of … by … to the dashboard”)." The three suggested-question chips under the bar are cut (cut 9).
- **The context chip** shows what the next message applies to:
  - Dashboard: the filter ("pclass = 3"), or else the focused widget's title, with × to clear it; "All rows" otherwise.
  - CSV tab: "3 rows selected" when cells are selected.
  - Flow tab: "3 cards selected", or "Whole canvas" with none.
  - The brush selection chip is cut (cut 8).

What the answerers do (TRD §8.2 has the contracts):
- **"Is fare significantly different between men and women?"** answers with the test the column types call for (Welch's t-test and Mann-Whitney here), the p-value, the effect size and n as chips, a plain verdict, and the test and group tables.
- **"What drives survival?"** answers from the analysis (the dashboard's, the cached one, or a new run waited for up to a minute): the verdict, the metric against the best simple rule, the strongest factors, the importance table and a **Model card** button.
- **"How accurate is the model?"** and **"why was boat left out?"** answer from the model card. **"Who did the model get wrong?"** answers with the count, the first rows and "Open these rows in CSV".
- **"What does sibsp mean?"** answers with what the data says (counts, range and common values), then a dashed box with the general meaning (from the web or the data dictionary when available; below).
- **"How do I undo a step?"** answers from the help pages (`docs/help`), naming the page in How do you know?.
- **Tabs.** Each tab offers its own tools. On the CSV tab "add a chart … to the dashboard" answers with a chart and **Pin to dashboard** instead of adding a widget; the Dashboard tab adds it.

### 10.2 Message lifecycle

1. The user sends a message (Enter or the send button). `/` focuses the bar when nothing editable has focus.
2. A reply appears at once with "Thinking…", then a one-line status from the stream as the agent works ("Running a query", "Finding rows", "Writing the answer"). A multi-step plan shows as a checklist above the answer (○ waiting, ◌ running, ✓ done, × failed) and stays on the saved message.
3. The answer renders in its shape:
   - **Number**: a large value with its label.
   - **Table**: up to 20 rows inline. A row answer links to the CSV tab ("Open these rows in CSV", or "Open all 143 rows in CSV"); other long tables say "Showing 20 of 143 rows".
   - **Chart**: a Bklit chart with **Pin to dashboard** (toast "Pinned “<title>” to the dashboard" with Open), or "Open the widget" when it's already on the dashboard.
   - **Text**: markdown with number chips; **Add to Flow** when it's a narrative answer (toast "Added to the canvas" with Open).
   - **Proposal**: a dashed card with **Approve** / **Reject** for data changes.
   - **Clarification**: the question and 2–3 buttons; the buttons work on the latest message only.
4. Every Sherlock message, clarifications and failures included, has a **How do you know?** disclosure: its sources (labels, SQL, web pages as links), then **How I worked it out** (collapsed, TRD §4.9). That lists the model calls in order: what each did ("Read the question", "Wrote the query"), the model, time and tokens, marked "(repair)", "(failed)", "(cut off, asked again)" or "(in place of the medium model)" (TRD §3.5); then "Total: 3 calls · 4.1 s waiting on them · 5,120 tokens". A web request reads "Searched the web · 5 results" ("cached" when the cache answered). An answer with no model call says "No model was called for this." A copy button on answers is not built yet.
5. Follow-ups reuse the saved focus (scope, columns, result ids).

Streaming and queueing:
- The first table appears as soon as its query has run, and the saved message replaces what streamed the moment it arrives, so the answer shows once.
- The next question waits until the stream ends (the thread summary runs after the answer). One sent meanwhile is queued in the thread ("Queued: sends when this answer finishes · Cancel") and goes when it ends, one at a time (UI/UX §4.8). Cancel puts its text back in the bar.
- **Two tabs.** A message answered in one tab shows in the other's thread too (the dataset stream's `chat.updated`).
- **Reload mid-answer.** The server finishes and saves the answer; after the reload the thread shows it.

**Clarifications.** Besides the router's own, Sherlock asks when it can't place a name ("Which column do you mean by “fair”?" with `fare` and the next closest), when "what does this column mean?" names none, when a test needs two columns, and when "make this a line chart" has no widget clicked (a dashboard with one widget uses it). Each offers 2–3 buttons (TRD §8.1).

**Changing data from chat** (data only changes through a step the user approves):
- **Cell edits.** With cells selected on the CSV tab ("set this age to 1", "make these empty"), or a cell named by its row on any tab ("set the age of row 5 to 200"), the answer is "Nothing has changed yet. Approve to apply this, or reject it." with a proposal card: Row, Column, Now (struck through), After; 20 shown, then "and n more". A number outside its column's range adds "Check row 5 before you approve: 200 is outside the range age holds in this version (0.167 to 80.00)." (TRD §4.4).
  - **Approve** saves a new version ("Saved as v3. Undo it from the Changes panel.") and the card reads Approved; **Reject** reads Rejected; a proposal whose data moved on reads "Expired: the data changed since". Expiring a stale proposal before it's clicked is not built yet: it keeps its buttons until Approve is refused.
- **"Clean these rows"** proposes Clean with AI on the selected rows; approving opens the cleaning plan for them (§8.3).
- **"Delete all the <records> …"** answers that rows can't be deleted from chat ("I can't delete rows from chat, …"), then lists the matching rows with the link to the CSV tab, where Delete row takes them out as a step (TRD §8.1).
- **"Make it a pie chart"** with a widget clicked changes that widget at once, redraws it from its new query, and offers **Undo** ("The widget is back as it was.").

**Other answers.**
- A question about the future ("what will <a measure> be next year?") answers that there's no forecast, says whether the file has a date or time column, and offers a question it can answer; it never asks which column (TRD §8.1).
- "Export a notebook without the data" opens the export dialog with Include data off, and the answer keeps an **Export notebook** button.
- An action that lives on another tab gets told where ("Adding a widget works from the Dashboard tab; ask there, or use Add widget.").

**Failure modes.**
- A query that still fails after its repair: "I couldn't build a working query for that. Try naming the columns, e.g. “…”", the example in the file's own columns (`agent/loop.py::example_question`), or none when the file has none.
- No column answers it: "This file has no column that answers that. The closest I can answer: “…”", as text. A button that asks the closest question is not built yet.
- Too few rows for an analysis: "This needs at least N rows with <target> filled in; …".
- A model outage or a used-up budget: §18.

**Quality of life** (the `?` shortcuts sheet is cut 9):
- **Toasts with Undo (10 s)** after deleting a widget, a dataset, a story card or canvas nodes. Deleted rows stay pending until Save; a saved step has Undo in the Changes panel.
- **Remember where I was**, per dataset in this browser: the last tab (saved on the server), each tab's scroll position, the canvas's pan and zoom, and unsaved CSV edits.
- **Empty states** say what goes there and offer one action (library, dashboard, stories panel, palette, canvas).
- **Error boundaries** around the page, each tab's content, the library and the side panel (§18).
- **Offline banner** (§18).

**Answers from the web (PRD ASK-11, TRD §8.2 `web_context`).** A question about the outside world (what a term means in general, typical values elsewhere, rules, history, recent events) is answered from a web search, never from the data:
- The status line says "Searching the web".
- The answer is a dashed block beginning "From the web (not from your data):": one to three sentences, each followed by a small linked number ([1], [2]) naming its page. It has no number chips: any number from the web stays in the quoted page text.
- Under it, "Searched the web for: “<the query>”" ("(from earlier today)" when cached) and a collapsed "3 sources" list: each page's title (a link that opens in a new tab), its site, the day it was retrieved, and the page's own words in quotes.
- "How do you know?" lists the same pages as links, then the receipt, where the search is a step of its own (above).
- When a plan has a data step and a web step, the data's chips and the web's cited text sit side by side with the line "The web part comes from the pages cited, not from your data; I didn't compare it with the numbers above."
- No key, the hourly limit, a timeout or an error: one line instead ("Web search isn't set up on this server, so I didn't look this up on the web.", …), never an error, and the rest of the answer still comes.
- **Column meanings** ("what does <column> mean?") keep what the data says. The general part reads "In general, from the web (not from your data): …" with citations and sources when web search is on; "From the data dictionary you linked (not from your data): …" when a dictionary is linked, with no search; and "In general (not from your data): …" from the model's general knowledge with no key.
- **"Use the codebook at <url>"** reads that page as the data dictionary (PRD LOAD-7) and answers which columns it describes; the notes then show in the CSV tab's headers.
- **Add to Flow** works on a web answer too: the card keeps the text with its [n] citations and lists the sources with their addresses and dates, and the notebook exports it as cited Markdown (§17.4).

### 10.3 Chat on each tab

| Tab | Context | Typical actions |
|---|---|---|
| Dashboard | global filter, focused widget (brush selection: cut 8) | questions, create/edit widgets, run analyses |
| CSV | selected cells and their rows (at most 500 rows sent) | questions about cells, cell-edit proposals, "clean these rows", (P1) computed columns |
| Flow | selected cards, or the whole canvas | "make sense of this", questions about the cards; "take it toward X", "rewrite this card" (cut 2, 3); "what's missing?" (P1) |
| Any | — | "export a notebook" / "give me this as a Jupyter notebook" opens the Export notebook dialog (§17) with the options pre-filled from the request ("without the stories" unticks Include story cards) |
| Any, while a cleaning plan is open (PRD CLEAN-8b) | the open plan (`plan_id`) | "don't touch outliers", "leave cabin alone", "also trim spaces in name", "fill age by class instead": the plan changes at once (§4.1), and the reply says what changed. Without an open plan the same words answer "Changing a cleaning plan from chat works while the plan is open; press Clean with AI to open one." |

---

## 11. Editing a story card

1. Click **Edit** (or double-click the card on the canvas). The card becomes two TipTap editors, Headline (one line) and Body.
2. Number chips and column labels are atoms: they can be deleted or moved as a whole, not edited character by character. Typing `/` opens a picker of the card's facts ("Find a number…"; type to filter, Enter or click inserts the chip, Esc closes).
3. Save sends the card; the server turns numbers typed by hand, digits or words ("zero", "twice"), into "unverified" chips (dashed outline, tooltip "Typed by you, not computed").
4. **Save** or **Cancel** (Esc cancels too, when the picker is closed). Saving marks the card user-edited (the "edited" pencil badge).
5. Later data changes: chips update in place. An edited card keeps its text and shows, under its body, "The data changed. Suggested revision:" with **Accept**, **Edit** (opens the suggestion in the editor) and **Dismiss**. PRD's side-by-side view (your text vs the AI's revision) isn't built; where the suggestion goes is an open decision.

The editors hold only what a card can store: paragraphs and bullets in the body, one paragraph in the headline, and text, chips and labels. Numbered lists, line breaks, bold, italic, strike, code, underline and links aren't offered.

When the data moves on (PRD STORY-7), an edited card on an older version shows "Written on v5, data is now v7" (also after Dismiss), and one with hand-typed numbers shows "Has numbers you typed; check them". Both go once the user edits the card on the new version (an edit records the version it was written on) or accepts the suggestion. They show on the canvas node too.

---

## 12. Flow tab

Within cuts 2 and 3: no "take the story toward X", no direction cards, no "Rewrite this card".

### 12.1 Layout

- **Header**: **Add note**, **Connect** (pressed while on) and **Fit view**, then the job tray and the ⋯ menu.
- **The canvas** (dot grid). At its top left, "Story canvas · 6 nodes · 3 selected", with **Make sense of this** beside it whenever two or more cards are selected (there, not in the header, so the header never changes width). Zoom buttons bottom-left, minimap bottom-right.
- **Right panel, the palette**: "Story cards", a search box ("Search cards"), every story card as a draggable row marked "on canvas" or "not placed", then "Try asking" ("Make sense of this", "What do these cards say about <a column>?"; a click fills the chat bar), then Export: **Notebook (.ipynb)** and "Obsidian (.canvas) · P1" (not built). With no cards: "Story cards appear here once the dashboard's stories are written."
- The chat bar with the context chip ("3 cards selected" / "Whole canvas").

### 12.2 Interactions

| Action | Result |
|---|---|
| Drag a palette row onto the canvas | Places that card as a node at the drop point. The row becomes "on canvas". |
| Enter or Space on a focused row, or double-click it | Places the card in the middle of the view, below any card already there. The row's accessible name is the card's title and "on canvas" or "not placed". Synthesis and answer cards are listed by their headline. A card already on the canvas isn't placed twice: it's selected and the view centres on it. |
| Drag a node | Moves it. |
| Click a node | Selects it; Shift-, Ctrl- or Cmd-click adds. There is no box selection. Selection is the chat context. |
| Keyboard | Tab reaches each node (and the chips and "Open widget" inside it); Enter selects the focused node, and Shift, Ctrl or Cmd with Enter adds it (React Flow's keyboard selection). Then `/` and "Make sense of this" in the chat bar. |
| Double-click a card node | Edits it in place with the card editor (§11), the same object as in the stories panel. |
| Connect, then click A then B | A hint reads "Click the first node, then the second", then "Now click the node to connect it to". The second click makes the edge, opens its label input, and turns Connect off. Enter saves the label, Esc leaves it as it was. Dragging from a node's side handle to another node also connects them. |
| Click an edge | Selects it; Delete removes it; double-click edits the label. |
| Add note | Places a note at the viewport centre in edit mode. Ctrl+Enter or clicking away saves it, Esc cancels; a new note left empty is removed. Double-clicking a note edits it again. |
| Delete or Backspace with nodes or edges selected | Removes them, with a toast "Removed 2 items from the canvas" ("Cards stay in the palette.") and Undo for 10 s. Notes are deleted; cards stay in the palette. |
| "Open widget" on a card node | Navigates to `?widget=:id` on the Dashboard tab. |
| Scroll / pinch | Zoom; drag the background to pan. |

**Card nodes** show the overline (the widget's title, "Overview", "Answer", or "Synthesis" in the accent colour), the headline and the body with live chips (a chip opens the evidence drawer), "Cites n cards" on a synthesis, "Open widget" on a widget card, and the badges: changed, edited, outdated, and "sources changed" (click to write it again).

**Saving.** Every change saves within a second. When another tab or the AI changed the canvas meanwhile, this tab's changes are merged onto the newer copy and saved again; nothing is lost. A synthesis from chat appears without a reload.

**Remember where I was.** Pan and zoom are kept per dataset in this browser. A canvas opened for the first time with nodes fits them in view; an empty one opens at 100%.

**Empty canvas.** "The canvas is empty", then "Drag story cards here from the palette, or add a note. Select two or more cards and ask Sherlock to make sense of them."

### 12.3 AI actions on the canvas

| Request | What happens |
|---|---|
| "Make sense of this" (needs ≥ 2 selected cards) | A **synthesis** card appears to the right of the selection, with edges labeled "summarized in" from each source. Its chips come from the sources' fact sheets. It carries "Cites n cards". A selected card that's outdated, or whose numbers no longer hold on this version, isn't cited, and the answer names it ("I left out … Refresh them to use them."). Deleting a card a synthesis cites shows "sources changed" on the synthesis. |
| Any other question about the cards | Answered from them, with **Add to Flow**. Outdated cards are left out the same way. |
| Add to Flow on any answer's text (any tab) | Makes an "Answer" card on the canvas with its numbers and their evidence. Only for an answer worked out on the current version: after a new version, older answers lose Add to Flow, and an old button answers "This answer was worked out on version 3; the data is now version 5. Ask again to add the current numbers to Flow." (TRD §4.9). |
| "Take the story toward X" | Cut (cut 2). Planned: a **direction** card in a "building" state (widget query → fact sheet → story → verify), connected to the selection with "next: X", that becomes a normal widget card and also appears on the dashboard; a failed stage shows its error and Retry. |
| "Rewrite this card" (1 selected) | Cut (cut 3). Planned: a chat proposal with the new text (chips only, verified like a story card); Accept replaces the text and marks the card user-edited; Reject discards. |
| "Argue against this" (P1) | Adds cards for widgets that weaken the claim, connected with "contrasts with". Not built. |
| "Order this into a story" (P1) | Proposes a numbered path; Accept numbers the nodes and enables Present mode. Not built. |

Failures: "Select at least two cards to make sense of them." · "There are no story cards to answer from yet." · when every card asked about is outdated, the "I left out …" sentence alone. Add to Flow refuses text without numbers ("Only an answer's text with its numbers can be added to Flow.") and an answer whose cited card changed ("A card this answer cites has changed; ask again to add it.").

---

## 13. Settings overlay

Opened from the gear (library panel or rail) or `?settings=1`. A centred dialog, "Settings", over a dimmed app. Within cut 1 it holds four settings as segmented controls, each with a help line (PRD §7.10, UI/UX brief §5.11):
- **Mode**: Light · Dark · System.
- **Accent**: Verdigris · Arcane · Ember · Aether · Brass.
- **Chat bar**: Pinned · Auto-hide · Hidden.
- **After upload**: Ask me · Open the cleaning plan · I'll clean it myself (stored as `ask|always|never`), with the help "What happens once a new CSV is profiled. Nothing is cleaned until you start a plan."

Changes apply at once and save to the server ("Saved to your Sherlock profile"); the mode and accent preview live behind the dialog. **Done**, Esc or clicking outside closes it. `?settings=1&field=after_upload` opens it scrolled to that field and outlines it; the "Change" links on the plan and building screens use it (§4).

---

## 14. Left panel (library) interactions

| Action | Result |
|---|---|
| Click a row | Opens that dataset on its last tab. |
| Row menu (⋯, on hover or focus) | Rename (inline; Enter saves, Esc cancels) · Download original CSV · Delete. Delete confirms ("Delete <name>? Its versions, dashboard and chat go with it. You can undo for 10 seconds."), then a toast "Deleted <name>" with Undo for 10 s. Deleting the open CSV goes to the library, and Undo reopens it. |
| Status line | "profiling" · "offer · 7 issues" · "cleaning 40%" with a thin progress bar · "building" with a bar · "ready · v7" · "failed" (hover shows the error). Hover text for the other states is not built. |
| Collapse (« / ») | The panel becomes an icon rail: dataset initials as links, Upload, Sample, the gear, and » to expand. |
| Upload CSV / Try with sample | §3. |
| Drag the panel's edge | Resizes the left (or right) panel; with the edge focused, ← and → resize it by 16 px. Sizes are kept in this browser. |

Below 1024 px wide, both side panels become slide-overs opened from buttons at the top of the centre.

---

## 15. Background jobs tray

An icon in the centre header shows the number of running jobs. Clicking lists the jobs of all the user's CSVs, each with its kind (Profiling, Cleaning, Building the dashboard, Writing stories, Analysis, Updating, Undoing, Exporting a notebook, Cleaning up), its CSV's name, and its progress label and bar, with **Cancel**. Finished and cancelled jobs show "Done" or "Cancelled" for 1 minute. Failed jobs show their error and stay until dismissed (×), with **Retry**; dismissing only hides it in this tab. With nothing to show: "No background jobs right now."

---

## 16. The update cascade, as the user sees it

Trigger: a new version (a saved edit batch, a committed cleaning step, an undo). A widget added or changed, or an analysis that finishes, gets its own card written without a cascade (TRD §7.4, §7.6).

1. A thin progress line appears under the header: "Updating 4 widgets and 4 stories".
2. Only widgets that read a changed column dim and show their updating line; others are untouched.
3. Affected analyses show "Outdated · Re-run", or re-run by themselves under "Story updates: Automatic" (§9).
4. Affected cards show a spinner while they're rewritten, then the "changed" badge (or "outdated, click to refresh" under "Ask first"). An edited card gets a suggestion instead (§11).
5. The progress line disappears. A toast summarizes: "v8: 4 widgets re-queried, 4 stories updated."

Rules (TRD §7.6):
- The cascade is debounced: saves within 2 seconds produce one cascade.
- A save while a cascade runs queues the next one behind it; two never run at once, so the cards end on the newer version.
- A cascade that fails or is cancelled leaves no card spinning: the cards it hadn't finished show "outdated, click to refresh", and the next cascade rewrites them.
- An analysis card shows the spinner while its run re-runs, and "outdated, click to refresh" if the run fails.
- A widget changed while the cascade runs keeps the change.

---

## 17. Notebook export

Available from every tab in every status except `profiling` and `failed`. TRD §7.7 specifies the exporter.

### 17.1 Entry points

| Entry | Where |
|---|---|
| Dataset menu (⋯) → Export notebook | Header, all tabs; shows Ctrl+Shift+E, or the reason it's disabled ("Available once the CSV is profiled", "This CSV failed to load") |
| Download → Notebook (.ipynb) | CSV toolbar |
| Changes panel → Export notebook | CSV tab, right panel |
| Palette → Export → Notebook (.ipynb) | Flow tab, right panel |
| Chat: "export a notebook" | Any tab; the dialog opens with the options the message asked for |
| Keyboard: Ctrl+Shift+E | Any dataset tab |
| `?export=notebook` | Deep link |

### 17.2 The dialog

Title "Export notebook". Body:
- One line: "A runnable Jupyter notebook that rebuilds **titanic3.csv v7** from the raw file: 6 steps, 8 widgets, 2 model runs, 9 story cards." (and ", 3 canvas notes" when included).
- Options (checkboxes, remembered per user), each with a help line: **Include data** (on: the raw CSV downloads next to the notebook) · **Include story cards** (on) · **Include canvas notes** (off) · **Include ML runs** (on).
- Order (segmented): **Steps, then dashboard order** (default) · **Flow reading path** (P1; disabled, "Order the canvas first", until a path exists; not built).
- Notes, in one box when any apply:
  - While a cleaning or build job runs: "A job is still running. This export uses v7, the latest committed version."
  - With pending edits: "You have 12 unsaved edits. They are not included; save first to include them." A **Save and export** button is not built yet.
  - The preview's own notes (TRD §4.2), for example "There are no story cards yet, so this notebook has the widgets only." Its running-job note is left out, since the dialog says that itself.
- Footer: Cancel · **Export** (primary).

### 17.3 Flow

1. Export → the dialog closes; a loading toast "Preparing notebook…" (the job shows in the tray).
2. On completion the browser downloads `titanic3-v7.ipynb` and, with Include data, `titanic3-raw.csv` 0.4 s later. The toast becomes "Notebook ready" with **Download again** for 1 minute.
3. A repeat export with nothing changed (same version, same dataset state, same options) comes straight from the cache.
4. A failed export turns the toast into its error; one not done after 2 minutes says "The export didn't finish."

While the dashboard or its stories are being updated, the export waits for them for up to 20 seconds (the job's log says "Waiting for the story cards to finish updating…"). If they're still updating, the notebook's first cell says so and each card that isn't current carries a note. A widget whose query fails on this version becomes a cell saying why, and the rest of the notebook is still written.

### 17.4 What's in the file, in order

1. Title and provenance (Markdown): dataset name, version, export time, Sherlock version, "every number below was computed by code".
2. Parameters (code): `DATA_PATH = "titanic3-raw.csv"`, `RANDOM_SEED = 42`.
3. Requirements (code): a pinned `pip install` line (TRD §10 `NOTEBOOK_PINS`). Its comment says `%pip` needs pip in the kernel's environment: make a uv venv with `uv venv --seed`, or install the pins with `uv pip install` and skip the cell.
4. Helpers (code): only the vendored cleaning helpers this notebook's steps use.
5. Load (code): the raw file decoded with the recorded encoding into a UTF-8 copy, then read the way the app reads it (the recorded delimiter, header and skip options, the same `_row_id` and an empty `_quarantine_reason` column) into `df`.
6. Overview (Markdown): the overview card.
7. Each step in the current version's effective chain, in order (undone steps left out; an undo appears only as a Markdown note): a Markdown cell (step number, summary, gate, decision, impact line) and a code cell (the step's stored code, ending in `df = result`). A final assertion cell checks the row count and columns against the version.
8. Each widget in dashboard order: Markdown (title), code (its DuckDB SQL on the DataFrame, with the result embedded), code (a matplotlib chart), then its story card as Markdown. An analysis widget gets its run's reproduction cell and its importance or coefficients table instead of the SQL and chart.
9. Each other ML run: Markdown (what and why, excluded columns with reasons), the reproduction code, its output tables; its story card.
10. "From the Flow canvas", after the dashboard: synthesis and answer cards, oldest first, each with its numbers and evidence like any card. A web answer comes as cited Markdown: its sentences with their [n] citations, the sources (title, URL, the day each was retrieved), and "From the web pages cited, retrieved on the dates shown; not computed from the data." With **Include canvas notes**, the canvas's notes follow as quoted Markdown in reading order (top to bottom, then left to right). Placing cards and notes along a Flow path is P1 and not built. No API key is ever written into the file.
11. Closing cell: "How to continue" (how to add cells, where the helpers are documented, a link back to Sherlock).

### 17.5 Edge cases

| Situation | Behaviour |
|---|---|
| Dataset is `profiling` or `failed` | The menu item is disabled with the reason; Ctrl+Shift+E and `?export=notebook` do nothing. |
| Export job fails (e.g. a step's code can't be re-rendered) | Toast with the error. Offering "Export up to step k" (a notebook that stops before the failing step, asserts against that earlier version, and says so in its first cell) is not built yet in the UI; the API's `up_to_step` option does it (TRD §4.2). |
| Widget SQL uses a global filter | Not applied; the cell's comment says "The dashboard's global filter isn't applied here; the widget's own rows are (in the WHERE clause)." |
| ML run is `outdated` | Included with the note "Outdated: the data changed after this ran on version 6. The numbers below are from that run; running the cell on this data can give different ones." |
| Analysis not finished | Its section says "This analysis hadn't finished when the notebook was exported, so it's left out." |
| Card edited by the user | Exported with the user's text; numbers typed by hand get a `*` and a footnote. |
| No story cards yet (export during the build) | The notebook says so and includes widgets only. |
| 50 MB file with Include data | The raw CSV download is the original file; the notebook's load cell reads it the same way. Export time ≤ 60 s. |

---

## 18. Error and edge-case catalogue

| Situation | Behaviour |
|---|---|
| Token Factory unavailable | Model calls retry with backoff for at most 2 minutes each (time that counts against the cleaning budget); the cleaning log shows "Waiting for the model…". Then the job fails with "The model service is unavailable. Try again in a minute."; chat answers "The model service is unavailable. Your data is safe; try again in a minute." Non-model features (grid, SQL widgets, filters) keep working (TRD §3.5). |
| A daily model budget is used up | App-wide: "Sherlock has used today's model budget for everyone. It resets at midnight UTC." Per user: "You've used today's model budget. It resets at midnight UTC." A job that hits its own budget: "This job used its model budget."; a chat answer that hits its own: "This answer used its model budget." Chat shows it as a text answer; cleaning and stories take their budget-exceeded paths. Uploads, the grid, edits, widgets and exports keep working (PRD §9, TRD §3.5). |
| Too many new visitors from one network | A first visit past 300 new users an hour from one IP gets `429` with "Too many new visitors from your network. Try again in N minutes." Anyone with a cookie is unaffected (TRD §15). The app shows a whole page, not the shell: "Sherlock can't open a new workspace yet", the server's message, "A browser that has opened Sherlock before isn't affected." and **Try again**. |
| The first request fails for another reason | A whole page: "Sherlock couldn't start", the error (or "Sherlock couldn't reach its server. Check your connection."), and **Try again**. |
| The server refuses an upload | An error toast with the reason: "This file is 73 MB. The limit is 50 MB." ("This file is over 50 MB. …" when the size only shows while reading), "This file has 1,200 columns. The limit is 1,000.", "This file has 2,500,000 rows. The limit is 2,000,000.", "This file has no data rows.", "Couldn't read this file as CSV: …", or the storage quota, "Your CSVs would use 520 MB. The limit is 500 MB; delete a CSV first." No dataset is created. |
| Rows with different numbers of fields | The file imports with its real columns. Short rows are padded with empty cells. A row with extra fields keeps them in `col_N` columns and is quarantined ("extra fields: this row has more fields than the header's 14"). It shows in the grid with its row number struck through, and Restore brings it back (PRD LOAD-3a). The flagged quick view is cut (cut 5). |
| Header not on the first row | The import preview's Header row and Skip rows controls fix it. Left alone, the server's sniffer detects skipped lines and the header (TRD §7.1). |
| LLM returns invalid JSON | One repair retry; then the cleaning step is skipped, or the chat answer falls back to the raw results table. Logged. |
| SQL from the model fails | One repair retry with the error; then "I couldn't build a working query for that. …" (§10.2). |
| Sandbox timeout (30 s of CPU; the wall clock at twice that plus 5 s) | The candidate fix is discarded ("The step hit the sandbox's CPU or memory limit.", or "The step took too long and was stopped." at the wall clock); with no candidate left, the issue is skipped. |
| Browser offline, or the server unreachable | A banner: "Can't reach Sherlock. Your data is safe, and unsaved CSV edits stay in this browser; this clears when the connection is back." It also shows when an API call can't reach the server, and clears once `/healthz` answers (checked every 5 s). Pending edits persist in local storage. Save retrying by itself is not built yet; pressing Save again after the banner clears saves. |
| Session cookie cleared | The library appears empty. There is no recovery; the README and the empty state's small print say so (§2). |
| Dataset expired (7 days) or deleted | Removed from the library. A stale link opens the library with the toast "That CSV is no longer available." |
| Two tabs open on the same dataset | Both receive the dataset's events (SSE). The other tab follows a new version by itself (version pill, grid, Changes panel and dashboard refresh); pending edits are shared through local storage (§8.1) and save through "Rebase and save" when the version moved (§8.2). Chat threads and the canvas stay in step too (§10.2, §12.2). |
| Wide file (> 30 columns) | The auto-dashboard uses the 30 most informative columns (keeping the target, time and first ID columns); the grid shows all. A note saying so in the app is not built yet. |
| No numeric columns | The dashboard shows counts and top-value charts; ML options are disabled with reasons. |
| Tiny file (< 100 rows) | The dashboard builds; supervised ML refuses with the row count needed; stories mention the small sample. |
| All-text file | Profiling detects free-text columns; the dashboard shows top values and lengths; chat can search text. |
| Column with no values | Profiling types it `empty`; it stays in the data, is flagged in the data card, and is left out of widgets, targets and features. |
| Page reloaded while a chat answer streams | The server finishes the answer and saves it; after the reload the thread shows the completed reply. |
| A crash in one part of the page | That part's error boundary (page, tab content, library, side panel) shows "Something went wrong showing the <part>" and "Your data is safe on the server. Try again, or reload the page if it keeps happening.", with **Try again** and **Reload**; the rest keeps working. |
