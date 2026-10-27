# Sherlock · App Flow

Version 1.0 · 2026-10-19 · Every screen, state, transition and edge case, as the user sees them. Read with the [PRD](01-PRD.md) for requirement IDs, the [UI/UX Brief](03-UIUX-BRIEF.md) for how things look, and the [TRD](04-TRD.md) for the API and pipelines behind each screen. "Cut N" refers to the cut order in Implementation Plan §5; every cut there applies.

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
                                                       └──────────────► ready ◄───────────────┘
                                                                          │
                                                                          ▼
                                                                    Dataset view
                                      (CSV grid · chat bar below · right panel: cleaning plan, report, Changes)
                                                               settings overlay (gear)
```

Routes (client-side, `web/src/App.tsx`):

| Route | Screen |
|---|---|
| `/` | Library; redirects to the last opened dataset if one exists. The "Sherlock" wordmark links here and stays on the library. |
| `/d/:datasetId` | The dataset view (§8) |
| `/d/:datasetId/:tab` | The same view, whatever the tab name, so old links still land |
| `?settings=1` | Settings overlay on top of any route; `&field=after_upload` scrolls to that field and outlines it |
| `?rows=:selectionId` | The dataset view filtered to a saved row selection (used by "open these rows") |
| `?export=notebook` | The Export notebook dialog on top of any dataset route |
| anything else | The library |

A dataset has one view; there is no tab switcher. The left panel and the chat bar exist on every dataset route.

---

## 2. First visit and the library

**State: no datasets.**
- Left panel: the "Sherlock" wordmark, the gear, the collapse button («), "Your CSVs" with "No CSVs yet.", then **Upload CSV** and **Try with sample**.
- Centre: the **empty state**. A large drop zone reads "Drop a CSV anywhere", then "or", **Upload**, **Try with sample (Titanic)**, ".csv, .tsv or .txt · up to 50 MB", and the small print "No sign-up: your CSVs stay with this browser. Clearing its cookies, or another browser, starts an empty library." Under it, one sentence: "Sherlock cleans it, then answers any question about it. Every number shows its source."
- Right panel: "How it works", four short tips: Clean, Look, Ask, Export (`library/HomeTips.tsx`).
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

When the image ships the cached seed (TRD §4.2), Try with sample opens a copy that is already **ready**: its cleaning steps and analysis, as the real model made them. There's no import preview, profiling or offer for it. Without the seed, the file goes through §3.2–§5 live.

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

**Import.** The raw file uploads (the Import button shows a spinner), the dataset is created, and the app opens `/d/:id` in the **profiling** state. A progress bar for uploads over 2 MB is not built yet. Only the settings the user changed from what the preview detected are sent; the server detects the rest. Server-side refusals show as an error toast (§18).

**The data dictionary (PRD LOAD-7).** With a URL in the field, Sherlock reads that page once the upload is accepted (TRD §7.1.1), while the file profiles; the dialog doesn't wait. When it's done, a toast says "Read the data dictionary: notes on 3 columns.", or gives the one line saying why it wasn't read ("Web search isn't set up on this server, so I didn't look this up on the web.", "I couldn't find column descriptions on that page.", …). It never holds up or fails the import. The notes show in the grid's column headers (§8.1).

**Until the dataset is ready**, the centre shows the profiling, offer, plan, cleaning or failed screen (§3.3–§5). Once it is `ready`, the centre shows the grid (§8).

### 3.3 Profiling state

- Centre: a spinner and one line that follows the profile job: "Reading titanic3.csv…", then "Typing 14 columns…", then "Profiling 14 columns…".
- Left panel row: status "profiling".
- Right panel: Changes (§8.5), with no steps yet.
- Chat bar: shows the placeholder "Ask about this CSV (profiling in progress)" but is disabled while profiling (and on a failed dataset). Questions queuing until profiling ends is not built yet.

**Failure.** The dataset stays in the library marked "failed", and the centre shows (`StatusScreens.tsx` `FailedScreen`):
- The heading "Profiling failed".
- Under it: "Sherlock ran into a problem of its own while profiling this CSV, so uploading it again won't help. Try again, and if it fails again, this file can't be loaded yet." The profile job runs after the file was read and checked (§3.2), so its failures are Sherlock's, not the file's.
- A cancelled profile says instead "Profiling was stopped before it finished. Try again to profile this CSV."
- **Try again** retries the failed or cancelled profile job (TRD §4.10), which moves the dataset back to profiling. It shows once the dataset's jobs have loaded and include that job.
- The raw error sits behind a closed "Technical details" toggle (none for a cancel); the server log has the traceback. The reason shown is always in plain words, per UI/UX brief §7.
- Delete is in the dataset menu (⋯) and the library row's menu. A Delete button on the screen itself is not built yet. The jobs tray still shows the raw error under the failed job (not built yet: plain words there too).

Once the dataset is `ready`, the centre shows the grid of the current version (§8), with the changed, flagged and invalid marks and quarantined rows struck through.

---

## 4. Cleaning offer

Shown in the centre when profiling finishes and the "After upload" setting is "Ask me".

Contents:
- Heading: "Here's what I found in titanic3.csv".
- A line: "1,309 rows · 14 columns · 7 issues".
- Three issues as a list with icons: a column that's never changed first ("boat records the outcome"), then the most severe by code's default level, then by size ("263 missing values in age"); or "Nothing that needs cleaning." when there are none. Every issue, with its count, examples and planned fix, is in the cleaning plan (§4.1).
- A **Cleaning depth** slider, 1 Surface to 5 Meaning (PRD CLEAN-15), starting at the Cleaning depth setting. The line "rows · columns · issues" and the three issues count only the layers up to it, adding "· n more in deeper layers" when deeper layers found more; with none at this depth but some deeper, the list says "Nothing at this depth. Drag right to look deeper." A line under the slider says what the layer looks at and names the checks it adds. Moving it changes nothing on the server.
- Two buttons: **Clean with AI** (primary) and **Clean it myself**.
- A checkbox "Remember my choice" (writes the After upload setting), with "· You can change this in Settings" beside it. Checked, Clean with AI saves `after_upload: always` and the slider's depth as `clean_depth`, and Clean it myself saves `never`.

Transitions:
- **Clean with AI** → §4.1 Cleaning plan at the slider's depth: it lists only those layers' issues. The centre shows "Diagnosing v2 of titanic3.csv…", then the plan. Nothing is cleaned until **Start cleaning**, which goes to §5.
- **Clean it myself** → the dataset is `ready` at once on the typed version (version 1 plus the automatic typing step, which runs on every path), and the grid opens, editable; the user edits by hand or asks the chat (§8, §10). The toolbar's Clean with AI button showing a dot until cleaning has run once is not built yet.
- **Ask me before each fix** (P1, the plan's Mode, PRD CLEAN-10) → when built, Start keeps the grid in view with the chat thread expanded and the first proposed step as an approval card. Until then the Mode row shows it disabled with "comes later".

When After upload skips the offer:
- **"Open the cleaning plan"** (stored as `always`): the profile job makes a draft plan and stops at `offer`, so the plan screen opens by itself. An inline line (a toast would vanish) says "Opened because After upload is “Open the cleaning plan” · Change"; Change opens Settings at After upload. **Discard** on the plan goes back to the offer. Nothing is cleaned without a click.
- **"I'll clean it myself"** (stored as `never`): the dataset goes from profiling straight to `ready` and the grid opens.

### 4.1 Cleaning plan (PRD CLEAN-8a)

What Clean with AI will try, shown before anything runs. Sherlock's code detectors diagnose the **current** version (its data card), so every count comes from code, and opening the plan never waits for the model: each fix shows code's default severity level until the background review (PRD CLEAN-8c) rates it. A plan made on an older version (the user edited cells or undid a step before starting) is diagnosed again and merged before it's shown or started: the user's own ticks are kept by issue, fixes no longer needed go, new ones come in ticked as their level starts, and a toast says what changed.

Where it lives: not a modal, so the chat bar stays usable. From the offer it fills the centre; from the grid it opens in the right panel in place of Changes, so the grid stays visible (§8.4).

Contents:
- Header: "Cleaning plan · v2" and "Sherlock checked v2. Untick, edit or add steps, or ask in chat.", followed by "Reviewing…" while the review runs; the plan refreshes when it ends (`plan.updated`, and every 3 s while it runs, so a review that ends before the tab is listening isn't missed). While it's being made: "Diagnosing v2 of titanic3.csv…".
- The fixes grouped by level, in this order: Your steps · Breaks answers · Skews answers · Splits groups · Worth a look · Cosmetic · Marked, not changed. Within a level, the largest by code severity first. Empty groups aren't shown. Each group header except Marked, not changed has a tri-state checkbox ("tick all" for the level, or for your steps) and "n of m".
- One row per fix, **every fix ticked except those worth a look** (probably real: outliers, missing values with no rule to recover them, rows that break a usual dependency), which the user can tick one by one or as a level: checkbox, the column, the issue ("missing values", "spacing or case variants"), the count, and Sherlock's planned action in one muted line, then the review's one-line reason in muted text, or "(default level)" when code's default stands. No per-item badge: the group heading carries the level. ▸ shows up to 5 example values as chips. With nothing to fix: "Nothing that needs cleaning yet. Add a step of your own below."
- Exact and near duplicate rows share one issue, so the plan shows only the more severe of the two, the one the Cleaner attempts (a known gap).
- **Marked, not changed**: leakage and ID-like columns, and any issue on such a column, with the flag icon, the reason ("ticket looks like an ID column, so it is left as is") and no checkbox. They are never changed.
- **✎ on a fix** (PRD CLEAN-8b) turns its planned action into an instruction the user rewrites (up to 500 characters), with Save, Cancel and Reset (Reset puts Sherlock's wording back). A rewritten fix shows the instruction marked "edited", with Sherlock's wording struck through beneath, and is ticked: rewording a fix asks for it.
- **The review's levels** arrive while the plan is open: a fix moves to its new group, and one the user hasn't ticked, unticked or reworded is ticked as its new level starts; one they touched keeps their choice.
- **An ambiguous-dates fix** asks "Which order are these dates in?": a small table of up to three of its values with their day-first and month-first readings ("03/04/2021 · 3 Apr 2021 · 4 Mar 2021"), and two toggle buttons, **Day first** and **Month first**. Picking one saves at once and marks that column of the table; picking it again clears it. Until one is picked, a muted line says "Every date here reads both ways, so Sherlock won't guess: without an order they stay text." (or, when some dates show their order, "Sherlock reads the dates that show their order; pick one to decide the rest."). The picked order runs as the user's instruction for the fix, with one diagnosis instead of the three-way vote, and the report lists it under "Your steps".
- **"+ Add a step"**: a Column select (the file's columns, plus "Rows") and "What to do", then Add. The step goes under **Your steps** (first), ticked, with ✎ to reword it and × to remove it. A step added from chat says "· from chat".
- **Suggested checks** (PRD CLEAN-14), above Marked, not changed once the review has written some: each in words ("parch is between 0 and 5") with "suggested by Sherlock", code's count ("3 rows break it.") and the model's reason, an unticked, disabled checkbox (it runs only once kept), **Edit**, **Keep** and **Dismiss**. Edit opens the check's values and "Rows that break it" under the group, as in Add a check, with Save and Cancel; saved, the suggestion shows its new words and count and is still a suggestion; a value that doesn't fit shows the reason as a toast. Keep makes it a check of the dataset: it leaves the group and its item comes in under its level, ticked as that level starts. Dismiss drops it, and it isn't suggested again.
- **"+ Add a check"** (PRD CLEAN-13): a Column select, a Check select (Numbers between · Dates between · One of these values · Matches a pattern · Never missing · Never repeated · Comes after another column · Set by another column), the fields that check needs (Lowest and Highest, Earliest and Latest, the allowed values separated by commas, a pattern, or the other column), "Rows that break it" (Flag the rows for review · Quarantine the rows · Fix the values) and **For every dataset of mine** (P2: the check runs on each of the user's datasets), then Add check. The check comes in at once with code's count: a flagged one under Marked, not changed with its words ("Listed for your review, not changed: rows where it isn't true that fare is at most 100."), the others under their level. A refused check shows the reason as a toast. × on a check's row turns it off, and its row goes.
- **Chat**: while the plan is open the chat bar's placeholder reads "Ask Sherlock to change the plan…". A message like "don't touch outliers", "skip the cosmetic ones", "flag rows where fare is below zero" or "also trim spaces in name" changes the plan at once; the reply, written by code, says what changed ("Unticked 1 fix: missing values in cabin."; "Added 1 step on name."), and the plan updates live (§10.3).
- Mode: "Run on its own" (selected) and "Ask me before each fix", disabled with "comes later" (PRD CLEAN-10).
- Footer: "n of m ticked" (past 20 it adds "Sherlock tries up to 20 per run; your steps first, then the most severe"), "Cells you edited by hand are left alone and listed in the report.", **Discard** and **Start cleaning (n)**. Start is disabled with nothing ticked, or while a ✎ editor or the Add a step form holds unsaved text.

Transitions:
- Ticking or unticking saves at once; nothing touches the data until Start.
- **Start cleaning** → §5 with the plan. Unticked fixes are skipped without a model call and logged "not in your plan"; the report lists them with "You left this out of the plan". Issues a fix exposes mid-run, which the plan didn't list, are still attempted. The user's steps run first; they and rewritten fixes follow the user's instruction, still under every hard check.
- If the data changed before Start, the toast says "The data changed; the plan was updated." and nothing starts.
- A plan made on an older version keeps the user's steps while their column exists; a step on a column that's gone is dropped, and the toast says so.
- **A new version while the plan is open** (an edit saved, a step undone, in this tab or another): the plan is read again and merged onto that version, with the toast above. Until it arrives the header reads "Sherlock checked v4; the data is v5. Checking the plan again…".
- **Discard** → the offer again (from the grid, the Changes panel).

---

## 5. Headless cleaning

**Centre panel (cleaning state).**
- Title "Cleaning titanic3.csv", the sentence "Running on its own. You can switch CSVs; it keeps going.", and **Stop** on the right.
- A progress line with the job's label ("Step 7 · embarked") and the elapsed time (mm:ss), over a progress bar. Until the stream's first progress event, it shows the job's stored progress.
- **Live log** (newest at the bottom, auto-scrolls unless the user scrolled up; "Waiting for the first step…" while empty): one entry per event with its time since the start, an icon (✓ committed, ⚑ flagged, ↷ skipped, ● running, a clock while waiting for the model, × error), the column, what was tried (candidate chips, the chosen one filled), the outcome and the gate line in the gate's colour.
- **So far**: issues found, fixed, flagged, and rows deleted (always 0). Read from the run's report, refreshed on every log line.
- **Checks on the latest step**: the hard verifiers of the last committed step with ✓ or ×, such as "No look-alike categories merged" (`merge_safety`) and "Missing values stay missing" (`missing_fill`) (labels in `CleaningProgress.tsx` `CHECK_LABELS`). Then the budget line "7 of 20 issues tried · 00:24 of 05:00".
- A dashed note: "When cleaning finishes, the grid opens with every fix marked, and Changes lists each step."
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

**Right panel.** Changes (§8.5), with the "Cleaning…" card; each step appears in Steps as it commits.

**Chat.** Enabled. Questions about the data run against the latest committed version. Saying so in the answer ("as of step 5") is not built yet.

**Leaving.** Switching to another dataset keeps the job running; its library row shows "cleaning 40%" with a thin progress bar. Coming back restores the log from the server.

**End of run.**
- A run that ends normally (every issue looked at, or a budget reached, even with no step committed) or by **Stop** sets the dataset to `ready` with the steps it committed. The centre shows the grid, editable, and the right panel shows the report summary above Changes. Whether a budget-ended run with zero steps should return to the offer instead is an open decision.
- **The report summary**: "Cleaning report", how the run ended ("Every issue was looked at.", "Stopped at the 20-issue budget.", "You stopped the run.", …) with "v2 → v9" (and "waited 12 s for the model" when it did), the counts fixed · flagged · checked and kept · couldn't fix · not attempted (PRD CLEAN-6), a muted line "n found · n marked, not changed (leakage and ID columns) · no rows deleted", the first three steps, and **View full report**. A report from a run before skips recorded their kind shows found · fixed · flagged · skipped · rows deleted instead. The same summary, titled "Last cleaning report", opens from the Changes panel's "Full cleaning report" (§8.5).
- **The full report** (a dialog): **Your steps** (each step the user added or fix they rewrote, with "done", "done with a flag", "skipped" with the reason, or "not reached"), **Steps**, then each skipped issue under its line, **Checked and kept**, **Couldn't fix**, **Not attempted** and **Marked, not changed**, with its reason and its level ("Worth a look"); "Nothing was skipped." when none was, **Cells you edited (left as they are)** with a count and an example, **Decisions** ("You asked: …" above the user's own), and **How I worked it out** (collapsed): the run's model calls in order ("Diagnosed an issue", "Proposed fixes", "Reviewed a fix"), each with its model, time, tokens and repairs, then the total. A long run lists its first 500 calls and says how many more there were; the total counts them all (TRD §4.10).
- **Stop**: the job is cancelled at once (a running sandbox worker is killed), committed steps stay, the report covers what ran (`ended_by: stopped`), and the dataset is `ready`.
- **Failure** (an error before the run could finish): the dataset goes back to `offer` with the error "Cleaning stopped: <reason>". The offer screen shows "<error>. Your data is safe; you can use it as is or try cleaning again." above its buttons, which now read **Try cleaning again** (it opens a new cleaning plan) and **Use as is** (`POST /use-as-is`: the typed version becomes `ready` and the grid opens).

---

## 6. Dashboard build

Removed by cut 10.

---

## 7. Dashboard tab

Removed by cut 10.

---

## 8. The dataset view (CSV grid)

### 8.1 Layout

- **Toolbar**: Add row (toast "Row added at the top. Fill it in, then save.") · Delete row ("Delete 3 rows" for several; the rows of the selected cells) · Restore (shown when the selection includes quarantined rows) · Find · Clean with AI · Download (a menu: CSV · Notebook (.ipynb)) · and on the right the legend (changed / flagged / unsaved). Add column (P1) is not built; the Filter control and quick views are cut (cut 5).
- **Header**: when edits are pending, "n unsaved changes", **Discard** and **Save changes (n)** sit in the context row on the right, before the job tray. Review changes is cut (cut 5); the Changes panel's "Unsaved (yours)" list removes single lines instead.
- **Grid**: a frozen first column shows `_row_id` ("new" for a pending row), struck through for quarantined rows and rows marked for deletion. New rows appear at the top until saved. Each header shows the name, the type and the missing share. A header click sorts by that column (ascending, descending, off); the sort is a view only.
- **Column notes (PRD LOAD-7)**: a column with a note (from a data dictionary the user linked, or from the web when chat explained the column) has ⓘ before its type line. Hovering the header shows Sherlock's sentence, the source's own words in quotes, and "From the data dictionary at <site>, retrieved <date>. Not computed from your data." (or "From the web at …"). A dictionary note wins over a web note. Hover only, since the grid's headers take no keyboard focus; chat answers the same meaning ("what does <column> mean?").
- **Status bar**: the number of selected cells, the row count (and "sorted by age ↑ (view only)"), "n unsaved", and the current cell ("Row 9 · home.dest"). Selection stats are cut (cut 5).
- **Right panel**: **Changes** (§8.5), or the cleaning plan while one is open (§8.4), with the last cleaning report's summary above Changes after a clean ends (§5).
- **While a whole-dataset clean runs** (`cleaning`): the centre shows its log instead of the grid (§5).

Behaviour:
- **A new view.** A new version, sort or Find clears the selected cells, since they're row positions that now hold other rows; the chat's "3 rows selected" goes with them. An open Find runs again on a new version, so its rows and count are that version's ("No cells match." closes it).
- **A page that fails** to load is asked for twice more (after 0.5 s and 1 s). Then the grid reads "Couldn't load these rows: <reason>" with **Retry**.
- **`?rows=`** shows only those rows, with a "n rows selected" chip and **Show all rows**.
- **Two tabs.** Pending edits made in one tab show in the other (the browser's `storage` event), and a save or Discard in one clears the other's buffer, so the same edits can't be saved twice.

### 8.2 Editing flow

1. The user edits cells, adds rows, or marks rows for deletion or restore. Each action creates **pending edits** (a client-side buffer, mirrored to local storage keyed by dataset and version).
2. Pending cells show the "unsaved" style. The Save button shows the count. The Changes panel lists them under "Unsaved (yours)", each removable.
3. **Save changes** sends the batch. The server validates types (invalid values are saved but flagged), writes one step and a new version, and marks outdated any analysis that read a changed column (§9). The grid reloads the new version; a toast says "Saved as v8 · 12 changes" with **Undo** (which undoes the step; "Undone: back to the data before step 6 (v9).").
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

Clicking opens the **cleaning plan** (§4.1) in the right panel in place of Changes, so the grid stays visible; a plan already open stays as it was. On a narrow window the right panel slides over. The button is disabled with its reason while the dataset is profiling or cleaning ("Cleaning is running.").

The side plan adds, above the modules:
- **Scope**: Whole dataset · Current selection (n rows; disabled with nothing selected; it uses the rows of the selected cells, saved as a selection) · Rows added since the last clean. A plan opened for some rows (the toast's Clean them, chat's "clean these rows") adds a first radio for them, picked: "The n rows you just added" or "The n rows you asked to clean". The plan stores that scope, so it survives a reload; from the centre (the offer) the plan says "Only the n rows …" under its title and runs on them. With a selection or new-rows scope: "Counts are for the whole file; changes stay inside the rows in scope."
- **With unsaved edits**: "Save or discard your 12 unsaved changes first." with **Discard edits**, and Start is disabled.

Start cleaning starts the job and toasts "Cleaning started. Its steps appear in Changes as they commit."; the right panel goes back to Changes. Discard also gives the panel back to Changes.

While the job runs, the Changes panel shows a "Cleaning…" card with its progress label, a bar and **Stop**; each committed step appears in Steps. A whole-dataset clean also sets the dataset to `cleaning`, so the centre shows the live log (§5). Hand-edited cells are skipped and listed in the report under "Cells you edited (left as they are)". Offering "Include these next time" is not built yet.

### 8.5 Changes panel

Header: "Changes" and the version pill. Sections, top to bottom:
- **Cleaning…** while a clean runs (§8.4).
- **Unsaved (yours) · n**: pending edits, one line each ("Row 9 · age: 22 → 23", "New row: …", "Delete row 12", "Restore row 40 from quarantine"), each removable with ×.
- **Steps**, newest first. Each: number, summary, and a detail line (affected columns, cells changed, rows added, deleted or quarantined, "flagged · 0.62", and who made it: automatic, Cleaner, you, chat), with **Undo** on steps in the current data. Expanding shows the code (cleaning and typing steps) or the edit list (edit batches), the impact line, the flag reason, the decisions and, for a code step, up to 6 changed cells as "Row 9 · age: — → 28". With no steps: "No steps yet. Edits you save and cleaning fixes appear here."
- Links: **Full cleaning report** (opens the last report in a drawer) · **Export notebook**. Export pipeline as Python (P1) is not built.

Steps not in the current data read "undone": dashed border, muted and struck through. Undo steps themselves have no Undo.

**Undo.** Undoing the latest step happens at once, with a toast "Undid step 7 · now v9". Undoing an earlier step asks first: "This undoes step 3 and replays the later steps still in effect (steps 4–7) on top. If a replay fails, nothing changes." If a replay fails, the undo is aborted and a toast gives the reason. Saying which replayed steps touch the same column is not built yet. Undoing the automatic typing step (step 1) also asks first, even when it is the latest: "Undoing typing turns every column back into text; charts and models that need numbers will stop working." (with the replay sentence when later steps follow). TRD §7.8 has the replay rules.

---

## 9. ML through chat

Within cuts 4 and 7: "What drives this?" is the only analysis that runs, and Auto the only method. Chat is the only way in (PRD ML-1); there is no setup form.

1. **Asking.** "What drives survived?" (or "what affects fare?") runs `driver_analysis` with that column as the target, on the rows of the selected cells when there are any, else the whole current version. The target must be a yes/no, a category or a number; a file with none answers "There's no column to explain in this file: it needs a yes/no, a category or a number." Features are chosen by the preview: columns such as IDs, free text and leakage are left out, each with its reason in the model card. The same request as a finished run answers from that run at once.
2. **Progress.** The reply's status line follows the run ("What drives survived: testing models…"), and the job tray lists the analysis job. Chat waits up to a minute; a longer run answers "I started the analysis of what drives survived. It's still running; ask again in a moment and the answer will be ready."
3. **Result.** The verdict (the model's metric against the best simple rule as chips, e.g. accuracy 80.4% vs 78.0%), the strongest factors with their importance as chips, "These are associations, not causes.", the importance table, and a **Model card** button. "How do you know?" names the run (method, folds, version). A question that also names a grouping column ("why did women survive more?") adds that column's place in the model and the outcome by its groups.
4. **The model card** (a drawer): excluded columns with reasons, method, baselines vs model, importance with partial dependence (clicking a factor shows the probability or prediction as it varies), for a category target the confusion matrix and, for two classes, the ROC curve, warnings, limits, and Show the code (the run's reproduction code).
   - **"Who did it get wrong?"** (in the model card, with the count, or asked in chat) saves a selection of the rows the out-of-fold predictions got wrong and opens the grid on `?rows=<selection_id>` ("256 rows selected" on Titanic).
   - **"How accurate is the model?"**, **"why was boat left out?"** answer from the newest run whose target the question names, else the newest run.
   - Predicted cells and their explanation are cut (cut 7).
5. **Outdated.** A new version that changes a column a finished run reads marks it outdated in the same commit (PRD ML-9). Nothing re-runs by itself. The model card says "Outdated: the data changed after this ran on v6." with **Re-run**; chat answers about it say "This model ran on version 6, and the data has changed since in columns it reads, so it's outdated. Re-run it to see the current version."; "run it again" in chat, or Re-run, starts the same analysis on the current version.

A failed or cancelled run says so ("The analysis was cancelled.", "The analysis of what drives survived failed: <reason>"). "Compare with Auto" in the model card (runs Auto with the same setup and shows both model cards side by side) is cut (cut 4).

---

## 10. Chat (ask anything)

### 10.1 The bar and thread

- **The bar**: a context chip on the left, the input with the placeholder "Ask about the data, or tell Sherlock what to change…" ("Ask Sherlock to change the plan…" while a plan is open), a `/` hint, and a send button. The "Chat bar" setting pins it, hides it until pointed at or tabbed to (Auto-hide), or hides it.
- **The thread** opens above the bar on focus or typing (at most 40% of the window height) and shows the dataset's conversation. Its header reads "Ask about <file name>" with a close button. Esc closes it. An empty thread shows one hint line: "Ask about the data (“the average of one column for each value of another”), find rows (“the rows where …”), ask for a chart (“a chart of … by …”), or ask what drives a column." The three suggested-question chips under the bar are cut (cut 9).
- **The context chip** shows what the next message applies to: "3 rows selected" when cells are selected in the grid, "All rows" otherwise.

What the answerers do (TRD §8.2 has the contracts):
- **"Is fare significantly different between men and women?"** answers with the test the column types call for (Welch's t-test and Mann-Whitney here), the p-value, the effect size and n as chips, a plain verdict, and the test and group tables.
- **"What drives survival?"** answers from the analysis (a cached run, or a new one waited for up to a minute): the verdict, the metric against the best simple rule, the strongest factors, the importance table and a **Model card** button (§9).
- **"How accurate is the model?"** and **"why was boat left out?"** answer from the model card. **"Who did the model get wrong?"** answers with the count, the first rows and "Open these rows in CSV".
- **"What does sibsp mean?"** answers with what the data says (counts, range and common values), then a dashed box with the general meaning (from the web or the data dictionary when available; below).
- **"How do I undo a step?"** answers from the help pages (`docs/help`), naming the page in How do you know?.
- **"A chart of fare by class"** answers with a chart block whose query "How do you know?" shows.

### 10.2 Message lifecycle

1. The user sends a message (Enter or the send button). `/` focuses the bar when nothing editable has focus.
2. A reply appears at once with "Thinking…", then a one-line status from the stream as the agent works ("Running a query", "Finding rows", "Writing the answer"). A multi-step plan shows as a checklist above the answer (○ waiting, ◌ running, ✓ done, × failed) and stays on the saved message.
3. The answer renders in its shape:
   - **Number**: a large value with its label.
   - **Table**: up to 20 rows inline. A row answer links to the grid ("Open these rows in CSV", or "Open all 143 rows in CSV"); other long tables say "Showing 20 of 143 rows".
   - **Chart**: a Bklit chart (or a custom visx chart) with its title, drawn from the answer's query.
   - **Text**: markdown with number chips.
   - **Proposal**: a dashed card with **Approve** / **Reject** for data changes.
   - **Clarification**: the question and 2–3 buttons; the buttons work on the latest message only.
4. Every Sherlock message, clarifications and failures included, has a **How do you know?** disclosure: its sources (labels, SQL, web pages as links), then **How I worked it out** (collapsed, TRD §4.9). That lists the model calls in order: what each did ("Read the question", "Wrote the query"), the model, time and tokens, marked "(repair)", "(failed)", "(cut off, asked again)" or "(in place of the medium model)" (TRD §3.5); then "Total: 3 calls · 4.1 s waiting on them · 5,120 tokens". A web request reads "Searched the web · 5 results" ("cached" when the cache answered). An answer with no model call says "No model was called for this." A copy button on answers is not built yet.
5. Follow-ups reuse the saved focus (scope, columns, result ids).

Streaming and queueing:
- The first table appears as soon as its query has run, and the saved message replaces what streamed the moment it arrives, so the answer shows once.
- The next question waits until the stream ends (the thread summary runs after the answer). One sent meanwhile is queued in the thread ("Queued: sends when this answer finishes · Cancel") and goes when it ends, one at a time (UI/UX §4.8). Cancel puts its text back in the bar.
- **Two tabs.** A message answered in one tab shows in the other's thread too (the dataset stream's `chat.updated`).
- **Reload mid-answer.** The server finishes and saves the answer; after the reload the thread shows it.

**Clarifications.** Besides the router's own, Sherlock asks when it can't place a name ("Which column do you mean by “fair”?" with `fare` and the next closest), when "what does this column mean?" names none, and when a test needs two columns. Each offers 2–3 buttons (TRD §8.1).

**Changing data from chat** (data only changes through a step the user approves):
- **Cell edits.** With cells selected in the grid ("set this age to 1", "make these empty"), or a cell named by its row ("set the age of row 5 to 200"), the answer is "Nothing has changed yet. Approve to apply this, or reject it." with a proposal card: Row, Column, Now (struck through), After; 20 shown, then "and n more". A number outside its column's range adds "Check row 5 before you approve: 200 is outside the range age holds in this version (0.167 to 80.00)." (TRD §4.4).
  - **Approve** saves a new version ("Saved as v3. Undo it from the Changes panel.") and the card reads Approved; **Reject** reads Rejected; a proposal whose data moved on reads "Expired: the data changed since". Expiring a stale proposal before it's clicked is not built yet: it keeps its buttons until Approve is refused.
- **"Clean these rows"** proposes Clean with AI on the selected rows; approving opens the cleaning plan for them (§8.3).
- **"Delete all the <records> …"** answers that rows can't be deleted from chat ("I can't delete rows from chat, …"), then lists the matching rows with the link to the grid, where Delete row takes them out as a step (TRD §8.1).

**Other answers.**
- A question about the future ("what will <a measure> be next year?") answers that there's no forecast, says whether the file has a date or time column, and offers a question it can answer; it never asks which column (TRD §8.1).
- "Export a notebook without the data" opens the export dialog with Include data off, and the answer keeps an **Export notebook** button.

**Failure modes.**
- A query that still fails after its repair: "I couldn't build a working query for that. Try naming the columns, e.g. “…”", the example in the file's own columns (`agent/loop.py::example_question`), or none when the file has none.
- No column answers it: "This file has no column that answers that. The closest I can answer: “…”", as text. A button that asks the closest question is not built yet.
- Too few rows for an analysis: "This needs at least N rows with <target> filled in; …".
- A model outage or a used-up budget: §18.

**Quality of life** (the `?` shortcuts sheet is cut 9):
- **Toasts with Undo (10 s)** after deleting a dataset. Deleted rows stay pending until Save; a saved step has Undo in the Changes panel.
- **Remember where I was**: `/` reopens the last opened dataset, and unsaved CSV edits stay in this browser (§8.2).
- **Empty states** say what goes there and offer one action (library, Changes panel, chat thread).
- **Error boundaries** around the page, the dataset view's centre, the library and the side panel (§18).
- **Offline banner** (§18).

**Answers from the web (PRD ASK-11, TRD §8.2 `web_context`).** A question about the outside world (what a term means in general, typical values elsewhere, rules, history, recent events) is answered from a web search, never from the data:
- The status line says "Searching the web".
- The answer is a dashed block beginning "From the web (not from your data):": one to three sentences, each followed by a small linked number ([1], [2]) naming its page. It has no number chips: any number from the web stays in the quoted page text.
- Under it, "Searched the web for: “<the query>”" ("(from earlier today)" when cached) and a collapsed "3 sources" list: each page's title (a link that opens in a new tab), its site, the day it was retrieved, and the page's own words in quotes.
- "How do you know?" lists the same pages as links, then the receipt, where the search is a step of its own (above).
- When a plan has a data step and a web step, the data's chips and the web's cited text sit side by side with the line "The web part comes from the pages cited, not from your data; I didn't compare it with the numbers above."
- No key, the hourly limit, a timeout or an error: one line instead ("Web search isn't set up on this server, so I didn't look this up on the web.", …), never an error, and the rest of the answer still comes.
- **Column meanings** ("what does <column> mean?") keep what the data says. The general part reads "In general, from the web (not from your data): …" with citations and sources when web search is on; "From the data dictionary you linked (not from your data): …" when a dictionary is linked, with no search; and "In general (not from your data): …" from the model's general knowledge with no key.
- **"Use the codebook at <url>"** reads that page as the data dictionary (PRD LOAD-7) and answers which columns it describes; the notes then show in the grid's headers.

### 10.3 Chat context

| When | Context | Typical actions |
|---|---|---|
| Always | selected cells and their rows (at most 500 rows sent), else all rows | questions, charts, "what drives X?" and "run it again" (§9), cell-edit proposals, "clean these rows", (P1) computed columns |
| Always | — | "export a notebook" / "give me this as a Jupyter notebook" opens the Export notebook dialog (§17) with the options pre-filled from the request ("without the data" unticks Include data) |
| Any, while a cleaning plan is open (PRD CLEAN-8b) | the open plan (`plan_id`) | "don't touch outliers", "leave cabin alone", "also trim spaces in name", "fill age by class instead": the plan changes at once (§4.1), and the reply says what changed. Without an open plan the same words answer "Changing a cleaning plan from chat works while the plan is open; press Clean with AI to open one." |

---

## 11. Editing a story card

Removed by cut 11.

---

## 12. Flow tab

Removed by cut 12.

---

## 13. Settings overlay

Opened from the gear (library panel or rail) or `?settings=1`. A centred dialog, "Settings", over a dimmed app. Within cut 1 it holds four settings, plus Cleaning depth, as segmented controls, each with a help line (PRD §7.10, UI/UX brief §5.11):
- **Mode**: Light · Dark · System.
- **Accent**: Verdigris · Arcane · Ember · Aether · Brass.
- **Chat bar**: Pinned · Auto-hide · Hidden.
- **After upload**: Ask me · Open the cleaning plan · I'll clean it myself (stored as `ask|always|never`), with the help "What happens once a new CSV is profiled. Nothing is cleaned until you start a plan."
- **Cleaning depth**: 1 · Surface · 2 · Columns · 3 · Records · 4 · Relationships · 5 · Meaning (stored as `1`–`5`), with the help "How deep a new cleaning plan looks. Each layer adds checks on a wider part of the data."

Changes apply at once and save to the server ("Saved to your Sherlock profile"); the mode and accent preview live behind the dialog. **Done**, Esc or clicking outside closes it. `?settings=1&field=after_upload` opens it scrolled to that field and outlines it; the "Change" link on the plan screen uses it (§4).

---

## 14. Left panel (library) interactions

| Action | Result |
|---|---|
| Click a row | Opens that dataset. |
| Row menu (⋯, on hover or focus) | Rename (inline; Enter saves, Esc cancels) · Download original CSV · Delete. Delete confirms ("Delete <name>? Its versions, analyses and chat go with it. You can undo for 10 seconds."), then a toast "Deleted <name>" with Undo for 10 s. Deleting the open CSV goes to the library, and Undo reopens it. |
| Status line | "profiling" · "offer · 7 issues" · "cleaning 40%" with a thin progress bar · "ready · v7" · "failed" (hover shows the error). Hover text for the other states is not built. |
| Collapse (« / ») | The panel becomes an icon rail: dataset initials as links, Upload, Sample, the gear, and » to expand. |
| Upload CSV / Try with sample | §3. |
| Drag the panel's edge | Resizes the left (or right) panel; with the edge focused, ← and → resize it by 16 px. Sizes are kept in this browser. |

Below 1024 px wide, both side panels become slide-overs opened from buttons at the top of the centre.

---

## 15. Background jobs tray

An icon in the centre header shows the number of running jobs. Clicking lists the jobs of all the user's CSVs, each with its kind (Profiling, Cleaning, Analysis, Undoing, Exporting a notebook, Cleaning up), its CSV's name, and its progress label and bar, with **Cancel**. Finished and cancelled jobs show "Done" or "Cancelled" for 1 minute. Failed jobs show their error and stay until dismissed (×), with **Retry**; dismissing only hides it in this tab. With nothing to show: "No background jobs right now."

---

## 16. The update cascade, as the user sees it

Removed by cut 11.

---

## 17. Notebook export

Available on a dataset in every status except `profiling` and `failed`. TRD §7.7 specifies the exporter.

### 17.1 Entry points

| Entry | Where |
|---|---|
| Dataset menu (⋯) → Export notebook | Header; shows Ctrl+Shift+E, or the reason it's disabled ("Available once the CSV is profiled", "This CSV failed to load") |
| Download → Notebook (.ipynb) | Grid toolbar |
| Changes panel → Export notebook | Right panel |
| Chat: "export a notebook" | The dialog opens with the options the message asked for |
| Keyboard: Ctrl+Shift+E | Any dataset route |
| `?export=notebook` | Deep link |

### 17.2 The dialog

Title "Export notebook". Body:
- One line: "A runnable Jupyter notebook that rebuilds **titanic3.csv v7** from the raw file: 6 steps, 2 model runs."
- Options (checkboxes, remembered per user), each with a help line: **Include data** (on: the raw CSV downloads next to the notebook) · **Include ML runs** (on).
- Notes, in one box when any apply:
  - While a cleaning job runs: "A job is still running. This export uses v7, the latest committed version."
  - With pending edits: "You have 12 unsaved edits. They are not included; save first to include them." A **Save and export** button is not built yet.
  - The preview's own notes (TRD §4.2). Its running-job note is left out, since the dialog says that itself.
- Footer: Cancel · **Export** (primary).

### 17.3 Export flow

1. Export → the dialog closes; a loading toast "Preparing notebook…" (the job shows in the tray).
2. On completion the browser downloads `titanic3-v7.ipynb` and, with Include data, `titanic3-raw.csv` 0.4 s later. The toast becomes "Notebook ready" with **Download again** for 1 minute.
3. A repeat export with nothing changed (same version, same dataset state, same options) comes straight from the cache.
4. A failed export turns the toast into its error; one not done after 2 minutes says "The export didn't finish."

### 17.4 What's in the file, in order

1. Title and provenance (Markdown): dataset name, version, export time, Sherlock version, "every number below was computed by code".
2. Parameters (code): `DATA_PATH = "titanic3-raw.csv"`, `RANDOM_SEED = 42`.
3. Requirements (code): a pinned `pip install` line (TRD §10 `NOTEBOOK_PINS`). Its comment says `%pip` needs pip in the kernel's environment: make a uv venv with `uv venv --seed`, or install the pins with `uv pip install` and skip the cell.
4. Helpers (code): only the vendored cleaning helpers this notebook's steps use.
5. Load (code): the raw file decoded with the recorded encoding into a UTF-8 copy, then read the way the app reads it (the recorded delimiter, header and skip options, the same `_row_id` and an empty `_quarantine_reason` column) into `df`.
6. Each step in the current version's effective chain, in order (undone steps left out; an undo appears only as a Markdown note): a Markdown cell (step number, summary, gate, decision, impact line) and a code cell (the step's stored code, ending in `df = result`). A final assertion cell checks the row count and columns against the version.
7. With **Include ML runs**, each finished ML run (done or outdated, newest first, at most ten; an outdated one says so): Markdown (what and why, excluded columns with reasons), the reproduction code, its output tables.
8. Closing cell: "How to continue" (how to add cells, where the helpers are documented, a link back to Sherlock).

No API key is ever written into the file.

### 17.5 Edge cases

| Situation | Behaviour |
|---|---|
| Dataset is `profiling` or `failed` | The menu item is disabled with the reason; Ctrl+Shift+E and `?export=notebook` do nothing. |
| Export job fails (e.g. a step's code can't be re-rendered) | Toast with the error. Offering "Export up to step k" (a notebook that stops before the failing step, asserts against that earlier version, and says so in its first cell) is not built yet in the UI; the API's `up_to_step` option does it (TRD §4.2). |
| ML run is `outdated` | Included with the note "Outdated: the data changed after this ran on version 6. The numbers below are from that run; running the cell on this data can give different ones." |
| Analysis not finished | Its section says "This analysis hadn't finished when the notebook was exported, so it's left out." |
| 50 MB file with Include data | The raw CSV download is the original file; the notebook's load cell reads it the same way. Export time ≤ 60 s. |

---

## 18. Error and edge-case catalogue

| Situation | Behaviour |
|---|---|
| Token Factory unavailable | Model calls retry with backoff for at most 2 minutes each (time that counts against the cleaning budget); the cleaning log shows "Waiting for the model…". Then the job fails with "The model service is unavailable. Try again in a minute."; chat answers "The model service is unavailable. Your data is safe; try again in a minute." Non-model features (grid, edits, undo, exports) keep working (TRD §3.5). |
| A daily model budget is used up | App-wide: "Sherlock has used today's model budget for everyone. It resets at midnight UTC." Per user: "You've used today's model budget. It resets at midnight UTC." A job that hits its own budget: "This job used its model budget."; a chat answer that hits its own: "This answer used its model budget." Chat shows it as a text answer; cleaning takes its budget-exceeded path. Uploads, the grid, edits and exports keep working (PRD §9, TRD §3.5). |
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
| Two tabs open on the same dataset | Both receive the dataset's events (SSE). The other tab follows a new version by itself (version pill, grid and Changes panel refresh); pending edits are shared through local storage (§8.1) and save through "Rebase and save" when the version moved (§8.2). Chat threads stay in step too (§10.2). |
| No numeric columns | Chat answers with counts and top values; "what drives X?" explains a category or yes/no target, and refuses with the reason when there is none (§9). |
| Tiny file (< 100 rows) | Supervised ML refuses with the row count needed. |
| All-text file | Profiling detects free-text columns; chat can search text. |
| Column with no values | Profiling types it `empty`; it stays in the data, is flagged in the data card, and is left out of targets and features. |
| Page reloaded while a chat answer streams | The server finishes the answer and saves it; after the reload the thread shows the completed reply. |
| A crash in one part of the page | That part's error boundary (page, the dataset view's centre, library, side panel) shows "Something went wrong showing the <part>" and "Your data is safe on the server. Try again, or reload the page if it keeps happening.", with **Try again** and **Reload**; the rest keeps working. |
