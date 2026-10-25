# Day 4 review: widgets, dashboard builder, chat v1, dashboard and chat UI

Reviewed 2026-10-25 on branch `claude/review-day4-efb14a`, cut from `main` at 79f07eb. The scope is Implementation Plan §2 "Day 4", as the §2.0 replan narrows it with cuts 1, 8 and 9. "Done" means plan §1: it runs on the Titanic sample, its test passes, the UI reaches it, and it's committed.

**Verdict.** Day 4 meets its exit check in a real browser, and the ask eval passed 35 of 35 live with no unsourced answers. This review found and fixed three bugs, each in its own commit with a test:

1. Row predicates and `{{rows}}` placements could OR past the quarantine exclusion.
2. A collapsed widget came back one row tall when expanded.
3. The job tray's buttons couldn't be reached by keyboard.

The most serious open finding is in a file this review may not edit. A two-valued numeric target that isn't coded 0/1 gets a "rate" KPI of 140% (finding F1, a Rule 4 problem). Also, `pnpm playwright test` doesn't exist yet, so the Day 4 flow has no end-to-end test.

## Evidence

| Check | Result |
|---|---|
| `uv run pytest` (api, after the fixes) | 281 passed, 3 skipped, 1 failed. The failure is `test_sandbox.py::test_happy_path_and_log`, which asserts that the shared system-temp `sherlock-sandbox` folder is empty. A live clean or a sibling session leaves folders there, so it isn't a Day 4 failure (F14). Before the fixes: the same failure, with all else passing. |
| `pnpm test` (web, vitest, after the fixes) | 6 files, 38 tests passed (36 before, plus 2 new). `tsc -b` is clean. |
| `pnpm playwright test` | **Missing.** There is no Playwright config, dependency or spec in `web/`. The plan inventory lists the Playwright flow test as open (D8.6), but `CLAUDE.md` lists the command as if it ran (F9). |
| `uv run sherlock eval ask`, live, run once | **35 of 35 passed**: 20 Titanic and 15 `sales_dated.csv`. 0 unsourced answers, median 11.0 s per answer. Spent 126 `llm_calls`, 113,402 prompt and 54,105 completion tokens (167,507 in all). Compose made 52 calls for 34 answers, 18 of them repairs (F8). |
| Browser exit check, live, run once | **Passed.** API on :8104, Vite on :5185 (5184 was taken). Spent 21 `llm_calls`, 19,261 prompt and 23,175 completion tokens (42,436 in all). Screenshots are in `reviews/day-4/`. |
| Second sample, not Titanic (Rule 4) | `sales_dated.csv`, uploaded from the browser, then "Use as is". The dashboard built itself with 10 widgets: total revenue, total units, return rate, revenue by product, average price by product, revenue, units and return rate over time, orders by region (ring), and return rate by region (`09-sales-dashboard.jpg`). The eval also covers 15 questions on this file. |
| Injection probes against compile and sqlglot | See D4.1. One gap was found and fixed (commit 37b79b6). |

### Exit check, step by step

| Step | Result | Screenshot |
|---|---|---|
| Upload (Try with sample) → offer | The offer shows 1,309 rows, 14 columns and 13 issues | `01-offer.jpg` |
| Clean it for me | The live log, then a report: 13 found, 2 fixed, 12 skipped, 0 rows deleted, 4 rows quarantined (`embarked` disagreements) | `02-cleaning.jpg`, `03-report-building.jpg` |
| The dashboard builds itself | 9 widgets on v4, with KPIs first (average fare, survival rate, average age, passengers), then survival by sex, fare by class, passengers by family size and survival by class | `04-dashboard.jpg` |
| Chat: "average fare by class" | The prose has chips 87.86, 21.24 and 13.30 and a three-row table. "How do you know?" shows `SELECT pclass AS class, AVG(fare) … WHERE _quarantine_reason IS NULL AND (1=1) GROUP BY pclass … LIMIT 2000`, with the reading "class → pclass, fare → fare" | `05-chat-avg-fare-by-class.jpg`, `06-chat-sql.jpg` |
| Chat: "add a chart of fare by port" | "I added Average fare by port to the dashboard", with an inline chart, Open the widget and sources. The widget is on the grid. | `07-chat-add-widget.jpg` |

## Status by item

