# Day 5 review: the CSV tab

Reviewed 2026-10-25 on branch `claude/review-day5-47e176`, cut from `main` at 8c96ca3. The scope is Implementation Plan §2 "Day 5 · Oct 24", as cut 5 in the §2.0 table narrows it. "Done" means plan §1: it runs on the Titanic sample, its test passes, the UI reaches it, and it's committed. The plan marks Day 5 "Done 2026-10-25, within cut 5"; this review checked that claim item by item.

**Verdict.** The Day 5 exit check passes in a real browser on Titanic. Edits and a new row saved as v5, the dashboard re-queried, the step showed in Changes with Undo, and the undo made v6 with v4's data. The exported notebook then rebuilt v6 exactly in a fresh venv. The harder case also passed: undoing an earlier Cleaner step replayed the later one into v7, and the v7 notebook rebuilt v7 exactly. `sherlock eval notebook --sets all` rebuilds 5 of 5 files, four of them not Titanic (Rule 4). Rule 3 holds: undo and restore make new versions, and no Parquet file is rewritten.

This review found six bugs outside the locked files and fixed each in its own commit with a test (see **Commits**):

1. With one pending edit, the grid drew a whole column's text in the accent colour.
2. The export dialog's counts went stale, because every preview after the first was a `422`.
3. Ctrl+Shift+E did nothing while the CSV grid had focus.
4. The export dialog dropped the server's notes.
5. The notebook's secret scan couldn't recognise a Token Factory key.
6. "Clean the new rows on save" skipped the LLM rate bucket.

Open findings needing the owner:

- **Type-aware editors are missing.** PRD CSV-5 is P0, and cut 5 doesn't remove these editors (O1).
- **No "Export up to step k".** App Flow §17.5 promises it when an export fails, but there is no frontend for it (O2).
- **The pending-edits guard has no Save button.** App Flow §8.4 says the guard offers Save and Discard; it offers only Discard (O3).
- **No component or end-to-end tests** cover the Save, conflict and Undo UI (O4).

## Evidence

