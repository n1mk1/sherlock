# Sherlock · App Flow

Version 1.0 · 2026-10-19 · Every screen, state, transition and edge case. Read with the [PRD](01-PRD.md) for requirement IDs and the [UI/UX Brief](03-UIUX-BRIEF.md) for how things look.

---

## 1. Map of the app

```
First visit ──► Empty library ──► (drop / upload / sample) ──► Import preview ──► Profiling
                                                                                   │
                                                                                   ▼
                                                                          Cleaning offer
                                                               ┌──────────────┼───────────────┐
                                                        Clean it for me   Use as is    Go step by step (P1)
                                                               │              │               │
                                                               ▼              │               ▼
                                                        Headless cleaning     │        Step-by-step thread
                                                               │              │               │
                                                               └──────► Dashboard build ◄─────┘
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

### 3.2 Import preview (modal)

Shown as soon as a file is chosen. The preview is parsed client-side from the local file; nothing is uploaded until Import.

Contents:
- File name and size.
- **Delimiter** (auto-detected; dropdown: comma, tab, semicolon, pipe, other).
- **Encoding** (auto-detected; dropdown: UTF-8, UTF-8 with BOM, Latin-1, Windows-1252, UTF-16).
- **Header row** (auto-detected; number input; 0 = no header, columns get `col_1…`).
- **Skip rows** before the header (number, default 0).
- A preview table of the first 20 rows as currently parsed, with column names in the header.
- A line: "Detected 14 columns · about 1,309 rows".
- Buttons: **Import** (primary) and **Cancel**.

Rules:
- Changing any control re-parses the preview (client-side with Papa Parse) within 500 ms.
- Import is disabled while 0 columns or 0 rows parse, with the reason under the button. A zero-byte file, a header-only file, or one with nothing left after skip rows shows "This file has no data rows." The server applies the same rule and creates no dataset.
- Duplicate column names get suffixes (`name`, `name_2`) and a note appears.
- Files over 50 MB are refused before upload with "This file is 73 MB. The limit is 50 MB."
- Files that look binary (NUL bytes in the first 64 KB, outside UTF-16) show "Couldn't read this as text. Is it a spreadsheet or a zip? Export it as CSV first."

Import uploads the raw file (with a progress bar for files > 2 MB), creates the dataset, and navigates to `/d/:id/dashboard` (or the default tab) in the **profiling** state. As built (2026-10-24), the Import button shows a spinner while the upload runs; the byte-level progress bar for large files isn't built yet. Only the settings the user changed from what the preview detected are sent as import options; the server detects the rest itself. Until the status is **ready**, the centre panel of every tab route shows the profiling, offer, cleaning or build screen, except that during cleaning the CSV tab shows the read-only grid (§5).

### 3.3 Profiling state

Centre: a spinner with "Reading titanic3.csv…" then "Profiling 14 columns…". Left panel row shows status "profiling". Chat bar enabled with the placeholder "Ask about this CSV (profiling in progress)"; questions queue until profiling ends. The right panel shows the three placeholder cards.

Failure: "Profiling failed: <reason>. You can delete this CSV and try again." with a Delete button. The dataset stays in the library marked "failed". (The Delete button arrives with library delete, Implementation Plan D4.5.)

Until the Glide grid lands (Implementation Plan D5.1), the CSV tab shows a read-only table of the current version, 100 rows a page, with the changed, flagged and invalid marks and quarantined rows struck through. It's available once the dataset leaves profiling.

---

## 4. Cleaning offer

Shown in the centre when profiling finishes and the "After upload" setting is "Ask me".

Contents:
- Heading: "Here's what I found in titanic3.csv".
- The one-line summary: top 3 issues by impact ("263 missing ages · 1,014 missing cabins · 2 columns look like they record the outcome").
- An expandable "All 7 issues" list: each with column, issue type, count, and what Sherlock would do.
- Three buttons: **Clean it for me** (primary), **Use as is**, and (P1) **Go step by step**.
- A checkbox: "Remember my choice" (writes the "After upload" setting).

Transitions:
- **Clean it for me** → §5 Headless cleaning.
- **Use as is** → §6 Dashboard build on the typed version (version 1 plus the automatic typing step, which runs on every path). The CSV tab's "Clean with AI" button later shows a small dot until cleaning has run once.
- **Go step by step (P1)** → the Dashboard tab opens with the chat thread expanded and the first proposed step as an approval card.

If the setting is "Always clean", the offer is skipped and cleaning starts; a toast says "Cleaning automatically (change in Settings)". If "Never clean", the dashboard builds directly.

---

## 5. Headless cleaning

**Centre panel (cleaning state).**
- Title "Cleaning titanic3.csv" and the sentence "Running on its own. You can switch CSVs; it keeps going."
- A progress bar: "Step 7 · embarked" and elapsed time.
- **Live log** (newest at the bottom, auto-scroll unless the user scrolled up): one entry per event with timestamp, an icon (✓ committed, ⚑ flagged, ↷ skipped, ● running), the column, what was tried (candidate chips), what was chosen, the gate outcome.
- **So far** card: issues found / fixed / flagged / rows deleted (always 0).
- **Checks** card: the verifiers with ✓ as they pass on the latest step; the budget line "7 of 20 issues tried · 0:24 of 5:00".
- Button: **Pause and review** (P1: switches to step-by-step for remaining issues). P0: **Stop** (ends the run; committed steps stay; the report is produced for what ran).

**Tabs.** CSV is enabled (shows the latest committed version, read-only while the job runs, with a banner "Cleaning in progress · editing resumes when it finishes"). Dashboard and Flow are disabled with the tooltip "Available after cleaning".

**Right panel.** The story placeholders with "No stories yet. They appear once the dashboard is built."

**Chat.** Enabled. Questions about the data run against the latest committed version and say so ("as of step 5").

**Leaving.** Switching to another dataset keeps the job running; the left panel row shows the progress bar and percentage. Coming back restores the log from the server.

**End of run.**
- The centre shows the **report** for 3 seconds (counts and the first three steps) with "View full report", then transitions automatically to the dashboard build. The full report lives in the CSV tab's Changes panel.
- On failure (server error, budget exceeded with zero steps): the centre shows the error and two buttons: **Build dashboard without cleaning** (uses the typed version) and **Try cleaning again**.

---

## 6. Dashboard build

Centre: the grid appears with skeleton widgets in the layout the builder chose; each fills in as its query returns. Right panel: cards stream in as they pass verification, overview first. A card that still fails verification after one regeneration shows its fact sheet as bullets. A top banner "Building your dashboard… 6 of 8 widgets" disappears when done.

If the builder produces fewer than 3 valid widgets (odd file), the dashboard shows what it has plus an empty-state card: "I could only build 2 widgets for this file. Add one from chat, or tell me which columns matter."

When done, the dataset status becomes **ready**.

---

## 7. Dashboard tab

### 7.1 Layout and header

- Tabs CSV | Dashboard | Flow centred at the top.
- Under them: dataset name, "v7 · 6 steps" (click opens the Changes panel in the CSV tab), the **filter bar** (active global filter chip, selection chip, and a "Filter" button that opens a small filter builder), then **Add widget**, **Edit layout**, and the dataset menu (⋯): Export notebook · Download CSV · Rename · Delete. The dataset menu is the same on all three tabs.
- Grid of widgets. Chat bar at the bottom per its setting.

### 7.2 Widget anatomy and states

Header: drag handle · title · scope chip ("All rows" / "3rd class · 709") · analysis dropdown · menu (⋯).
Body: the chart or table.
Footer: version stamp ("v7") · "How do you know?" link · status (outdated / updating / error).

States: loading (skeleton) · ready · updating (dimmed with a thin progress line) · outdated (footer badge with "Re-run") · error (message in the body with "Retry" and "Show query").

Menu (⋯): Change view (list of compatible views) · Duplicate · Collapse · Pin number as KPI (P1, for single-value results) · Copy as image (P1) · Show as table · Delete.

### 7.3 Interactions

| Action | Result |
|---|---|
| Hover a widget | Its story card highlights and scrolls into view in the right panel; related widgets get the spotlight. Suppressed during drag, resize and brush. |
| Click a bar / slice / heatmap cell | Sets the global filter (e.g. `pclass = 3`). Every widget with `inherit_global_filters` re-queries. The filter chip appears. Clicking the same element again, or the chip's ×, clears it. |
| Brush (drag inside a chart body) | Creates a row selection shown as a selection chip with the count. It's available to the analysis dropdown ("Rows: selection") and the chat ("selected rows"). Esc or the chip's × clears it. |
| Drag the handle (⠿) | Moves the widget (react-grid-layout). Layout saves on drop. |
| Drag the corner | Resizes. Charts re-measure. |
| Edit layout toggle | Adds resize corners and makes the whole header a drag handle on all widgets; off by default so brushing isn't accidentally a drag. |
| How do you know? | Opens a drawer: for SQL widgets, the SQL with a "Copy" button and the row count; for ML widgets, the recipe, scope, params and the model card. |
| Analysis dropdown | See §9. |
| Add widget | Opens a drawer with: "Describe it" (text to chat), and quick templates by column (bar of X by Y, histogram of X, KPI of X, table). |
| Delete | Removes the widget and its card; toast with Undo for 10 s. |

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

## 8. CSV tab

### 8.1 Layout

- Toolbar: Add row · Add column (P1) · Find · Filter · Clean with AI · Download (a menu: CSV · Notebook (.ipynb)) · and on the right the legend (changed / flagged / unsaved).
- Header line: dataset name, version, "n unsaved changes", **Discard**, **Save changes (n)**.
- The grid.
- Status bar (bottom of the grid): selection stats · row count · "Row 9, col home.dest".
- Right panel: **Changes**.

### 8.2 Editing flow

1. The user edits cells, adds or deletes rows, pastes, fills, or uses find-and-replace. Each action creates **pending edits** (client-side buffer, mirrored to local storage keyed by dataset and version).
2. Pending cells show the "unsaved" style. The Save button shows the count. The Changes panel lists them under "Unsaved (yours)".
3. **Undo/redo** operate on the pending buffer.
4. **Review changes** (link next to Save) opens a drawer with one line per edit (row, column, old → new) and a per-line discard.
5. **Save changes** sends the batch. The server validates types (invalid values are saved but flagged), writes one step and a new version, and starts the cascade. The grid reloads the new version; a toast says "Saved as v8 · 12 changes" with Undo (which undoes the step).
6. If new rows were added, the toast also offers "Run cleaning on the 3 new rows".
7. **Discard** clears the buffer after confirmation.

Conflicts: if a background job commits a new version while edits are pending (e.g. "Clean with AI" started from chat), the Save button becomes "Rebase and save" and the edits are reapplied on the new version by `_row_id`; edits to cells that the job also changed are listed for the user to resolve (keep mine / keep theirs).

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
| Select a range then type in chat | The chat context shows "n cells selected"; "clean this" or "standardize these" proposes "Clean n cells in <column>?"; Approve starts Clean with AI on that selection. |

### 8.4 Clean with AI (any time)

Clicking opens a small popover:
- Scope: Whole dataset · Current selection (n cells) · Rows added since last clean (n).
- Mode: Auto · Step by step (P1).
- A note if there are unsaved edits: "Save or discard your 12 unsaved changes first." with both buttons.
- **Start**.

It runs as a job with the same live log, shown in a slide-over on the right (the Changes panel) so the grid stays visible. Hand-edited cells are skipped and listed in the report with "Include these next time" as an option.

### 8.5 Changes panel

Sections, top to bottom:
- **Unsaved (yours)**: pending edits with a count, each line removable.
- **Steps**: newest first. Each: number, summary, affected columns and cell count, confidence/flag, **Undo**. Expanding shows the code (for cleaning steps) or the edit list (for edit batches), the impact report and the decision entries.
- Links: Full cleaning report · Export notebook (.ipynb) · Export pipeline as Python (P1).

Undo of a non-latest step: a confirmation explains "This undoes step 3 and replays the later steps still in effect (4–7) on top. 2 later steps touch the same column and will be re-run." If a replay fails, the undo is aborted and the reason shown. Undoing the automatic typing step (step 1) also asks first, even when it is the latest step: "Undoing typing turns every column back into text; charts and models that need numbers will stop working."

---

## 9. ML from a widget

1. The user opens a widget's **analysis dropdown**. Options are grouped: Explain (What drives this?) · Predict (Predict a column) · Group (Find groups, P1) · Unusual (Find unusual rows, P1) · Time (Forecast, P1) · Plain chart (SQL). Incompatible options are disabled with the reason.
2. Choosing one flips the widget body into **setup**: Target (dropdown, pre-filled) · Features (chips; excluded ones crossed out with reasons on hover; click to toggle, with a warning when re-including an excluded one) · Rows (scope chip; "Use selection" if a brush selection exists) · Method (Auto · Linear regression · Logistic regression; incompatible ones disabled) · More (advanced params from the recipe manifest) · baselines preview for this scope · **Run** and **Cancel**.
3. **Run** starts a job. The widget shows plain-language progress ("checking for leakage → baselines → testing models → explaining"). The job tray (small icon in the header) lists it.
4. On completion the widget shows the result view with the verdict line, the chart, the view switcher, and a **Model card** link (drawer). Its story card updates.
5. Digging in: clicking a factor bar shows a partial-dependence mini chart; "Who did it get wrong?" opens the CSV tab filtered to those rows (`?rows=`); clicking a predicted cell shows its explanation.
6. If the data changes later, the footer shows "Outdated" with **Re-run** (or it re-runs automatically per the story-update setting).

"Compare with Auto" in the model card runs Auto with the same setup and shows both model cards side by side.

---

## 10. Chat (ask anything)

### 10.1 The bar and thread

- Collapsed: a single input with the placeholder "Ask Sherlock, or tell it what to build…", a `/` hint, and a send button. Under it, three **suggested questions** as chips.
- Focus or typing expands the thread above the input (max 40% of the centre height), showing the dataset's conversation. Esc collapses it.
- A **context chip** on the left of the input shows what the next message applies to: "All rows", "Selection: 709 rows", "3 cards selected", "Cell B12", or the widget name when a widget is focused. Clicking it clears the context.

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
5. Follow-ups reuse the saved focus (scope, columns, result ids).

Failure modes: "I couldn't turn that into a query. Try naming the column, e.g. 'average fare by pclass'." · "There's no column for nationality. The closest is home.dest; want that?" (button) · "That needs about 100 rows and this selection has 41."

### 10.3 Chat on each tab

| Tab | Context | Typical actions |
|---|---|---|
| Dashboard | global filter, brush selection, focused widget | questions, create/edit widgets, run analyses |
| CSV | selected cells/rows/columns | questions about cells, "clean this", "standardize these", (P1) computed columns |
| Flow | selected nodes or whole canvas | "make sense of this", "take it toward X", "rewrite this card", "what's missing?" (P1) |
| Any | — | "export a notebook" / "give me this as a Jupyter notebook" opens the Export notebook dialog (§17) with the options pre-filled from the request ("without the stories" unticks Include story cards) |

---

## 11. Editing a story card

1. Click **Edit** (or double-click the card on the canvas). The card becomes an inline editor with the headline and body editable.
2. Number chips are atomic: they can be deleted or moved, not edited character by character. Typing `/` opens a picker of this card's fact-sheet values to insert a new chip.
3. Typing a number by hand creates an "unverified" chip (dashed outline) with a tooltip "Typed by you, not computed".
4. **Save** or **Cancel**. Saving marks the card as user-edited (an "edited" pencil badge).
5. Later data changes: chips update in place; the card gets a "data changed" badge with **See suggestion** (opens a side-by-side: your text vs the AI's revision, with Accept / Keep mine).

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

---

## 13. Settings overlay

Opened from the gear or `?settings=1`. A centred dialog over a dimmed app. Contents per PRD §7.10 as segmented controls. Changes apply immediately and save to the server; "Done" closes. Esc or clicking outside closes. The mode and accent switches preview live behind the dialog.

---

## 14. Left panel (library) interactions

| Action | Result |
|---|---|
| Click a row | Opens that dataset on its last tab. |
| Row menu (⋯) | Rename (inline) · Delete (confirm, then toast with Undo) · Download original CSV. |
| Status badge | profiling / offer / cleaning n% / building / ready / failed. Hover shows the last event. |
| Collapse (« / ») | Panel becomes an icon rail: dataset initials as buttons, Upload, Sample, gear. |
| Upload / Try with sample | §3. |

---

## 15. Background jobs tray

A small icon in the centre header shows the number of running jobs. Clicking lists them (cleaning, dashboard build, story updates, ML runs) with progress and **Cancel**. Completed jobs show for 1 minute. Errors stay until dismissed, with "Retry".

---

## 16. The update cascade, as the user sees it

Trigger: a save in the CSV tab, a cleaning step commit, a widget added/changed/removed, an ML result.

1. A thin progress line appears under the header: "Updating 4 widgets and 3 stories".
2. Affected widgets dim and show "updating"; others are untouched.
3. Affected ML widgets show "Outdated · Re-run" (or re-run automatically).
4. Story cards update one by one; each gets the "changed" badge (or "outdated, click to refresh" in Ask-first mode).
5. The progress line disappears. A toast summarizes: "v8: 4 widgets re-queried, 3 stories updated."

The cascade is debounced: multiple saves within 2 seconds produce one cascade.

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

### 17.2 The dialog

Title "Export notebook". Body:
- One line: "A runnable Jupyter notebook that rebuilds **titanic3.csv v7** from the raw file: 6 steps, 8 widgets, 2 model runs, 9 story cards."
- Options (checkboxes, remembered per user): **Include data** (raw CSV next to the notebook; default on) · **Include story cards** (on) · **Include canvas notes** (off) · **Include ML runs** (on).
- Order (segmented): **Steps, then dashboard order** (default) · **Flow reading path** (P1; disabled with "Order the canvas first" until a path exists).
- A note when a cleaning or ML job is running: "A job is still running. This export uses v7, the latest committed version."
- A note when pending edits exist: "You have 12 unsaved edits. They are not included; save first to include them." with a **Save and export** button.
- Footer: Cancel · **Export** (primary).

### 17.3 Flow

1. Export → the dialog closes; a toast "Preparing notebook…" with a progress bar (job in the tray).
2. On completion the browser downloads `titanic3-v7.ipynb` and, if ticked, `titanic3-raw.csv` (two downloads; on browsers that block the second, the toast offers a link). The toast becomes "Notebook ready" with **Download again** for 1 minute.
3. A repeat export with nothing changed (same version, same dataset state, same options) downloads instantly from the cache.

### 17.4 What's in the file, in order

1. Title and provenance (Markdown): dataset name, version, export time, Sherlock version, "every number below was computed by code".
2. Parameters (code): `DATA_PATH = "titanic3-raw.csv"`, `RANDOM_SEED = 42`.
3. Requirements (code, pinned `pip install` line).
4. Helpers (code): the vendored cleaning helpers used by any step in this notebook (only those).
5. Load (code): decode the raw file with the recorded encoding into a UTF-8 copy in the working directory, then DuckDB's `read_csv` with the recorded delimiter, header and skip options and `all_varchar`, the same reader, `_row_id` expression and empty `_quarantine_reason` column the app uses, then `.df()`.
6. Overview (Markdown): the overview card.
7. For each step in the current version's effective chain (undone steps left out), in order: a Markdown cell (step number, summary, gate, decision, impact line) and a code cell (the stored pandas for cleaning steps, or the stored DuckDB statement for the typing step, ending in `df = result`; generated pandas assignments by `_row_id` for edit batches). An undo appears only as a Markdown note. A final assertion cell checks row count and columns against the version.
8. For each widget in dashboard order: Markdown (title), code (DuckDB SQL on the DataFrame → table, output embedded), code (matplotlib chart), then its story card as Markdown. ML widgets get their run's reproduction cell and its importance or coefficients table instead of the SQL and chart cells.
9. For each ML run: Markdown (what and why, excluded columns with reasons), code (reproduction), output tables embedded; its story card.
10. Synthesis and direction cards after their sources; canvas notes where they sit in the Flow path (when that order is chosen).
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
| LLM returns invalid JSON | One repair retry; then the pipeline step is skipped (cleaning) or the answer falls back to the raw results table (chat). Logged. |
| SQL from the model fails | One repair retry with the error; then "I couldn't build a working query for that." |
| Sandbox timeout (30 s) | The candidate fix is discarded; the issue is skipped with "took too long". |
| Browser offline | A banner "You're offline. Edits are kept locally." Pending edits persist in local storage; Save retries when back online. |
| Session cookie cleared | The library appears empty. There is no recovery (documented in the README and the empty state's small print). |
| Dataset expired (7 days) | Removed from the library; opening a stale link shows "This CSV expired." |
| Two tabs open on the same dataset | Both receive cascade events (SSE); pending edits are per tab; a save in one tab makes the other show "A new version exists. Reload to see it." |
| Wide file (> 30 columns) | Auto-dashboard uses the 30 most interesting columns; a note says so. The grid shows all. |
| No numeric columns | Dashboard shows counts and top-value charts; ML options are disabled with reasons. |
| Tiny file (< 100 rows) | Dashboard builds; supervised ML refuses with the row count needed; stories mention the small sample. |
| All-text file | Profiling detects free-text columns; the dashboard shows top values and lengths; chat can search text. |
| Column with no values | Profiling types it `empty`; it stays in the data, is flagged in the data card, and is left out of widgets, targets and features. |
| Page reloaded while a chat answer streams | The server finishes the answer and saves it; after the reload the thread shows the completed reply. |
| Header not on the first row | The import preview's header-row control fixes it; auto-detection tries the first 5 rows. |
