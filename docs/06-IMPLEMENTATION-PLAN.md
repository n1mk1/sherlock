# Sherlock · Implementation Plan

Version 1.2 · 2026-10-24 (replan after a five-day slip with all nine cuts applied, §2.0; v1.1 added the submission artifact contents, §7) · Day-by-day build order from an empty folder to a submitted project. Deadline 2026-10-30 13:00 EDT; internal deadline 2026-10-29.

---

## 1. Working rules

- **Build in vertical slices.** Each day ends with something that runs end to end, even if thin. Horizontal layers that can't be exercised are not done.
- **Commit each verified slice to `main` and push immediately.** Feature branches only for work that takes more than half a day.
- **Mock the model when building UI.** Recorded LLM responses (`api/tests/fixtures/llm/`) let the frontend and pipelines be built without spending credits or waiting on Token Factory.
- **Definition of done for a task:** it runs on the Titanic sample locally; its automated test passes; it's reachable from the UI (if it has one); it's committed.
- **Cut, don't slip.** Each day has a "must" and a "stretch". If a must isn't done by the end of the day, the cut order in §5 applies the next morning.
- **Keep `FEEDBACK.md` open.** Every surprise with Token Factory, Nemotron, Serverless or Bklit goes in it the moment it happens.

Two-person split, if available: **Backend** owns `api/` (pipelines, agent, ML, data), **Frontend** owns `web/` (shell, grid, charts, Flow, chat UI). The API contract in the TRD is the handshake; the frontend builds against a mock server generated from the OpenAPI schema until the real endpoints exist.

---

## 2. Day-by-day

### 2.0 Replan · 2026-10-24 (in force)

Nothing was built Oct 20–23, so the build started on Oct 24, five days late. The team is solo. Approved by As Wasti on 2026-10-24:

- **Cuts applied:** all nine rows of the cut order in §5, from today. The detail is below. The never-cut list in §5 is unchanged.
- **Dates:** the schedule below replaces the dates of Days 1–9. The original days stay as the reference for each item (for example "D2.3" is Day 2, Must item 3). Each item keeps its definition of done (§1), and an item narrowed by a cut is done when what remains is done.
- **Process changes (no scope dropped):**
  - The frontend builds against the real API, not an OpenAPI mock server (this replaces D2.9's mock handler). Recorded LLM fixtures (§1) are still used.
  - The three Day 1 spikes become 1-hour checks at the start of the work that uses them: Bklit before the dashboard (D4.7), Glide before the CSV tab (D5.1) and react-grid-layout with the dashboard grid. Their pass rules and fallbacks are unchanged, and the results go in `FEEDBACK.md`.

| Date | Work (original day.item) |
|---|---|
| Fri Oct 24 | D1.1 scaffold · D1.2 Nemotron smoke test · D1.4 migrations, identity, ownership, rate limiter, `/me` |
| Sat Oct 25 | D1.3 hello-world deploy first (timeboxed to 3 h; the VM fallback is taken the same day if the `/data` exit check fails) · D2.1–D2.8 backend |
| Sun Oct 26 | D3.1–D3.5 the Cleaner · D4.1–D4.3 widgets, dashboard builder, agent v1 · D2.9–D2.10 shell and Library |
| Mon Oct 27 | D3.6 cleaning screens · D4.4–D4.8 frontend · D5 (within cut 5) · D6.1–D6.6 (within cut 6) |
| Tue Oct 28 | D7 (within cuts 4 and 7) · D8.1–D8.6 (within cuts 2, 3 and 9) · **feature freeze at 12:00** · D9.1–D9.5 ship |
| Wed Oct 29 | Day 10 unchanged: video, Devpost, `FEEDBACK.md`, submit |
| Thu Oct 30 | Morning buffer only, as before |

What each cut removes from the days below:

| Cut | Removed | Stays |
|---|---|---|
| 1 | D4.4: the settings dialog beyond four settings | mode, accent, chatbar, after-upload |
| 2 | D8.1 and D8.2: `propose_card_edit` and "rewrite" proposals | |
| 3 | D8.1 and D8.2: the "take it toward X" path, direction nodes and the building-state checklist | canvas, card/note/synthesis nodes, labeled edges, "make sense" |
| 4 | D7.2, D7.4 and D7.5: the `linear_regression` and `logistic_regression` methods, the method control, the coefficients and residuals views, and Compare with Auto | Auto; `repro.py` for Auto |
| 5 | D5.1–D5.3 and D5.7: range selection, TSV copy/paste, fill down, duplicate row, buffer undo/redo, the Review changes drawer, find and replace, the filter row, quick views, the cell provenance tooltip, status-bar stats, right-click menus, jump to row and Ctrl+arrow | the paged grid, cell edits, add/delete row, sort, find, Save (conflict handling, Discard), the Changes panel with Undo; also kept because other P0s need them: Clean with AI (P0-02), the Download/Export notebook entry (P0-12) and Restore for quarantined rows (Rule 3) |
| 6 | D6.2: the material hash and the material-change check | every affected card is re-narrated |
| 7 | D7.2, D7.4 and D7.5: the `predict` recipe, the predictions table, predicted cells and explain-row; `samples/titanic_blanks.csv` is not needed | `driver_analysis` |
| 8 | D4.7: brushing and the brush → selection chip (no spike ran, so brushing is the safe cut) | click-to-filter; ML scope comes from a filter or the whole dataset; §9 moment 6 filters instead of brushing |
| 9 | D4.3: the suggested-questions endpoint and UI; D4.4 and D8.3: the `?` shortcuts sheet | chat; the `/` shortcut |

**Hosting change (2026-10-24, owner's decision):** D1.3 deploys to Render (`render.yaml`, PRD §9) instead of a Nebius Serverless Endpoint. The account's Nebius AI Cloud tenant was suspended, and the rules don't require Nebius hosting. The exit check is unchanged. The Nebius steps in D1.3 and D9.2 stay valid as the alternative (`scripts/deploy.sh`). D1.3 was done on 2026-10-24: https://sherlock-anw3.onrender.com serves `/healthz` and the web shell, and the `/data` exit check passed (TRD §11).

If a Must from this table slips, §5 has nothing left to cut, so any further drop needs a PRD change by the owner.

### Day 0 · Oct 19 (evening): decisions locked

- [x] These six documents written.
- [ ] Create the Nebius account/project, request Token Factory access, note credit balance.
- [ ] Create the GitHub repo `sherlock` (public from day 1, MIT license visible).

### Day 1 · Oct 20: foundations, model facts, first deploy

**Must**
1. Repo scaffold: `api/` (uv, FastAPI, pydantic-settings, `/healthz`), `web/` (Vite + React + TS + Tailwind + shadcn init), `docker-compose.yml`, `.env.example`, `README.md` skeleton, `FEEDBACK.md`, `LICENSE`, CI running `pytest` and `pnpm test`.
2. **Nemotron smoke test** (`scripts/smoke_llm.py`): list the Token Factory catalog; for each Nemotron model in the catalog (plus the embedding model): a plain completion, a JSON-schema completion (3 schemas from the TRD), a tool call, a pandas task, latency and tokens. Write results into `FEEDBACK.md` and set `MODEL_LARGE/MEDIUM/SMALL/EMBED` (Nemotron 3 Ultra, Super and Nano, plus an NVIDIA embedding model or empty; TRD §3.5), `NVIDIA_EMBED_MODELS` and `LLM_TOOLS_MODE` in `.env.example`.
3. **Hello-world deploy**: build the image (API plus the built web app served under `/`), push to a registry, create the Nebius Serverless Endpoint pinned to one replica with a mounted filesystem at `/data`, and confirm `GET /healthz` and the web shell from a public URL. Exit check: a file on `/data` survives a restart and a SQLite write lock works on it; if either fails, switch to one Nebius AI Cloud VM with a disk the same day. Record the exact commands in `scripts/deploy.sh` and the README.
4. SQLite migrations 001 (all tables in the schema doc), the identity middleware (`sherlock_uid` cookie → `users`), the ownership dependency for every route, the rate limiter, `GET /me` and `PUT /me/settings`.
5. **Spikes** (timeboxed 2 h each, results in `FEEDBACK.md`):
   - Bklit: install `bar-chart`, `line-chart` via the shadcn registry; confirm custom tooltip content, a shared hover state across two charts, brushing (or what it takes to add it), 5k points, and that the charts read the theme tokens. Pass: tooltip, shared hover and theme tokens work. If brushing is missing, cut 8 drops brushing, not click-to-filter.
   - Glide Data Grid: editing, range selection, range paste, fill handle, custom theme from CSS variables, 500k-row virtualization with a paged data source. Pass: editing, range select and range paste work. If fill handle or range paste fail, they move to P1 (there is no AG Grid fallback).
   - react-grid-layout: works with the project's React version; drag handle restriction; ResizeObserver re-measure. Pass: all three work; the fallback is fixed layouts with no drag.

**Stretch**: the light and dark token sets and the five accent sets in `web/src/app/theme.css`.

**Exit**: public `/healthz` works; model assignments known; spike answers written down; CI green.

### Day 2 · Oct 21: ingest, profile, steps, sandbox, shell

**Must**
1. `ingest/`: upload endpoint with size/decoding checks, sniffing, `all_varchar` import to `v1.parquet`, `_row_id`, readable through the cached in-memory DuckDB connection. `POST /datasets`, `POST /datasets/sample`, `GET /datasets`, `GET /datasets/{id}`.
2. `profile/`: type and role inference, stats, histograms, top values, value index (no embeddings yet), all detectors from PRD §7.3.2 (in `cleaning/detectors/`, called by `profile/`) with unit tests on synthetic columns. `GET /datasets/{id}/datacard`.
3. `steps/`: step model, `commit_step` (new Parquet, version row, lineage rows, file lock, `base_version` check, `effective_step_ids`, re-profile of the new version, `state_rev` bump, **`notebook_code` required on every step**: edit batches rendered to pandas at commit), `undo` for the latest step. `GET /datasets/{id}/steps`, `POST …/undo`.
4. `sandbox/`: subprocess worker with limits and the static allowlist, and the `sherlock-sandboxd` launcher that spawns it as the `sandbox` user; protocol tests (timeout, memory, forbidden import, happy path).
5. `jobs/`: runner, `jobs`/`job_events` tables, SSE endpoint with replay, `profile` job wired to upload.
6. Rows API: `GET /datasets/{id}/rows` with paging, sort, filter, views; `POST /datasets/{id}/edits` committing an `edit` step.
7. `llm/`: client, schemas, repair, retries, budgets and the `llm_calls` log (the Day 3 Cleaner needs them).
8. The typing step in `profile/` (TRD §7.1 step 3b), committed as step 1 on every path.

**Must (frontend)**
9. Three-panel shell with tabs and header rows, the theme tokens, the generated API client, the SSE hook with resume, TanStack Query and the stores, built against the OpenAPI mock server (`pnpm openapi` plus a mock handler generated from it).
10. Library panel: list with status badges (user-level SSE), upload with dropzone and import preview (Papa Parse), sample button.

**Stretch**: `cleaning/helpers/` with tests; `verifiers.py`.

**Exit**: `curl` can upload Titanic, get its data card, page its rows, post an edit batch, see a new version, undo it (a newer version with the previous data); SSE shows the profile job's progress.

### Day 3 · Oct 22: the Cleaner

**Must**
1. `cleaning/verifiers.py`, `gate.py`, `helpers/` complete with tests.
2. `cleaning/loop.py`: the headless pipeline exactly as TRD §7.2, with prompts for diagnose / propose / critic and recorded fixtures for tests. `POST /datasets/{id}/clean`, `GET /datasets/{id}/report`, `job.log` events.
3. `eval/corruption.py`: inject damage into 3 clean datasets (Titanic-derived clean set, a sales-style synthetic set, an HR-style synthetic set), run the Cleaner, score recovery / harm / row loss, print a table. First numbers into `FEEDBACK.md`.
4. "Use as is" endpoint (skips to the build job, which for now just marks `ready`).

5. `sherlock` CLI entry point (`clean`, `eval`, `export`), `scripts/make_samples.py` (seeded) generating the synthetic files in §6, and job cancellation (`POST /jobs/{jid}/cancel`) behind the cleaning Stop and the tray's Cancel.

**Must (frontend)**
6. Cleaning offer and cleaning-in-progress screens driven by SSE; the end-of-run report view (the Changes panel links to it once the panel lands on Day 5).

**Exit**: `sherlock clean <dataset>` runs headless on Titanic with the real model, commits steps, produces a report, and the benchmark prints numbers. The Titanic expectations (age by title, deck from cabin, boat/body leakage) are checked by hand and noted.

### Day 4 · Oct 23: shell, dashboard builder, widgets, chat v1

**Must (backend)**
1. `widgets/`: spec model, SQL compile with `{{rows}}` and global filters, sqlglot validation, execution with caps and cache. `GET/POST/PATCH/DELETE` widgets, `GET /widgets/{id}/data`, `/explain`, `PUT layout`, `POST /datasets/{id}/selections`.
2. `dashboard/`: candidate generation (bar, line, area, KPI and table only until the custom charts land on Day 6), interestingness scoring, curation prompt (with fixture), validation, layout packing, `build_dashboard` job. Wire it after cleaning and after "Use as is".
3. `agent/` v1: loop with route → `ask_data` / `find_rows` / `explain_widget` / `ask_history` → compose → verify; `create_widget` from a prompt. `POST /datasets/{id}/chat` streaming, `GET …/chat`. Suggested questions endpoint. Eval v0: 20 Titanic questions and 15 on `sales_dated.csv` in `samples/eval/ask_questions.yaml`, run daily from here.

**Must (frontend)**
4. Shell completion: collapse to rail, settings dialog with all nine settings (only mode, accent, chatbar and after-upload if solo: cut 1), keyboard shortcuts sheet, job tray with Cancel and Retry.
5. Library rename and delete with Undo toast.
6. Widget menu: change view, duplicate, collapse, show as table, delete with Undo, and the 20-widget warning.
7. Dashboard: react-grid-layout grid, widget shell with all states, Bklit adapter for bar/line/area/pie/ring/kpi/table, "How do you know?" drawer, click-to-filter, brush → selection chip, Add widget drawer.
8. Chat bar and thread: streaming status, blocks (number, table, chart with Pin, text), sources disclosure, suggested questions, `/` shortcut.

**Exit**: upload → offer → clean → dashboard builds itself in the browser; chat answers "average fare by class" with a table and the SQL; "add a chart of fare by port" creates a widget.

### Day 5 · Oct 24: CSV tab

**Must**
1. Glide grid with the paged data source, header metadata, cell marks (changed / flagged / unsaved / predicted / invalid), provenance tooltip (`GET /cells/{row}/{col}/history`).
2. Editing buffer (Zustand + local storage): cell edits with type-aware editors, ranges, copy/paste TSV, fill down, add/duplicate/delete rows, undo/redo, pending count, Review changes drawer, Save → `POST /edits` with conflict handling, Discard.
3. Toolbar: Find and replace (`GET /find` + buffer edits), Filter row, quick views, Download, Clean with AI popover (`POST /clean` with scope and the pending-edits guard).
4. Changes panel: unsaved list, steps with expand (code via Shiki, edit lists, impact, decisions), Undo per step with the replay confirmation (`409` handling).
5. Backend: undo-with-replay; `user_edited_cells`; "run cleaning on new rows" option; cascade v0 (re-query all widgets after a commit); status bar stats computed client-side from the loaded page or server-side for full-column selections.
6. **Notebook export v0** (`notebook/`): title, parameters, requirements, helpers, load, one cell group per step, the assertion cell, one cell group per widget (SQL → embedded table, matplotlib chart). `POST /datasets/{id}/exports/notebook`, `GET /exports/{id}`, download, `exports` table, cache. The nbconvert execution test on the sample in CI. Frontend: dataset menu (⋯) with Export notebook, the Download menu in the CSV toolbar, the export dialog (options, notes, Save and export), progress toast, Ctrl+Shift+E.

7. Right-click menus with keyboard equivalents, jump to row and Ctrl+arrow navigation (P0: CSV-3, CSV-14), and Restore for quarantined rows.

**Exit**: edit cells and add a row on Titanic, save → a new version (v8) appears, widgets re-query (cascade v0: all widgets), the step shows in Changes with Undo, and undo produces v9 with v7's data. **Export notebook → the `.ipynb` runs top to bottom in a fresh venv and rebuilds the current version, including after the undo.**

**Done 2026-10-25, within cut 5** (as built, in the TRD, App Flow §8 and §17, and the UI/UX brief §4.7, §5.6–§5.7 and §5.13):
- [x] D5.1 within cut 5: the paged Glide grid (the 1-hour check passed, `FEEDBACK.md`), header type, missing share and mini histogram, the changed, flagged, invalid and unsaved marks.
- [x] D5.2 within cut 5: cell edits, add row, delete row, Save with conflicts ("Rebase and save", keep mine or theirs), Discard, the buffer in local storage.
- [x] D5.3 within cut 5: Find, Clean with AI (whole dataset, selection, new rows; the pending-edits guard), the Download menu.
- [x] D5.4: the Changes panel (unsaved lines, steps with code or edit list, impact and decisions, Undo with the replay and typing confirmations). Code is shown in a plain mono block: Shiki wasn't added.
- [x] D5.5: undo with replay, cascade v0 (every widget re-queried after a commit), "Run cleaning on the n new rows" from the save toast.
- [x] D5.6: notebook export v0 with the execution test (pytest) and the fresh-venv eval (`sherlock eval notebook`).
- [x] D5.7 within cut 5: Restore for quarantined rows (select cells in them, then Restore).
- Exit, checked: an edit and a new row saved as a new version, the widgets re-queried (toast), the step in Changes with Undo, the undo made the next version with the earlier data, and the exported notebook ran and rebuilt the current version after the undo, in a fresh venv for four sample files.

### Day 6 · Oct 25: stories and the cascade

**Must**
1. `stories/`: fact-sheet computations per view type with tests; significance helpers; relation graph; narrator prompt with the chip-only schema and the no-digits validator; `verify_claim`; overview; `stories` job streaming `card.updated`.
2. Cascade as TRD §7.6 (column-level dependencies, material hash, suggestion path for edited cards, "ask first" mode, debounce).
3. Frontend: story panel with cards, chips (evidence drawer), related chips, two-way hover linking with the spotlight, "changed"/"outdated" badges, inline card editor (TipTap with a chip node and the `/` picker), suggestion side-by-side, Ask why → chat.
4. Cascade UI: progress line, widget updating states, toast summary.
5. Custom visx histogram, heatmap, box plot and scatter; builder candidates widened to them. Gauge views render as a KPI tile in P0.
6. Notebook export: story cards as Markdown cells (chip rendering, unverified footnotes, evidence details blocks), the overview as the introduction, "Include story cards" option wired.

**Exit**: the sample dashboard has grounded cards; hovering links both ways; editing `age` values in the CSV tab updates only the cards that depend on `age`; an edited card keeps its text and shows a suggestion.

**Done 2026-10-25, within cut 6** (as built in TRD §4.6, §6.4, §7.3–§7.7; App Flow §7.4, §11, §16; UI/UX brief §4.4–§4.6):
- [x] D6.1: fact sheets per view type with their tests, significance helpers (chi², Kruskal-Wallis, Kendall), relations, the narrator with the chip-only schema and its checks, `verify`, the overview, the `stories` job streaming `card.updated`. The narrator runs on `medium` (TRD §7.4).
- [x] D6.2 within cut 6: the cascade with column-level dependencies, edited cards given suggestions, "Ask first" marking cards outdated; every affected card is narrated again (no material hash). Debounce from D5.5.
- [x] D6.3: the story panel, cards, chips with the evidence drawer, related chips, two-way hover linking with the spotlight, changed/edited/outdated badges, the TipTap editor with chip and label nodes and the `/` picker, the suggestion side by side, Ask why → chat.
- [x] D6.4: the cascade's progress line, updating widgets and cards, the summary toast (since D5.5).
- [x] D6.5: custom visx histogram, heatmap, box plot and scatter; builder candidates for them. Gauges render as a KPI tile.
- [x] D6.6: story cards in the notebook (overview as the introduction, each card after its widget, evidence details, unverified footnotes, Include story cards wired).
- Exit, checked: the sample dashboard has grounded cards (live, Nemotron Super); hovering links both ways; editing `fare` in the data updated only the four cards that read `fare` (the exit names `age`; no widget on that dashboard read `age`); an edited card kept its text and showed a suggestion.
- **Review, 2026-10-25, after the deploy of `52cc5eb`.**
  - **Live check on https://sherlock-anw3.onrender.com, scripted against the API.**
    - Sample, Use as is: 7 widgets (bar, box, heatmap, histogram, KPIs), with 8 cards written by the model 48 s after upload.
    - Every chip matches its fact. No text run has digits or markup, and every card's evidence resolves.
    - Editing one `fare` cell cascaded in 22 s, and only the 3 cards that read `fare` changed.
    - An edited fare card kept its text and got a suggestion. An edited card that doesn't read `fare` got none.
  - **Fixed after the review** (TRD §4.6, §7.4, §7.6):
    - A card whose widget query fails is no longer left `updating`.
    - Accept sets the card's version.
    - Restoring a widget rewrites the overview.
    - Hovering a card no longer spotlights its widget in Edit layout.
    - Numbers spelled out in words are rejected.
    - The heatmap story may name both categories of its cell.

### Day 7 · Oct 26: ML

**Must**
1. `ml/common.py`: scope → DataFrame, framing, leakage check, split, preprocessing pipeline, baselines, explain, predictions, OOD, calibration. Planted-truth tests pass.
2. Recipes `driver_analysis` and `predict`, each with the methods Auto, `linear_regression` and `logistic_regression` (statsmodels, with assumption checks; method chooser is cut 4 and `predict` is cut 7 if solo); registry and manifests; `GET /recipes` with compatibility; runs API; caching; `run.updated` events; the Dashboard builder adds the driver widget.
3. Answerers: `ask_why`, `ask_stats`, `ask_model` (+ explain-row), `ask_meaning`, `app_help` with `docs/help/*.md`; tool exposure by tab.
4. Frontend: analysis dropdown with disabled reasons, setup form generated from the manifest (target, feature chips with exclusions, scope chip, method segmented control (pair only: cut 4 if solo), More), run progress, result views (importance, the partial-dependence mini chart on a factor bar, confusion and ROC; coefficients table and residuals are pair only: cut 4 if solo; predictions table is pair only: cut 7 if solo), model card drawer (Compare with Auto is pair only: cut 4 if solo), "who did it get wrong?" → CSV tab via `?rows=`, predicted cell style and explain tooltip (pair only: cut 7 if solo), outdated/re-run.
5. `repro.py` generation per method (`ml/runner.py` writes it at completion; `notebook/repro_render.py` renders it), `GET /runs/{rid}/code`, run cells in the notebook export with embedded metrics and importance/coefficients tables; the execution test asserts metrics within 0.5 pp.

**Stretch**: none. Spare time goes to Day 8's Flow work; P1 items wait until P0 is complete.

**Exit**: brush 3rd class → "What drives this?" → importance and a model card showing baselines; switch to logistic regression → odds ratios (pair only: cut 4 if solo); "predict survived" fills blank cells on a copy of Titanic with blanks introduced (pair only: cut 7 if solo); the exported notebook reproduces every run made (one if solo).

**Done 2026-10-25, within cuts 4 and 7** (as built in TRD §4.8, §5, §6.5–§6.8, §7.3, §7.5–§7.7, §14; App Flow §9; UI/UX brief §5.8–§5.9; Schema §2.13, §4):
- [x] D7.1:
  - `sherlock/ml/`: scope → DataFrame, framing, leakage (with a purity check for categories), stratified or plain k-fold, the preprocessing `Pipeline`, baselines (majority or mean, and the best one-column rule), CV, permutation importance and partial dependence.
  - Planted-truth tests pass: drivers found in order, the leak and the ID excluded, noise reported as "no signal". `uv run sherlock eval ml` prints them.
  - **Not built:** predictions, OOD and calibration. They serve `predict`, which is cut 7; the decision is recorded in TRD §7.5. Time-series and group splits are not built either.
- [x] D7.2 within cuts 4 and 7:
  - `driver_analysis` with Auto (logistic or ridge, gradient boosting and a random forest, chosen by CV within `time_budget_s`), and the registry with the other recipes disabled with their reason.
  - `GET /recipes`, the runs API (`/runs`, `/runs/preview`, `/runs/{rid}`, `/results?view=`, `/model-card`, `/code`, `/cancel`, plus `POST /widgets/{wid}/rerun`), the cache, and `run.updated`.
  - The cascade outdates runs, and the builder adds "What drives <target>?" when rows ≥ 100.
- [x] D7.3 (2026-10-25, follow-up):
  - `ask_why`, `ask_stats`, `ask_model` and `ask_meaning`, plus `app_help` with `docs/help/*.md` and tool exposure by tab (TRD §8.2).
  - explain-row stays cut with predictions (cut 7); `ask_model` says so for a one-row question.
  - The new model calls were recorded live into the chat fixture.
- [x] D7.4 within cuts 4 and 7:
  - **Built:** the analysis dropdown with disabled reasons; the setup form from the manifest (target, feature chips with exclusions struck through and reasons on hover, the scope chip, More); run progress; the importance view with the partial-dependence mini chart on a factor bar; the model card drawer; Outdated with Re-run; "Plain chart (SQL)".
  - **Built later the same day (follow-up):** the confusion and ROC views, and "Who did it get wrong?" (out-of-fold predictions saved at run time, the CSV tab via `?rows=`). Only `predict`, the predictions table, predicted cells and explain-row stay cut (cut 7).
- [x] D7.5:
  - `repro.py` for Auto, written at completion; the model card's metrics come from executing it. `GET /runs/{rid}/code` serves it.
  - Run cells in the notebook: the analysis widgets via their run, and `include_runs`, with embedded metrics, baselines and importance.
  - The execution test asserts the metrics are within 0.5 points of the model card, and they match exactly.
- Exit, checked in the browser on the sample (API on :8001 with its own data folder):
  - The built dashboard has "What drives survived?". Gradient boosting scores accuracy 80.4% against 78.0% for the best one-column rule (sex), with sex, then age, ticket and pclass. The model card shows the baselines, and boat, body and name are excluded with their reasons.
  - "What drives this?" on "Survival by Sex" opened the setup. Putting `boat` back in warned on the form and in the model card, and the verdict named boat alone as the rule the model can't beat.
  - An `age` edit with "Ask first" marked both analyses outdated, Re-run re-ran one on v3, and "Plain chart (SQL)" brought the bar chart back.
  - Brushing is cut 8, so the scope comes from a filter.
  - The exported notebook reproduces the sample's run (the execution test).

### Day 8 · Oct 27: Flow, polish, freeze

**Must**
1. `canvas/`: JSON Canvas model, `GET/PUT` with etag, pruning; actions `add_canvas_node`, `add_canvas_edge`, `propose_card_edit` (pair only: cut 2 if solo); `ask_story`; the "make sense" synthesis path; the "take it toward X" path (create widget → fact sheet → story → verify → direction card → placement; pair only: cut 3 if solo); "rewrite" proposals (pair only: cut 2 if solo).
2. Frontend Flow tab: React Flow canvas with card/note/synthesis nodes styled from tokens (direction nodes are pair only: cut 3 if solo), labeled edges, connect mode, palette with drag, minimap and zoom, selection → chat context chip, building-state checklist on direction cards (pair only: cut 3 if solo), "Open widget".
3. Quality of life: toasts with Undo everywhere destructive, `?` sheet complete, remember-where-I-was, empty states, error boundaries, offline banner. Notebook export entry points on Flow (palette Export) and in chat ("export a notebook" → dialog with pre-filled options); canvas notes as Markdown cells.
4. Eval: ask-anything set extended to ≈ 50 and run; grounding test run; failures fixed or documented.
5. Chat completion: resolve with the value index, clarification buttons, multi-step plans, follow-up focus, `update_widget`, `edit_cells` and `clean_selection` proposals with approve and reject, Add to Flow.
6. Jobs: checkpoints and resume with heartbeats, the purge job; the Playwright flow test.
7. **Feature freeze at end of day.** Anything not done moves to P1 or is cut.

**Exit**: on the sample, drag three cards, "make sense of this" produces a synthesis card with chips; "take it toward age" produces a new widget and a connected card (pair only); evals pass thresholds or the gaps are listed.

### Day 9 · Oct 28: ship

**Must**
1. `scripts/seed_sample.py`: run the full pipeline on Titanic once with the real model, store the artifacts under `/data/sample/`, and make `POST /datasets/sample` clone them with ID remapping (instant demo); test the clone from two browser profiles.
2. Deploy the final image (API plus built web app); set env vars; run the five-file end-to-end set against the public URL from a fresh browser profile; export the notebook for each and execute all five locally; fix anything that breaks (bugs only, no features). Commit the sample's exported notebook to the repo as `docs/examples/titanic3-v7.ipynb` so judges can read it on GitHub.
3. README, in the order in §7: the hosted URL, setup, local run, deploy, **how Nemotron and Token Factory are used** (which model does what, with the `llm_calls` purposes, latency and cost per role), Nebius services used, benchmark table, eval table, user-test and baseline results, known limitations, accessibility notes, architecture diagram, screenshots.
4. `THIRD_PARTY.md` licenses; confirm Bklit Studio is absent; sample-file license note.
5. Rate limits and budgets verified on the public URL; a second browser can't see the first's datasets.

**Exit**: a judge with the URL can: click Try with sample → see the dashboard in seconds → ask a question → edit a cell → see a card update → build a Flow story, and upload their own CSV.

### Day 10 · Oct 29: submit

1. Record the video from the demo script in §9 (screen recording of the live site; voice-over; captions for each hero moment). Upload to YouTube (public). Keep it ≤ 3:00.
2. Write the Devpost description with the sections in §7.
3. Finalize `FEEDBACK.md` into the feedback field, in the structure in §7.
4. Submit. Verify the submission page shows the repo, URL, video and track.

### Oct 30 (morning): buffer only. No changes to the deployed app unless it is down.

---

## 3. Task inventory by module (checklist)

### Backend

- [ ] `config.py`, `main.py` lifespan (migrations, job runner), `/healthz`, `/metrics`: all but `/metrics` done 2026-10-24 (the job runner starts in the lifespan since D2.5)
- [ ] `db/` migrations 001, repositories (users, datasets, versions, steps, lineage, widgets, cards, canvases, runs, jobs, messages, proposals, selections, value_index, llm_calls)
- [x] identity middleware, ownership dependency, rate limiter (2026-10-24)
- [ ] `storage.py` folder layout, locks, byte accounting
- [x] `ingest/` sniff, import, `_row_id`, sample loader (2026-10-24)
- [ ] `profile/` types, roles, stats, histograms, top values, issues, value index, embeddings (optional): all but embeddings done 2026-10-24 (the catalog has no NVIDIA embedding model), and the typing step done 2026-10-24 (D2.8)
- [x] `cleaning/detectors/*` (16 detectors) (2026-10-24)
- [ ] `cleaning/verifiers.py`, `gate.py`, `helpers/*`, `loop.py`, prompts: verifiers, gate and helpers done 2026-10-24 (D3.1); the loop, prompts, `POST /clean`, `GET /report` and the `clean` job done 2026-10-24 (D3.2); the owner's two cleaning-quality decisions (missing values stay missing; reviewer concerns don't block a commit) applied 2026-10-24
- [x] `sandbox/` worker, `sherlock-sandboxd` launcher, limits, allowlist, protocol (2026-10-24)
- [x] `steps/` commit, undo latest, undo with replay, lineage queries, user-edited cells: commit, undo latest and user-edited cells done 2026-10-24; lineage queries done 2026-10-24 (D2.6); replay done 2026-10-25 (D5.5)
- [ ] `jobs/` runner, events, SSE, cancellation, checkpoints, purge job, `nebius` backend stub: runner, events, SSE with replay, cancellation, heartbeats and the `profile` job done 2026-10-24 (D2.5); checkpoints and the purge job (D8.6) and the `nebius` stub remain
- [x] `widgets/` spec, compile, validate, execute, cache, explain: done 2026-10-24 (D4.1) for SQL widgets, with CRUD, layout and selections; ML widgets done 2026-10-25 (D7: a widget becomes an analysis, its data is its run's importance)
- [x] `dashboard/` candidates, scoring, curation, validation, layout, job: done 2026-10-24 (D4.2) for the P0 views; the custom-chart candidates done 2026-10-25 (D6.5); the driver widget done 2026-10-25 (D7.2)
- [x] `stories/` fact sheets, stats helpers, relations, narrator, verify, overview, cascade, material hash: done 2026-10-25 (D6) without the material hash (cut 6)
- [ ] `ml/` common, registry, 2 recipes with 3 methods, runner, artifacts, explain-row, predictions, compare-auto: done 2026-10-25 within cuts 4 and 7 (plan, core, analysis, repro, registry, runner, artifacts: `driver_analysis` with Auto); explain-row, predictions and compare-auto are cut
- [ ] `agent/` loop, router, resolve, 10 answerers, actions, verify, compose, focus, summaries, suggestions: v1 done 2026-10-25 (D4.3) with `ask_data`, `find_rows`, `explain_widget`, `ask_history`, `create_widget`, compose, verify and focus; the other answerers are D7–D8, summaries and the planner D8.5, suggestions cut 9; `ask_why`, `ask_stats`, `ask_model`, `ask_meaning`, `app_help` and tool exposure by tab done 2026-10-25 (D7.3)
- [x] `llm/` client, schemas, repair, budgets, logging (2026-10-24, D2.7; later shapes join `schemas.py` with their work)
- [ ] `canvas/` model, persistence, pruning
- [ ] `notebook/` exporter job, cell renderers (load, helpers, step, edit batch, widget, chart, run, card, note), repro code, embedded outputs, allowlist scan, cache, `exports` table, download endpoint, nbconvert execution test: v0 done 2026-10-25 (D5.6) with every part but the card, run and note cells and repro code (D6.6, D7.5, D8.3); run cells and repro code done 2026-10-25 (D7.5)
- [ ] `chat/` threads, messages, proposals: threads, messages and pin done 2026-10-25 (D4.3, in `routers/chat.py` and `agent/loop.py`); proposals are D8.5
- [ ] `routers/*` for every endpoint in TRD §4: the rows API (rows, cell history, edits, find, column values, `export.csv`) done 2026-10-24 (D2.6); selections are D4.1
- [ ] `eval/` corruption benchmark, planted-truth, grounding, ask-anything: the corruption benchmark done 2026-10-24 (D3.3); ask-anything v0 done 2026-10-25 (D4.3, `uv run sherlock eval ask`); planted-truth done 2026-10-25 (D7, `uv run sherlock eval ml`); grounding done 2026-10-25 (Day 6 review, `uv run sherlock eval grounding`, TRD §14)
- [ ] `scripts/` smoke_llm, seed_sample, deploy
- [ ] tests: unit, integration (mocked LLM), fixtures

### Frontend

- [ ] theme tokens (light and dark, five accents), fonts, ThemeProvider with mode and accent, reduce-motion
- [ ] API client (generated), SSE hook with resume, TanStack Query setup, error boundaries: all but error boundaries done 2026-10-24 (D2.9)
- [ ] stores: ui (panels, tab, chatbar), filters (global filter, selection), edits buffer, settings: the ui store (panels, the import file, live progress) done 2026-10-24 (D2.9); settings live in the `me` query; the filters store (global filter) and the ui store's panel sizes, rail, Edit layout, focused widget and chat thread done 2026-10-25 (D4); the selection waits for brushing (cut 8) and the edits buffer is D5.2
- [ ] shell: panels, rail, tabs, header rows, job tray, settings dialog, shortcuts sheet, toasts: panels (fixed widths; slide-overs below 1024px), tabs, header rows, the disabled chat bar and toasts done 2026-10-24 (D2.9); the settings dialog with the four cut-1 settings done 2026-10-24 (matching the owner's design canvas); the rail, resizing and job tray are D4.4, done 2026-10-25 (the shortcuts sheet is cut 9)
- [x] library: list, status badges, upload, dropzone overlay, import preview, sample, rename/delete: all but rename/delete (D4.5) done 2026-10-24 (D2.10); rename and delete with Undo done 2026-10-25 (D4.5)
- [ ] cleaning: offer, in-progress (log, so-far, checks), report view
- [ ] dashboard: grid, widget shell (all states), filter bar, add-widget drawer, explain drawer, KPI tile: done 2026-10-25 (D4.6–D4.7) except the filter builder button; the outdated state done 2026-10-25 with runs (D7)
- [ ] charts: Bklit components via registry, adapter, custom heatmap/histogram/box, highlight/point, brush, click-to-filter, table view, accessible summary: the Bklit components, adapter, point, click-to-filter and table view done 2026-10-25 (D4.7); custom histogram, heatmap and box plot (and scatter) done 2026-10-25 (D6.5), each with an accessible summary as its label; brushing is cut 8
- [ ] csv: grid data source, theme bridge, marks, editors, buffer UI, toolbar, find bar, filter row, review drawer, changes panel, clean-with-AI popover, status bar, context menus: done 2026-10-25 (D5) within cut 5 (no filter row, review drawer or context menus; the status bar shows the row count, cell count and position, not stats)
- [ ] ml: dropdown, setup form from manifest, progress, result views, model card drawer, predicted cells: done 2026-10-25 (D7.4) within cuts 4 and 7 (importance with partial dependence; no confusion or ROC views, no predicted cells)
- [x] stories: panel, card, chip, evidence drawer, badges, editor, suggestion view, hover linking, spotlight: done 2026-10-25 (D6.3)
- [ ] flow: canvas, node types, edges + labels, connect mode, palette, minimap, context chip, direction checklist
- [ ] chat: bar, thread, renderers (number/table/chart/text/proposal/clarification/plan), sources, pin/add-to-flow, suggested questions: the bar, thread, number/table/chart/text/clarification renderers, sources and Pin done 2026-10-25 (D4.8); proposals, plans and Add to Flow are D8.5, suggested questions cut 9
- [ ] export: dataset menu (⋯), Download menu, export dialog (options, preview sentence, notes, Save and export), progress toast with Download again, Ctrl+Shift+E, Flow palette and Changes panel entry points: done 2026-10-25 (D5.6) but the Flow palette entry (D8) and the dialog's Save and export button (the note tells the user to save first)
- [ ] Playwright flow test (ends with Export notebook → file downloaded)

---

## 4. Environments and commands

| Purpose | Command |
|---|---|
| Install | `cd api && uv sync` · `cd web && pnpm install` |
| Run locally | `docker compose up` or `uv run uvicorn sherlock.main:app --reload` + `pnpm dev` |
| Tests | `uv run pytest` · `pnpm test` · `pnpm playwright test` |
| Evals | `uv run sherlock eval corruption` · `… eval ml` · `… eval grounding` · `… eval ask` · `… eval notebook` (export + execute). As of 2026-10-25 `corruption`, `ask` and `notebook` run (`notebook` takes `--sets a.csv,b.csv` or `all` for the end-to-end set); the others answer that they come with D6 and D7, and exit 2. Since then `ml` (D7) and `grounding` (Day 6 review: every story card's chips re-checked, TRD §14) run too, so every eval in this row runs |
| Clean a file headless | `uv run sherlock clean <file.csv or sample>` (in `api/`): imports it, prints the live log and the report (D3.5) |
| Make the synthetic samples | `uv run --project api python scripts/make_samples.py` (seeded; writes `api/samples/`) |
| Export a notebook from the CLI | `uv run sherlock export notebook <dataset_id> --out out.ipynb` |
| Smoke the model | `uv run python scripts/smoke_llm.py` (from the repo root: `uv run --project api python scripts/smoke_llm.py`; options `--models a,b`, `--out report.json`, `--no-thinking`) |
| Seed the sample | `uv run python scripts/seed_sample.py` |
| Deploy | `./scripts/deploy.sh` (build → push → update endpoint) |
| Generate the API client | `uv run --project api python scripts/dump_openapi.py`, then `pnpm openapi` in `web/` (reads `web/src/api/openapi.json`, TRD §3.1) |

Environments: `local` (compose, `DATA_DIR=./data`, mocked LLM optional via `LLM_MOCK=1`), `prod` (Render web service with a disk, real Token Factory; the Nebius Serverless Endpoint is the alternative).

---

## 5. Cut order (apply the morning after a missed "must")

If the team is solo on Oct 20, cuts 1, 2, 3, 4 and 7 apply from Day 1. This table is the only way a P0 item may be dropped (PRD §5).

**Applied 2026-10-24: all nine cuts** (the replan in §2.0 lists what each one removes).

| Order | Cut | What remains |
|---|---|---|
| 1 | Settings dialog beyond mode + accent + chatbar + after-upload | Those four settings |
| 2 | Flow "rewrite this card" | make sense + take it toward X |
| 3 | Flow "take the story toward X" | canvas, notes, edges, make sense |
| 4 | Method chooser (linear/logistic) | Auto only |
| 5 | CSV tab beyond cell edits, add/delete row, sort, find, save, changes panel | That set |
| 6 | Material-change check in the cascade | Re-narrate all affected cards (more credits, same behaviour) |
| 7 | `predict` recipe | `driver_analysis` only |
| 8 | Brushing if the Day 1 spike found Bklit lacks it, otherwise click-to-filter | The other interaction |
| 9 | Suggested questions, `?` sheet | Chat works without them |

Never cut: headless cleaning with a report, the auto-dashboard, grounded story cards with linking, ask-anything with sources, the deploy, the cached sample, **and notebook export** (at minimum: load, steps, widgets, cards; if ML runs slip, their cells are omitted with a note).

---

## 6. Test and demo data

| File | Purpose | Source |
|---|---|---|
| `samples/titanic3.csv` | the sample and eval baseline | OpenML 40945 (fetched by `scripts/fetch_sample.py` if not bundled). Bundled as `api/samples/titanic3.csv` (2026-10-24): 1,309 rows, 14 columns, ARFF `?` written as empty cells |
| `samples/titanic_blanks.csv` | prediction demo (50 `survived` values blanked) | derived |
| `samples/sales_dated.csv` | time-series path (synthetic, 5k rows, monthly) | generated |
| `samples/wide_messy.csv` | 60 columns, mixed formats, sentinels (synthetic) | generated |
| `samples/reviews_text.csv` | free-text column (synthetic) | generated |
| `samples/broken_latin1.txt` | wrong delimiter, Latin-1, header on row 3 | generated |
| `samples/eval/ask_questions.yaml` | ≈ 50 questions with expected answers and tolerances | v0 on day 4 (Titanic plus `sales_dated.csv`), extended on day 8 |
| `samples/eval/corruption/*` | clean sets + injection config | day 3 |

The five-file end-to-end set is `titanic3.csv`, `sales_dated.csv`, `wide_messy.csv`, `reviews_text.csv` and `broken_latin1.txt`; `titanic_blanks.csv` is only for the prediction demo. The synthetic files come from `scripts/make_samples.py` (seeded, Day 3).

As generated (2026-10-24, D3.5): `sales_dated.csv` (5,000 rows × 8), `wide_messy.csv` (800 × 60), `reviews_text.csv` (600 × 6) and `broken_latin1.txt` (150 data rows × 4, Latin-1, `;`) are committed in `api/samples/`. `titanic_blanks.csv` isn't made: cut 7 removed the `predict` recipe. In `broken_latin1.txt` the two preamble lines carry the same delimiters as the data, so the sniffer reads them as data (152 rows) unless the import preview sets header row 3. This gap in header detection is known (App Flow §18: "auto-detection tries the first 5 rows").

`samples/eval/corruption/*` isn't a folder of files as built (D3.3): the three clean sets come from seeded generators in `sherlock/eval/synthetic.py`, and the damage plan (column, kind, share, seed) is in `sherlock/eval/corruption.py` (TRD §14). Checked in the Day 3 review (2026-10-25): two runs of `scripts/make_samples.py` write byte-identical files, equal to the committed ones.

---

## 7. Submission artifacts

What each artifact must contain is set by PRD §12 (the official rules and the judges' rubric).

- Repo: `README.md`, `LICENSE`, `FEEDBACK.md`, `THIRD_PARTY.md`, `docs/` (these), `docs/USER-TESTS.md`, architecture diagram (`docs/architecture.png`), screenshots, `docs/examples/titanic3-v7.ipynb` (the sample's exported notebook, viewable on GitHub). Public and readable without a login; `LICENSE` (MIT) at the root so it shows at the top of the repo page; no secrets in the history (`.env` ignored, a secret scan before making it public). Owner: As Wasti. LICENSE on Day 0, README and THIRD_PARTY.md on Day 9, FEEDBACK.md kept from Day 1 and finalized on Day 10.
- README sections, in order: what Sherlock is in two sentences and the hosted URL · a screenshot · try it (sample, then your own CSV) · **NVIDIA models and Nebius** (a table per role: model ID, what it does, median latency, tokens and cost per sample run; the Nebius services the deployed app actually uses; the request/data-flow diagram) · how trust works (sources, chips, verifiers, quarantine) · results (cleaning benchmark, ML planted-truth tests, grounding test, ask-anything eval, user test and baseline comparison) · **known limitations** (failed eval questions, cleaning cases the benchmark misses, files that fail, anonymous identity with no recovery, 7-day expiry, anything not shipped from P0) · accessibility · local setup and run (`.env.example`, a Token Factory key, `docker compose up`) · deploy · tests and evals · license and third-party notices.
- `docs/USER-TESTS.md`: for each tester (at least 3, none who has seen Sherlock before): who they are, the CSV, the task, time to first sourced answer, where they hesitated, what they said, what was changed because of it; plus the baseline comparison (the same 3 questions on the same file by hand versus with Sherlock: time, steps, and how many answers could be traced to their source).
- Public URL on Render (or the Nebius alternative), live through the judging period and winner announcement (PRD §9, TRD §11). Owner: As Wasti. First deploy on Day 1, final on Day 9.
- YouTube video ≤ 3:00, public, from the §9 script. Owner: As Wasti. Day 10.
- Devpost description, in this order: the problem and who has it (PRD §3.1) · what Sherlock does, in one line · the demonstrated result (benchmark, eval and user-test numbers) · how it works (architecture, which NVIDIA model does what and why that size, what runs on Nebius) · how it differs from existing tools (PRD §3.2) · limitations · what comes next (P1 and P2 highlights). Owner: As Wasti. Day 10.
- `FEEDBACK.md`, written for the Most Valuable Feedback criteria (completeness, viability, potential impact): for each of Token Factory, the Nemotron models (per model), and Nebius hosting: what we used it for, what worked, each problem with steps to reproduce and its effect on the build, and a concrete, buildable suggestion with who it would help.
- Devpost form: track (Best Apps and Agents), URL, video, repo, feedback, pre-existing project (no), city (if an IRL event was attended). Owner: As Wasti. Day 10.

---

## 8. Daily checklist

Each day: pull → run tests → work the "must" list top-down → commit per slice → update `FEEDBACK.md` → at end of day, write three lines in `docs/LOG.md` (done, not done, decision for tomorrow) → push.

---

## 9. Demo script (video, ≤ 3:00)

The hero moments the PRD's video metric refers to, in recording order. Every moment that uses a model carries a small on-screen caption naming the NVIDIA model and the Nebius service behind it (for example "Nemotron 3 Ultra on Nebius Token Factory plans each fix"), so the integration is shown throughout and not only at the end.

1. 0:00 to 0:15. The problem and who has it in one line (PRD §3.1), then Try with sample: the dashboard and its stories appear in seconds.
2. 0:15 to 0:40. Upload a messy CSV: import preview, the headless cleaning log, the report with "rows deleted: 0".
3. 0:40 to 1:00. Hover a widget to light up its story card, then click a number chip: "How do you know?" shows the SQL.
4. 1:00 to 1:25. Ask a question in chat and get a sourced answer; pin it to the dashboard.
5. 1:25 to 1:45. Edit a cell in the CSV tab and save: only the dependent cards update. Undo the step.
6. 1:45 to 2:10. Brush a range (with cut 8 applied: click a bar to filter), run "What drives this?", and read the model card against its baselines, with the leakage column excluded.
7. 2:10 to 2:30. On the Flow canvas, select three cards and run "Make sense of this": a synthesis card with chips appears.
8. 2:30 to 2:50. Export the notebook and run it in Jupyter: it rebuilds the current version.
9. 2:50 to 3:00. Close on the architecture: which Nemotron model does what on Nebius Token Factory, hosting on Render, and one result against its baseline.