| Check | Result |
|---|---|
| `uv run pytest` (api) | **First run: 340 passed, 3 skipped, 4 failed.** That run took 18 min while the notebook eval, a live clean and a fresh-venv notebook run shared the machine. The 4 failures were `test_cleaner::test_clean_commits_steps_reports_and_builds`, `test_notebook::test_export_runs_and_rebuilds_the_version_after_an_undo` and two `test_stories` cascade tests. All were `wait_for` timeouts, or a polling helper reading an error envelope as a job list. **The 4 rerun alone: 4 passed** (2 min 22 s). **Full rerun after the fixes, on a quiet machine: 345 passed, 3 skipped, 1 failed** (11 min 36 s). The failure was `test_openapi`: the docstring added in 8d14888 is the route's OpenAPI description. 152448c regenerated `openapi.json` and `schema.d.ts`, and `test_openapi` then passed. |
| `pnpm test` (web, vitest) | **Before: 8 files, 53 passed. After: 10 files, 61 passed** (8 new tests). `tsc -b` is clean. |
| `uv run sherlock eval notebook --sets all` | **5 of 5 rebuild their version in a fresh venv.** titanic3.csv: 2 steps, 8 widgets, 181 s. sales_dated.csv: 2 steps, 8 widgets, 180 s. wide_messy.csv: 2 steps, 6 widgets, 252 s. reviews_text.csv: 2 steps, 6 widgets, 133 s. broken_latin1.txt: 2 steps, 6 widgets, 142 s. Each file gets two edit batches (cells, a new row, a deleted row), and the first is undone, which replays the second. |
| Browser exit check, Titanic, live | **Passed.** API on :8105, Vite on :5185, opened as `http://review5.localhost:5185` so the cookie doesn't clash with sibling sessions. Steps and screenshots are below. |
| Notebook after the undo, fresh venv | **v6 notebook:** 54 cells ran, and the assertion cell printed "Rebuilt version 6: 1,309 rows × 14 columns". `pandas.testing.assert_frame_equal` against `v4.parquet` (v6's file) passed, dtypes included. **v7 notebook** (after an undo with replay of Cleaner step 3): 53 cells ran, and it is frame-equal to `v7.parquet`. The v7 venv had only `nbclient` and `ipykernel` before the notebook's own `%pip install` cell ran. |
| Non-Titanic export (Rule 4) | Covered by the eval row above: four non-Titanic files, each with edits, an undo with replay, and a fresh-venv run. A second live dashboard build wasn't spent on it. |
| Rule 3 (data never changed in place) | `versions` after the check: v6 points at `versions/v4.parquet` (undo of the latest step, no file written), and v7 is a new `versions/v7.parquet` (replay). The mtimes of v1–v5 didn't change. Hand-deleted rows are a real deletion in the *new* version only. The step can be undone, and the summary says "deleted … by hand". |

### Exit check, step by step (Titanic)

| Step | Result | Screenshot |
|---|---|---|
| Try with sample, then Clean it for me (live) | The clean committed steps 1–3: typing, age median by title, pclass and sex (263 cells), fare by pclass (1 cell). The dashboard built itself on v4 with 9 widgets. | `day-5/01-cleaning.jpg`, `day-5/02-dashboard-v4.jpg` |
| CSV tab | The paged grid shows the header's type, "n% missing" and a mini histogram. Changed cells (age, row 16) have the tint and the top line. The legend and the Changes panel with three steps are present. | `day-5/03-csv-tab-v4.jpg` |
| Edit cells and add a row | Edits: row 1 age 29 → 31, row 4 age → `abc` (it fits no type, so it gets the red underline), row 2 sex → `Male`, and a new row (pclass 3, a name, age 44). "4 unsaved changes" shows, and the Unsaved (yours) list has a × on each line. **The buffer survived a reload.** The accent-coloured column text in this shot is the bug fixed in 46de486. | `day-5/04-pending-after-reload.jpg` |
| Save | **v5**, step 4 "Edited 3 cells, added 1 row by hand", 1,310 rows. Row 4 age is saved blank and marked invalid. The toast offered "Run cleaning on the 1 new row?"; it wasn't clicked, to save spend (covered by a test). For a moment the grid showed v4's rows under the v5 header (O6). | `day-5/05-saved-v5-stale-grid.jpg`, `day-5/06-saved-v5-cascade.jpg` |
| Widgets re-query (cascade) | "Updating 9 widgets and 9 stories". After it, all 9 widgets have `version_built = 5`, the passengers KPI reads 1,310, and the cards carry "changed". | `day-5/07-dashboard-v5.jpg` |
| Step in Changes with Undo | Expanded, step 4 shows its edit list (the three cells and "Added row 1310") and "1,309 rows in, 1,310 out · 3 cells changed". | `day-5/08-changes-step4.jpg` |
| Undo step 4 | No confirmation, as specified: it's the latest step and not typing. The result is **v6** with 1,309 rows, row 1 age 29 and row 2 "male". Step 4 is struck through as "undone", and step 5 reads "Undid step 4 …". | `day-5/09-undo-v6.jpg` |
| Export notebook | The dialog opened with Ctrl+Shift+E (focus outside the grid, see fix 3): "rebuilds titanic3.csv (sample) v6 from the raw file: 3 steps, 8 widgets, 1 model run, 10 story cards". The loading toast became "Notebook ready" with Download again. The server log shows `GET /exports/{id}/download` and `GET /raw.csv`, both 200. The `exports` row is done with `counts {steps 3, widgets 8, runs 1, cards 10}`. | `day-5/10-export-dialog-v6.jpg`, `day-5/11-notebook-ready.jpg` |
| Extra: undo with replay | Undo step 2 asked "This undoes step 2 and replays the later steps still in effect (step 3)…". The result is **v7**: age is 20.09% missing again, and step 6 reads "Undid step 2 … (replayed step 3)". Exported, then rebuilt in a fresh venv (above). | `day-5/12-undo-replay-confirm.jpg`, `day-5/13-undo-replay-v7.jpg` |
| Find, Clean with AI guard | Find "Allison" gives "4 matches in 4 rows; only those rows are shown". With a pending edit, Clean with AI shows "Save or discard your 1 unsaved change first", Start is disabled, and only Discard is offered (O3). | `day-5/16-find.jpg`, `day-5/15-clean-guard.jpg` |

## Status by item

| Item | Status | Evidence |
|---|---|---|
| **D5.1** Paged Glide grid, header type, missing share, mini histogram, the changed, flagged, invalid and unsaved marks | **done** (one bug fixed here) | `Grid.tsx` loads 200-row pages as they scroll into view (`load` at `:87`, `onVisibleRegionChanged` at `:313`) and draws the header in `drawHeader` (`:200`). Marks come from `lineage.cell_marks` (`steps/lineage.py:62-79`), plus the buffer. Seen live. **Fixed:** the unsaved mark leaked the accent fill into Glide's cached context, so a column's later cells drew accent text (46de486; before: `04-pending-after-reload.jpg`, after: `17-marks-fixed.jpg`). The legend has no "invalid" entry, though App Flow §8.1 lists only three marks, so this matches. |
| **D5.2** Cell edits with type-aware editors, add row, delete row, local-storage buffer, Save with conflicts (Rebase and save, keep mine or theirs), Discard | **partial** | Edits, add and delete row, the buffer (`state/edits.ts`, key `sherlock:edits:<ds>:<base>`, which survived a reload live), Save, Discard with confirmation, and the conflict dialog (`SaveActions.tsx:27-66, 102-149`) are all there. The server diff is `rows/edits.py:182-224`, tested by `test_rows.py::test_stale_base_version_lists_conflicts`. **Type-aware editors are missing:** every cell uses Glide's text editor (`getCellContent`, `Grid.tsx:149`), with an invalid underline. App Flow §8.2 documents that as built, but PRD CSV-5 (P0) and plan D5.2 ask for a category dropdown, number validation, a boolean toggle and a date picker, and cut 5 doesn't remove them (O1). The conflict UI wasn't exercised live, and no frontend test covers it (O4). |
| **D5.3** Find, Clean with AI (whole dataset, selection, new rows, the pending-edits guard), the Download menu | **done** (gaps O3, O9) | Find uses `GET /find?all=true`, then a selection (`runFind`, `CsvTab.tsx:55`); seen live. The popover's three scopes call `POST /clean` (`api/csv.ts:120-131`), and the server resolves scopes in `cleaning/loop.py:150-184`. The guard was seen live (Discard only, O3). The Download menu (`CsvTab.tsx:97-105`) offers CSV (`export.csv`, with formulas escaped) and Notebook. |
| **D5.4** Changes panel: unsaved lines, steps with code or edit list, impact and decisions, Undo with the replay and typing confirmations, `409` handling | **done** | `ChangesPanel.tsx`. Seen live: the edit list, the impact line, the replay confirmation, undone steps struck through. Code shows in a plain mono block (no Shiki, as the plan's as-built note says). On a failed replay, the `409` reason shows as a toast (`:139`); covered by `test_replay.py::test_a_replay_that_cannot_apply_changes_nothing`. The typing warning is in the code (`:164`) and `test_steps.py` but wasn't clicked live. |
| **D5.5** Backend undo with replay, `user_edited_cells`, "Run cleaning on the n new rows", cascade v0, debounce | **done** (one gap fixed) | Undo is `steps/undo.py`, replay is `steps/replay.py`; seen live, including a sandbox replay of a Cleaner step. `user_edited_cells` is written in `commit.py:181-185` and re-protected on undo (`_reprotect`, `undo.py:127, 149`). Clean on save: the save toast's "Clean them" uses `/clean` with `new_rows`. The API flag `run_cleaning_on_new_rows` is in `routers/rows.py`. **Fixed:** that flag queued a model job without the LLM bucket (8d14888). The cascade (`jobs/cascade.py`) is now D6.2's column-level cascade with the 2 s debounce. A row-count change re-ran all 9 widgets live, which meets v0. |
| **D5.6** Notebook export v0: cells, routes, `exports` table, cache, the execution test, the dataset menu, Download menu entry, dialog, progress toast, Ctrl+Shift+E, and no secrets | **done** (four fixes here; O2 open) | The cells are `notebook/cells.py`, `exporter.py`, `vendored_helpers.py` and `scan.py` (locked files read, not edited). The routes are `routers/exports.py`; the table matches Schema §2.19; the cache key is `sha1(version, state_rev, options)`. The execution tests are `test_notebook.py` and the eval. The frontend entry points are `DatasetMenu.tsx:110`, `CsvTab.tsx:103` and `ChangesPanel.tsx:46`, plus Ctrl+Shift+E and `?export=notebook`. **Fixed:** the preview `422` loop (b49893b), Ctrl+Shift+E from the grid (c1e0b2a), the dropped notes (50729db), and the scan missing Token Factory keys (1845c9c). **Secrets (Rule 6):** the notebook holds no cookie, user id, dataset id or prompt. Its code is stored step code, compiled widget SQL and run `repro.py`, and the model never sees the key. The scan (`scan.py`) now refuses the configured key's value anywhere in the file. |
| **D5.7** Restore for quarantined rows | **done** (not seen live) | `CsvTab.tsx:53, 90-94` (shown when the selection includes quarantined rows). Server: `rows/edits.py:146-148`, as a new version with the summary "Restored n rows by hand". Covered by `test_rows.py::test_restore_quarantined_row`. The live clean quarantined no rows, so the UI path wasn't clicked. |
| **Exit check** | **passed** | See above. Both the plain undo (v6) and the undo with replay (v7) rebuild exactly in a fresh venv. |

### What cut 5 removed that a P0 still names

These are cut, so they aren't counted as missing. They stay P0 in the PRD, so the PRD and the cut table disagree until the owner records the drop:

- **CSV-2:** the hover `old → new (step n)` tooltip.
- **CSV-3:** Ctrl+arrow and jump to row number. Glide's arrows, Tab and Enter work.
- **CSV-4:** the selection stats (count, sum, mean, min, max).
- **CSV-6:** TSV copy and paste, and fill down.
- **CSV-7:** add above or below, and duplicate.
- **CSV-9:** replace.
- **CSV-10:** column filters and the changed, flagged and missing quick views. The API supports `view=` and `filter=`; the UI doesn't use them.
- **CSV-11:** buffer undo/redo and the Review changes drawer.
- **CSV-14:** right-click menus.

## Findings, ranked

"Locked" marks a file with the owner's uncommitted Day 8 work. This review found no defect that needs a change in a locked file.

### Fixed on this branch

- **F1 (medium, fixed in 46de486). One pending edit recoloured a whole column.**
  - What happened: `Grid.tsx` drew the unsaved mark by setting `ctx.fillStyle` and `ctx.strokeStyle` to the accent and never restoring them. Glide caches the styles it set, so every later cell in that column drew its text in the accent colour.
  - Seen live: the age and sex columns turned teal after one edit each.
  - Why it matters: it reads as a mark those cells don't have (UI/UX §4.7).
  - The fix: all marks now go through `drawMarks`, which saves and restores the context.
- **F2 (medium, fixed in b49893b). The export dialog's counts went stale.**
  - What happened: the preview answers its options with `up_to_step: null`, and the dialog sent that back as `up_to_step=null`, which is a `422`.
  - Effect: after the first preview, toggling an option never updated the counts, and reopening the dialog lost them ("…v7 from the raw file." with no counts; `14-export-dialog-no-counts.jpg`).
- **F3 (low, fixed in c1e0b2a). Ctrl+Shift+E didn't work in the CSV grid.**
  - What happened: Glide stops the keys it handles from bubbling, and the shortcut listened in the bubble phase. On the CSV tab focus is usually in the grid, so the shortcut did nothing there.
  - App Flow §17.1 says "any tab". After the fix it works from the grid (`18-shortcut-from-grid.jpg`).
- **F4 (low, fixed in 50729db). The export dialog dropped the preview's notes.**
  - What happened: the dialog ignored the `notes` that TRD §4.2 says the preview returns for it. With no story cards yet, it drew an empty warning box.
  - App Flow §17.2 now has an as-built line for this.
- **F5 (medium, fixed in 1845c9c). The secret scan couldn't recognise a Token Factory key (Rule 6, PRD NB-11).**
  - What happened: `scan.py`'s pattern catches `sk-…`, `LLM_API_KEY` and bearer tokens. The configured Token Factory key starts `v1.` and wouldn't match, and the scan read cell sources only.
  - No path that puts the key into a notebook was found: the model never sees it, and no cell reads the environment. This hardens the guard.
  - The scan now also refuses the configured `LLM_API_KEY` and `TAVILY_API_KEY` values anywhere in the file: sources, outputs and metadata. Added to TRD §7.7.
- **F6 (low, fixed in 8d14888). Clean-on-save skipped the LLM rate bucket.**
  - What happened: `POST /edits` with `run_cleaning_on_new_rows` queues a clean, which calls the model, without the 10-per-minute LLM bucket that `POST /clean` has.
  - This is the same class as the Day 1 note about job routes that skip the bucket. The UI doesn't send the flag (it calls `/clean`), so only direct API calls hit it.
  - Added to TRD §4.3 as built.

### Open

- **O1 (high for P0 coverage). Type-aware editors are missing (PRD CSV-5 P0, plan D5.2).**
  - What happens: every cell edits as text. There is no category dropdown (`GET /columns/{col}/values` exists for it), no boolean toggle, no date picker, and no number validation beyond the after-the-fact underline.
  - Cut 5 doesn't remove these editors. App Flow §8.2's as-built line documents the text editor, so the docs agree with each other but drop a P0 behaviour outside the cut order.
  - Needs the owner: build them, or record the drop (Rule 5, plan §2.0: "any further drop needs a PRD change").
- **O2 (medium). No "Export up to step k" on a failed export (App Flow §17.5).**
  - What happens: `runExport` shows the error as a toast only (`ExportDialog.tsx:68`). The backend supports `up_to_step` (`exporter.py:_chain`, preview and tests), but nothing in the UI offers it.
  - No as-built line says so, so the docs and the code differ.
  - Fix: add the toast action, or an as-built note.
- **O3 (low–medium). The pending-edits guards lack their Save buttons.**
  - App Flow §8.4 says the Clean with AI note comes "with both buttons". Only Discard is there (`CsvTab.tsx:246-253`), with no as-built note.
  - The export dialog's "Save and export" is missing too, but App Flow §17.3 records that as built.
  - Small UI gaps in the same popover:
    - The scope labels have no counts: "Rows added since the last clean" has no "(n)".
    - "Current selection (1 rows)" doesn't singularise.
    - `ChangesPanel.tsx:112` shows "1 cells".
- **O4 (medium). No UI tests for the Save, conflict and Undo flows.**
  - Web tests cover the buffer and `fitsType` (`csv.test.ts`), plus this review's mark and export dialog tests. `SaveActions`, `ConflictDialog`, `ChangesPanel` and `CsvTab` have no component test. There is no Playwright flow either (Day 4's F9).
  - The conflict dialog ("Rebase and save", keep mine or theirs) was checked only by reading the code: no browser session made a concurrent commit.
- **O5 (low). "Keep mine" on a row the newer version deleted can't be saved.**
  - What happens: the conflict list includes it (`theirs: null`). Keeping mine resends the edit, and `_check_ids` answers `422 "rows: row N doesn't exist in this version"`.
  - The buffer then can't be saved until that line is removed by hand. The same happens for a pending delete or restore of a row that's gone.
  - Read from the code, not run.
- **O6 (low). A brief stale grid after Save.** For about a second after the save, the grid showed v4's rows (1,309, old values) under the v5 header, then reloaded (`05-saved-v5-stale-grid.jpg` → `06-…`). The header and the grid change version at different moments.
- **O7 (low). Select-all reports a delete count for loaded rows only.**
  - What happens: after Ctrl+A, the toolbar offered "Delete 200 rows" while the status bar said 18,326 cells. `onSelectionChange` only counts rows whose page is loaded (`Grid.tsx:259`).
  - Range selection is cut (cut 5), but Glide still allows it, so a big select-all marks only the loaded rows for deletion.
- **O8 (low). The undo confirmation omits the same-column count.** App Flow §8.5's text says "2 later steps touch the same column and will be re-run". The dialog names the steps to replay but not which ones touch the same columns.
- **O9 (low). Find shows at most the first 10,000 matches' rows.** `FIND_ALL = 10_000`. Past that, the bar's "N matches in R rows; only those rows are shown" is true only of the rows in those first 10,000 matches. Fine for the sample.
- **O10 (low). An invalid edit reads as if its text was kept.** The step's edit list shows "Row 4 · age → abc" for a value saved as blank and flagged invalid. A "(invalid, saved blank)" hint would match App Flow §8.2.
- **O11 (low, test flakiness). Tests time out under load.**
  - `wait_for` polls (`tests/test_jobs.py:36`) timed out when the suite shared the machine with the eval and a live clean.
  - The stories helper then iterated an error envelope as if it were a job list ("string indices must be integers"), likely a `429` from polling longer. All 4 pass alone.
  - Fix: assert the status code inside those helpers.
- **O12 (note). The plan's as-built claim overstates D5.2.** "Done within cut 5" is accurate except for O1, which cut 5 doesn't cover.

## Commits on this branch

| Commit | What | Test | Doc |
|---|---|---|---|
| 1845c9c | `notebook/scan.py`: refuse the file if the configured `LLM_API_KEY` or `TAVILY_API_KEY` value appears anywhere in it | `test_notebook.py::test_scan_refuses_a_configured_key_anywhere_in_the_file` | TRD §7.7 |
| 50729db | `ExportDialog.tsx`: list the preview's notes, leaving out its running-job note | `export.test.tsx` "shows the preview's notes…" (fails before, passes after) | App Flow §17.2 as built |
| 8d14888 | `routers/rows.py`: `run_cleaning_on_new_rows` counts against the LLM bucket | `test_rows.py::test_cleaning_new_rows_on_save_uses_the_llm_bucket` | TRD §4.3 as built |
| 46de486 | `Grid.tsx`: every mark draws through `drawMarks`, which saves and restores the context | `grid.test.tsx`, 5 marks; seen live before and after | none (restores UI/UX §4.7) |
| b49893b | `ExportDialog.tsx`: unset options are left out of the preview query | `export.test.tsx` "asks the preview again…" (fails before, passes after) | none (restores TRD §4.2) |
| c1e0b2a | `ExportDialog.tsx`: Ctrl+Shift+E listens in the capture phase | `export.test.tsx` "opens with Ctrl+Shift+E even when the focused element stops the key" (fails before, passes after); seen live | none (restores App Flow §17.1) |
| 152448c | `web/src/api/openapi.json` and `schema.d.ts` regenerated for the `POST /edits` description changed in 8d14888 | `test_openapi.py` (failed after 8d14888, passes now) | none |

Nothing is pushed or merged.

## Token Factory spend for this review

From the live run's `llm_calls`:

| Run | `llm_calls` | Prompt tokens | Completion tokens |
|---|---|---|---|
| Live clean (one) | 14 | 12,137 | 15,181 |
| Dashboard build (one) | 1 | 907 | 1,679 |
| Stories after the build | 19 | 13,390 | 29,459 |
| Cascades after v5, v6 and v7 (cards narrated again) | 23 | 12,852 | 32,492 |
| **Total** | **57** | **39,286** | **78,811** (118,097 in all; 2 repairs, 0 failures) |

`eval notebook` and the test suites ran with the model off.