| Item | Status | Evidence |
|---|---|---|
| **D4.1** `widgets/`: spec, compile with `{{rows}}` and the global filter, sqlglot validation, execution with caps and cache, CRUD, `/data`, `/explain`, `PUT layout`, `POST /selections` | **done** (a bypass was fixed here) | `widgets/spec.py`, `compile.py`, `execute.py`, `service.py`, `layout.py`, `routers/widgets.py`; `tests/test_widgets.py`. Probes: `DROP`, `;`-chained statements, `ATTACH`, `read_csv`, `'file.csv'`, `FROM 'x.parquet'` in a CTE or subquery, `glob()`, `duckdb_settings()`, `main.t`, `sqlite_master`, and a column-name injection in filters were all refused. Filter values become quoted literals (`'x'' OR ''1''=''1'`, `TRY_CAST('1 OR 1=1' AS BIGINT)`). `getenv` doesn't exist with external access off. **Fixed:** a predicate `a = 1) OR (1 = 1`, or `WHERE {{rows}} OR …`, `NOT {{rows}}` or a second read of `t` without `{{rows}}`, used to bring quarantined and filtered-out rows back (commit 37b79b6). |
| **D4.2** `dashboard/`: candidates (bar, line, area, KPI, table), scoring in code, curation prompt and fixture, validation, layout, the `build_dashboard` job after cleaning and after "Use as is" | **done** (F1 and F5 open) | `dashboard/candidates.py`, `scoring.py`, `builder.py`, `prompts.py`, `jobs/build.py`, `jobs/clean.py:36-41`, `routers/cleaning.py:62`; fixture `tests/fixtures/llm/dashboard_curate.json`. Seen live both after cleaning (Titanic) and after "Use as is" (sales). |
| **D4.3** `agent/` v1: route → `ask_data` / `find_rows` / `explain_widget` / `ask_history` → compose → verify, `create_widget`, streaming chat, chips bound to cells, eval v0 | **done** (F6, F7 and F8 open; suggested questions are cut 9) | `agent/loop.py`, `answerers.py`, `compose.py`, `resolve.py`, `routers/chat.py`, `eval/ask.py`, `samples/eval/ask_questions.yaml` (20 + 15). Rule 2 holds by construction: `TextRun` refuses digits (`llm/schemas.py:89-96`), and every chip, number and table value is read from a result cell by code (`compose.py:56-70, 84-104`). The eval passed 35 of 35 with 0 unsourced. |
| **D4.4** Shell: rail, settings (four, cut 1), job tray with Cancel and Retry | **done** (fixed here) | `LibraryPanel.tsx:33-82`, `AppShell.tsx`, `SettingsDialog.tsx:37-79`, `JobTray.tsx`. **Fixed:** the tray was a Radix *dropdown menu*, which cancels Tab, so Cancel, Retry and Dismiss couldn't be reached by keyboard (commit 8e01101). The `?` sheet is cut 9. |
| **D4.5** Library rename and delete with an Undo toast | **done** | `LibraryPanel.tsx:139-157`, `DatasetMenu.tsx:26-89`. F16 is unverified. |
| **D4.6** Widget menu: change view, duplicate, collapse, show as table, delete with Undo, 20-widget warning | **partial** | Collapse and Expand were broken; fixed here (commit 2be752a, shown live in `08-expand-bug-h1.jpg` → `10-expand-fixed.jpg`). The 20-widget warning only shows from the Add widget drawer (F4). |
| **D4.7** Dashboard: grid, widget states, Bklit adapter for bar/line/area/pie/ring/kpi/table, "How do you know?", click-to-filter, Add widget drawer | **partial** | `Dashboard.tsx`, `WidgetShell.tsx`, `charts/adapter.tsx`, `ExplainDrawer.tsx`, `AddWidgetDrawer.tsx`. Click-to-filter needs a mouse (F2). The explain drawer can show SQL the widget isn't running (F3). Brushing is cut 8. The outdated state waits for D7. |
| **D4.8** Chat bar and thread: streaming status, number/table/chart/text blocks, Pin, sources, `/` | **done** | `ChatBar.tsx` (status `:99-103,214-223`, `role="log"` at `:195`, Pin `:241`, sources `:271-285`, `/` at `:74-86`), `Blocks.tsx`. Seen live. Suggested questions are cut 9. |

## Findings, ranked

"Locked" marks a file with the owner's uncommitted Day 6 work, so this review reports the finding but doesn't fix it.

### High

