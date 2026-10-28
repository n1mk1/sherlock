# Plan: type it, see the code, press OK, see the CSV change

**Status:** built. Code: `api/sherlock/agent/commands.py` (commands), `agent/analysis.py` (`ask_code`), `steps/undo.py` (`history`, `quick_undo`, `redo_step`), the card in `web/src/components/shell/ChatBar.tsx` and the buttons in `web/src/components/csv/CsvTab.tsx`. Two choices made while building: a request to delete rows becomes a command whose code sets the rows aside (it used to be refused), and a command that sets aside more than a fifth of the rows shows a warning on the card instead of being refused, since the user sees the count before OK.

**The loop:**

```
you type a command ──► Nemotron writes pandas code ──► card shows the code + a preview
        ▲                                                      │
        │                                                   [ OK ]
        │                                                      ▼
   keep going  ◄──── like it? ────  grid jumps to the new CSV, changed cells highlighted
                        │
                     don't like it
                        ▼
              [ ↶ Undo ]  [ ↷ Redo ]   up to 3 states back, and forward again
```

Works any time a CSV is loaded: grid open, rows selected, cleaning plan open, even while a clean is running (§5).

---

## 1. Queries vs commands

**Queries run on DuckDB, commands run on pandas.**

| | Query: "average fare by class" | Command: "trim the spaces in name" |
|---|---|---|
| Code | SQL that Nemotron writes, checked by sqlglot (read-only, one `SELECT`) | pandas that Nemotron writes, checked by `sandbox/static_check.py` |
| Runs on | In-memory DuckDB over the version's Parquet file (`query/execute.py`) | The sandbox subprocess: `df` in, `result` out, no network, CPU and memory caps |
| Changes the CSV | Never | Yes: a new version, undoable |
| Needs OK | No. It's read-only, so it answers straight away, and the SQL is under "How do you know?" | **Yes.** Nothing changes until you press OK |
| You see | Numbers as chips, a table or a chart in chat; "Show these rows" filters the grid (view only) | The updated grid |

Queries stay on DuckDB because it's fast on large files, a read-only `SELECT` can't damage anything, and every number already traces back to the SQL. The other option is to make queries pandas too, with an OK. That costs a click per question, needs a sandbox run each time, and doesn't make the answers safer.

### 1.1 Every kind of question, and what answers it

"Query" covers more than SQL. The router (`agent/prompts.py::INTENT_LINES`) sends each question to the engine that fits:

| Question | Intent | Engine | Built |
|---|---|---|---|
| Counts, totals, averages, rates, group-bys, top-N, trends, percentiles, filters, joins of a column to itself, window functions | `ask_data` | DuckDB SQL | yes |
| "Which / who / show / list …" rows | `find_rows` | DuckDB SQL, then the grid | yes |
| "Is X significantly different between A and B?", correlation, p-values | `ask_stats` | DuckDB reads, scipy runs the test (Pearson/Spearman, Welch t, Mann-Whitney, Kruskal, chi²) | yes |
| "What drives X?" | `ask_why` | scikit-learn driver analysis (permutation importance) | yes |
| "How accurate is the model?" | `ask_model` | stored model runs | yes |
| "What did cleaning change?" | `ask_history` | the step history in SQLite | yes |
| "What does column X mean?" | `ask_meaning` | DataCard, data dictionary, web | yes |
| Outside-world questions | `web_context` | Tavily | yes |
| "How do I …" in the app | `app_help` | help pages | yes |
| **Anything SQL can't express**: a regression, clustering, a custom statistic, text processing beyond regex (fuzzy matching, tokenising), reshaping beyond `PIVOT`, multi-step calculations | **`ask_code` (new)** | **pandas + numpy + scipy + scikit-learn in the sandbox, read-only** | **no, slice 9** |

Today a question in the last row gets an honest "I can't answer that". The new `ask_code` path covers it:

- Nemotron writes pandas analysis code. The sandbox runs it on a copy of the current version and returns a result table, never a new version.
- It needs no OK, because nothing is saved. The code is shown under "How do you know?", like the SQL is.
- Numbers come from the result table as chips, and a result can be shown as a table or a chart, like `ask_data`'s.
- It's tried when the router picks it, and also when `ask_data` can't write working SQL after its repair, but only when the reason is "SQL can't express this". When the reason is "no column records this", the answer stays an honest "can't", because pandas can't conjure missing data.

## 2. What exists and what's missing

- **Exists:**
  - Queries (`ask_data`, `find_rows`).
  - Cell edits by row number (`edit_cells`).
  - The sandbox, the verifiers, `commit_step`.
  - Undo of any step from the Changes panel, as a new version (`steps/undo.py`).
- **Missing:**
  - Column-wide commands as pandas code with OK (`clean_step`).
  - Showing the code before running it.
  - Jumping the grid to the result with the changes highlighted.
  - Undo/Redo buttons. There's no redo anywhere today.

## 3. The command card