- **F1. A two-valued numeric target that isn't 0/1 gets a "rate" above 100% (Rule 4).**
  - Where: `api/sherlock/dashboard/candidates.py:58-60` (locked). The same assumption is in `scoring.py:41-46` (locked).
  - What happens: `binary_target` averages `CAST(target AS DOUBLE)` for any int, float or bool target with two values. A last column coded 1/2 is `target_like` (`profile/infer.py:142`), so its KPI is "Rate of outcome" at `AVG = 1.4`, shown as **140%**. The same happens to its rate-by-category bars and lines.
  - Reproduced offline: a 60/40 column of 1s and 2s gives `[(1.4, 100)]`.
  - TRD §7.3 ("a numeric or yes/no target is averaged") describes the bug.
  - Fix: average only for 0/1 or bool values. Otherwise compare against the positive value as text targets do. Add this to TRD §7.3.

### Medium

- **F2. Click-to-filter needs a mouse.**
  - Where: `web/src/components/charts/adapter.tsx:94-113,148-151` (locked), `WidgetShell.tsx:56-60` (locked).
  - What happens: a click reads the hovered bar or slice from `useChartHover`. Bars and slices aren't focusable and have no key handler. The Bklit spike notes (`FEEDBACK.md:219`) chose this design.
  - Violates UI/UX §8: nothing may rely on hover alone.
- **F3. "How do you know?" can show SQL the widget isn't running.**
  - Where: `ExplainDrawer.tsx:12-14` against `WidgetShell.tsx:46-51` (locked).
  - What happens: a chart doesn't filter itself by its own category, but the drawer always adds the global filter, so the SQL shown has a clause the chart's data doesn't.
  - Violates PRD DASH-7 and App Flow §7.3 ("exactly as it runs now").
  - Fix: pass the applied filter through `onExplain`, which is a change to locked `WidgetShell.tsx`.
- **F4. The 20-widget warning only shows from the Add widget drawer.**
  - Where: `AddWidgetDrawer.tsx:58`.
  - What happens:
    - Duplicate (`routers/widgets.py:138-149`) doesn't return `warning`.
    - Pin (`routers/chat.py:114-152`) and chat's `create_widget` don't either, and the UI never shows one for them.
  - Violates PRD DASH-10 and D4.6.
- **F5. With a wide file, trends and tables can be cut before scoring.**
  - Where: `dashboard/candidates.py:204` (locked).
  - What happens: `out[:60]` truncates in generation order: KPIs, then every dimension × measure, then trends, then tables. With up to 30 kept columns, time trends and the top table can be dropped before they're scored.
  - TRD §7.3 says "cap 60 candidates" but not which ones go.
  - Fix: score first, or cap each kind.
- **F6. Pinning a table pins the first result's query, not that table's.**
  - Where: `routers/chat.py:134-139`.
  - What happens: the widget is built from `focus["sql"]`, which is `results[0].template` (`agent/loop.py:283`), whatever `block["result"]` is. A table pin also drops the answer's `selection_id`.
  - Today the UI only offers Pin on chart blocks (`ChatBar.tsx:241`), so only direct API calls hit this.
- **F7. The widget the user is looking at is read without checking its dataset.**
  - Where: `agent/loop.py:128-131`.
  - What happens: `SELECT title FROM widgets WHERE id = ?` takes `context.focused_widget_id` with no `dataset_id` check, so another user's widget title can reach the prompt. The IDs are random ULIDs, so this is low risk. `explain_widget` itself checks (`:239`).
- **F8. Compose is repaired often.**
  - What happens: in the live eval, compose made 52 calls for 34 answers, and 18 were repairs. Each repair costs a `medium` call (about 1,200 tokens) and adds latency; the median answer took 11 s.
  - Fix: worth a prompt pass. The validator messages in `compose.py:177-193` show which rules fail most.
- **F9. No end-to-end test, though `CLAUDE.md` lists `pnpm playwright test`.**
  - What happens: `web/` has no Playwright config, dependency or spec. Plan §3 lists the Playwright flow as open (D8.6), so the docs agree with each other, but `CLAUDE.md` tells readers to run a command that doesn't exist.
  - Nothing tests the Day 4 UI flow (rail, rename and delete, widget menu, drawers, chat streaming, Pin) beyond the vitest units in `dashboard.test.tsx` and `App.test.tsx`.
- **F10. Charts can't be read without hover, and motion ignores reduced motion.**
  - Charts have no text alternative: their SVGs are `aria-hidden` with no label, and "Show as table" is the only route. The accessible summary is planned with fact sheets (D6).
  - Bars and pie slices animate with `motion` and never check `useReducedMotion`. `animate-pulse` isn't covered by the zeroed duration tokens (`theme.css:163-176`).
  - Both violate UI/UX §2.4 and §8.