```
you:  remove the extra spaces in name and make city title case

┌ Trim spaces in name, title-case city ────────────────────────┐
│ result = df.copy()                                             │
│ result["name"] = result["name"].str.strip()                    │
│ result["city"] = result["city"].str.title()                    │
│                                                                │
│ 412 cells in 398 rows · name, city                             │
│  row  column  now                after                         │
│  12   name    "  Allen, Miss "   "Allen, Miss"                  │
│  40   city    "new york"         "New York"                     │
│ ✓ no rows lost  ✓ no new blanks  ✓ types kept                  │
│                                         [ Cancel ]  [ OK ]     │
└────────────────────────────────────────────────────────────────┘
```

- The code is shown open, not hidden. It's what will run.
- The preview comes from a dry run in the sandbox on a copy, so you see the real effect before you press OK. The numbers are written by code, never by the model.
- If the dry run fails a check (drops rows, blanks out values, fills with "Unknown"), Nemotron gets one try to fix its code with the error. If it still fails, you get "I can't do that safely: <reason>" and no OK button.

**OK:**
1. Runs the code on the CSV as it is right now and saves a new version. Nothing is overwritten; every version is kept.
2. The grid jumps to the new version and highlights the changed cells for a few seconds.
3. The card reads "Done · v8 · [Undo]".

If the CSV changed between the preview and OK, the code runs on the new state anyway. If the effect differs from the preview, the card refreshes ("Re-checked: now 415 cells") and you press OK once more.

## 4. Undo and Redo

Two buttons in the CSV toolbar, plus Ctrl+Z / Ctrl+Y:

- **Undo** goes back one CSV state, at most **3** in a row. The 3 is a setting (`UNDO_DEPTH = 3`).
- **Redo** goes forward again through the states you undid.
- A new command after an undo clears Redo, the usual editor rule.
- Each button's tooltip says what it does: "Undo: trim spaces in name (v8 → v7)".
- Every step counts: chat commands, hand edits saved from the grid, and the Cleaner's steps.

**How it works without deleting anything.** A version is a list of steps (`effective_step_ids`), so going back and forward is cheap:

- **Undo** makes a version whose list is one step shorter. When that version already exists, it points at the existing file and rewrites nothing. This is today's `undo_step` on the latest active step.
- **Redo** makes a version whose list has the undone step back. That version always exists (it's the one you undid), so redo also points at an existing file and copies nothing.

**Server.** A `GET /datasets/{id}/history` call returns `{ undo: { step_id, summary, to_version } | null, redo: … | null, depth_left }`. `POST /datasets/{id}/undo` and `POST /datasets/{id}/redo` both take `base_version`. Redo is a new `redo` step kind with a `redone_step_id`, saved as an `undo`-style step so the Changes panel and the notebook list it.

**Changes panel.** It keeps undoing any step, however old. The 3-deep buttons are the quick path, and the panel is the full history.

## 5. Any time a CSV is loaded

| State | A command |
|---|---|
| Grid open, idle | Card, OK, grid updates |
| Cells or rows selected | Applies to those rows only (`keep_outside_scope`); the card says "on 40 selected rows" |
| Cleaning plan open, not started | OK saves now, and Start cleaning runs on the newer version. "Change the plan" messages still edit the plan |
| Cleaning job running | OK puts it in a queue ("Waiting for cleaning to finish"), and it runs when the job ends or is stopped. Undo/Redo are disabled while the job runs |
| Unsaved grid edits | OK asks to save or discard them first |
| Profiling or failed | Chat bar disabled; there's no data yet |

## 6. Slices

Each slice is tested, committed and pushed on its own.

### Slice 1: the command, the code and the dry run (backend)
- `llm/schemas.py`: `StepDraft { reading, columns, new_columns, code }`.
- `agent/prompts.py`:
  - A `clean_step` intent: change values in a column, or in every row that matches a condition.
  - A `STEP` prompt: the DataCard, sample values of the target columns, the sandbox's cleaning helpers, and the rules (keep every row and `_row_id`, quarantine rather than delete, touch only the columns named, leave the answer in `result`).
- `agent/actions.py::propose_step`:
  - A `medium` call, then `sandbox.execute` on a copy of the current version, `diff_versions` and `verifiers.verify(requested=True)`.
  - One repair call on a failure.
  - A preview written by code.
  - Saved as a `clean_step` proposal holding the code.
- `agent/loop.py`: add `clean_step` to `TOOLS`. Route guard: rows named by number go to `edit_cells`, and a rule over a column goes to `clean_step`. "Delete rows" is still refused.

### Slice 2: OK runs it
- `actions.approve`, `clean_step` branch:
  - Rerun the stored code on the current version and verify again.
  - If the effect matches the preview, call `commit_step(kind="clean", created_by="chat", gate="user", code, notebook_code)`.
  - If it differs, refresh the card.
- A `clean_step` proposal doesn't expire when the version moves on.

### Slice 3: the card and the grid jump (web)
- `components/shell/ChatBar.tsx`: the card shows the code (open), the preview table, the check results and **Cancel / OK**. Its states: pending, re-checked, waiting for cleaning, done with Undo, cancelled, couldn't run.
- On `version.created` from an OK, `CsvTab` loads the new version and highlights the changed cells, using the step's `before_after` plus the version diff, then fades the highlight out.

### Slice 4: Undo and Redo
- `steps/redo.py` with `redo_step`. It reuses `_base` and the existing-version shortcut, and adds `redo` to the step kinds. The undo side reuses `undo_step` on the latest active step.
- `routers/steps.py`: the `history`, `undo` and `redo` endpoints, with the `UNDO_DEPTH` setting in `config.py`.
- The notebook export lists redo steps like undo steps, so the notebook's result matches the CSV.
- Web: Undo/Redo buttons in `CsvTab.tsx`'s toolbar, Ctrl+Z / Ctrl+Y outside cell editing, tooltips with the step summary, and a toast "Undid trim spaces in name · now v9" that has its own Redo.

### Slice 5: selected rows
- The selection's row ids, or its predicate, go into the step through `keep_outside_scope`, in both the dry run and the stored notebook code, so replay keeps the scope.

### Slice 6: with a cleaning plan open
- With a plan open, the router sees `edit_plan` and `clean_step`. A code guard sends plan words ("don't touch", "leave out", "put back", "instead") to `edit_plan` and everything else that changes data to `clean_step`.

### Slice 7: while cleaning runs, and unsaved edits
- OK during a clean sets the proposal to `queued`, and `cleaning/loop.py::_finish` applies queued proposals in order.
- The web OK handler asks to save or discard pending grid edits first.

### Slice 8: computed columns
- "add family_size = sibsp + parch" goes through the same path with `new_columns` and `kind="computed_column"`.

### Slice 9: pandas analysis for questions SQL can't answer (`ask_code`)
- `sandbox/worker.py`:
  - Add an analysis mode. The code reads `df` and leaves `result` as a DataFrame, Series or scalar. The worker returns it as JSON (at most 500 rows × 50 columns, values as text plus types) and writes no version file.
  - Analysis mode also allows `scipy` and `sklearn` imports (`static_check.ANALYSIS_MODULES`). Cleaning mode keeps its narrower list.
- `llm/schemas.py`: `AnalysisDraft { reading, code, shape: number|table|chart }`.
- `agent/prompts.py`:
  - An `ask_code` intent line: analysis that needs Python, such as a regression, clustering, a custom statistic, fuzzy matching, or a multi-step calculation.
  - An `ANALYSIS` prompt: the DataCard, the sandbox contract, and "never invent data: if no column records it, say so".
- `agent/answerers.py`:
  - `ask_code` makes a `medium` call, runs the code in the sandbox on the current version (or the selection), with one repair on an error, and returns a `Result` like the SQL answerers do, so chips, tables, charts and "How do you know?" work unchanged. The source is `{ kind: "code", code }`.
- `agent/loop.py`:
  - Route `ask_code`.
  - When `ask_data` fails with "the SQL can't express this", try `ask_code` once before answering "can't".
  - Keep the "no column records this" checks (`money_swapped` and the rest) ahead of the fallback.
- Tests:
  - A linear regression's slope and R².
  - k-means group sizes.
  - Fuzzy-grouped name counts.
  - A question that SQL fails and code answers.
  - A "no column records this" question that still says can't.
  - Code that tries to import `os` is refused.

### Slice 10: eval and end-to-end
- `ask_questions.yaml`: commands on titanic3 and `sales_dated`, scored on the proposal's columns and impact.
- `pnpm e2e`: type a command, OK, the grid shows the change. Then Undo ×3 (the button disables after 3), Redo ×3, a new command after an undo clearing Redo, and a command typed during a clean.

## 7. Tests (`api/tests/`, recorded with `LLM_RECORD`)

- **Commands:**
  - Trim, replace a value, text to number, a fill you asked for, title-case: each previews the right impact.
  - A placeholder fill is refused, then repaired or answered with the reason.
  - Code that drops rows fails the row check.
  - "delete the rows where …" is refused in words.
- **OK:**
  - With no change since the preview, it saves.
  - After a change with the same effect, it saves.
  - After a change with a different effect, it refreshes.
- **Undo/Redo:**
  - Three undos, then the fourth is refused with `depth_left: 0`.
  - Redo brings back the exact same file (same Parquet path, no rewrite).
  - A new step clears redo.
  - Undo and redo across a hand-edit batch and a Cleaner step.
  - The notebook replays to the same data after undo and redo.
- **States:**
  - Selected rows only.
  - With a plan open, plan words go to `edit_plan` and data words to `clean_step`.
  - Queued during a clean.
  - A second fixture file, so nothing is tuned to Titanic.

## 8. Defaults (say if you want them changed)

1. Queries stay DuckDB SQL with no OK. Questions SQL can't express go to read-only pandas (`ask_code`), also with no OK, since neither changes the CSV (§1.1).
2. Undo/Redo go 3 deep in the toolbar; the Changes panel still undoes any step.
3. The code is shown but not editable on the card.
4. A command also changes cells you edited by hand, since you asked for it.
5. One command card per message.