### Low

- **F11. Widgets aren't focusable.** There's no `tabIndex` and no keyboard way to open a widget's menu. Chat's focused-widget context is set only on pointer down (`WidgetShell.tsx:78-85`, locked). UI/UX §6.
- **F12. `?widget=:id` is never read.** Chat's "Open the widget" links to it (`Blocks.tsx:89`), so the link opens the dashboard without the widget. App Flow §1 routes.
- **F13. The eval's `value` check is lenient.** `eval/ask.py:53-59` accepts the expected value from *any* cell of any table in the answer, so a wrong headline can pass when the right number is elsewhere in the table. Consider requiring a number block, or the single-cell table, first.
- **F14. `test_sandbox.py:90` isn't isolated.** It asserts that `tempfile.gettempdir()/sherlock-sandbox` is empty, which fails whenever another run or a live clean is using the machine. Day 2 territory. Fix: set `SANDBOX_TMP` to `tmp_path` in the test.
- **F15. `contains` filters don't escape `%` or `_`.** `widgets/compile.py:201`: a `contains "%"` filter matches every row.
- **F16. Possible double rename (unverified).** Inline rename may submit twice, once on Enter and again on blur, and Esc may commit through `onBlur` (`LibraryPanel.tsx:142-154`).
- **F17. Small UI gaps.**
  - The empty-widget message says "No rows match the current filter" even with no filter, and has no Clear filter link (`adapter.tsx:50-52`, locked).
  - "Show as table" resets on reload (`WidgetShell.tsx:53`, locked; UI/UX §5.5 says "this browser only").
  - Chat answers have no copy button (App Flow §10.2 item 4).
  - The drag handle has `aria-label` but no role.
  - The resize separators have no `aria-valuenow`.
- **F18. The Bklit spike is marked "passed" without one of its pass rules.** `FEEDBACK.md:207-219` says shared hover was "not tried yet", but plan §2 D1 makes shared hover a pass rule. Matters for D6 hover linking.
- **F19. Environment notes for whoever runs the browser check next.**
  - The `sherlock_uid` cookie is set for `localhost` without a port, so parallel apps on other ports in the same browser profile overwrite it. Mid-check, the dataset went `404` and each request made a new user. Using `review4.localhost` avoided it.
  - The first page load made 3 anonymous users at once, because concurrent cookie-less requests each create one. That's the Day 1 identity finding.
  - After `git checkout` plus `sed`, Vite on Windows sometimes missed the file change; `touch` fixed it.

## Commits on this branch

| Commit | What | Test |
|---|---|---|
| 37b79b6 | `compile.py`: a row predicate must be balanced, and `{{rows}}` must be ANDed into the `WHERE` of every `SELECT` that reads `t`. Before, `a = 1) OR (1 = 1`, `{{rows}} OR x`, `NOT {{rows}}` and `(SELECT count(*) FROM t)` returned quarantined and filtered-out rows. This makes TRD §6.3's "the quarantine exclusion is always in what runs" true, so the doc needed no change. All 60 SQL templates from the live eval and exit check still pass. | `test_widgets.py::test_predicate_validation` (extended), `::test_rows_must_be_anded_into_every_read_of_t` |
| 2be752a | `Dashboard.tsx`: a widget drawn collapsed keeps its stored height when it expands. Before, Expand saved `h: 1`. This matches App Flow §7.3 "keeps its height for when it expands". | `dashboard.test.tsx` "keeps a collapsed widget's height…"; live before and after: `08-expand-bug-h1.jpg`, `10-expand-fixed.jpg` |
| 8e01101 | `JobTray.tsx`: the tray uses `@radix-ui/react-popover`, already a dependency, instead of a dropdown menu imported under the name `Popover`. Cancel, Retry and Dismiss can now be reached with Tab. This matches App Flow §15 and UI/UX §5.15 and §8. | `dashboard.test.tsx` "job tray": fails on the old import, passes now; live: the tray content has `role="dialog"` |

The TRD should add one sentence to §6.3 saying `{{rows}}` must be ANDed into the `WHERE` of every read of `t`. `docs/04-TRD.md` is locked for this review, so that sentence wasn't added here.

## Token Factory spend for this review

| Run | `llm_calls` | Prompt tokens | Completion tokens |
|---|---|---|---|
| `eval ask` (live, once) | 126 | 113,402 | 54,105 |
| Browser exit check, plus the sales build and one widget (live, once) | 21 | 19,261 | 23,175 |
| **Total** | **147** | **132,663** | **77,280** |
