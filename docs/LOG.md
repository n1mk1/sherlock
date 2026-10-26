# Sherlock · Build log

Three lines per day: done, not done, and the decision for tomorrow (Implementation Plan §8).

## 2026-10-24 (Fri)

- **Done:**
  - Replan with all nine cuts (plan §2.0).
  - D1.1 scaffold: `api/`, `web/`, compose, CI, README, LICENSE, FEEDBACK.
  - D1.2 Nemotron smoke test: Ultra, Super and Nano pass 6/6 with reasoning on; `LLM_TOOLS_MODE=native`; no NVIDIA embedding model, so `embed` is empty.
  - D1.4: migration 001, cookie identity, ownership, rate limits, `/me`.
  - The public repo is `n1mk1/sherlock`; CI is green.
- **Not done:**
  - D1.3 Nebius deploy, moved to Oct 25 by the replan.
  - The Day 1 stretch: theme tokens in `web/src/app/theme.css`.
  - The Day 0 check of the Nebius credit balance (not recorded yet).
  - The owner's `CLAUDE.md` rule 6 edit is still uncommitted.
- **Decision for tomorrow:**
  - Open with the hello-world deploy: the image with the API and web build, a registry, and the Serverless Endpoint with `/data`. It's timeboxed to 3 h, and the AI Cloud VM fallback is taken the same day if `/data` persistence or SQLite locking fails.
  - Then D2.1–D2.8 backend: ingest, profile, steps, sandbox, jobs/SSE, rows API, the `llm/` client, the typing step.
  - Prerequisites from the owner: Docker Desktop running, the Nebius CLI installed and logged in, and a registry Nebius can pull from.

### 2026-10-24 (evening update)

- **Done:**
  - Theme tokens (the Day 1 stretch).
  - The production image (verified locally).
  - The `CLAUDE.md` rule 6 edit, committed.
  - Ubuntu WSL with the Nebius CLI. The Nebius AI Cloud tenant turned out to be new and suspended, so on the owner's decision hosting moved to Render (`render.yaml`, PRD §9).
  - D1.3 on Render: https://sherlock-anw3.onrender.com is live, and the `/data` exit check passed (boots 1 → 2, SQLite lock works, cookie user persists).
- **Not done:**
  - The Nebius AI Cloud credit balance: there's no active AI Cloud tenant. Token Factory, which serves all inference, shows 0.94 of the 1.00 starter credit left plus a $25 top-up (recorded in `FEEDBACK.md`).
  - The Nebius alternative is scripted but has never run.
- **Decision for tomorrow:**
  - Start the D2.1–D2.8 backend directly; the deploy is no longer first.
  - Move the Render plan from Starter to Standard before the sandbox lands (D2.4 needs about 2 GB).

### 2026-10-24 (night: autonomous run, D2.6 through Day 3)

- **Done** (each slice tested, documented, committed to `main` and pushed; CI green and the Render deploy live after each):
  - D2.6, the rows API: pages with sort, filter and the changed, flagged and missing views; cell marks and history read through the effective chain; edit batches with conflicts; find; column values; `export.csv`.
  - D2.7, the LLM client: retries, budgets, strict schemas, one repair call, `llm_calls`, recorded fixtures (`LLM_MOCK`, `LLM_RECORD`). A live check against Token Factory passed.
  - D2.8, the typing step: lossless casts committed as step 1 by the profile job. Titanic types 7 columns and lands on v2.
  - D2.9–D2.10, the web shell and library: three panels, tabs, the generated API client, SSE with resume, live status badges, the drop overlay, the import preview (Papa Parse), Try with sample.
  - D3.1: the helpers (which run in the sandbox), the verifiers (pandera included) and the gate.
  - D3.2: the headless Cleaner, plus `POST /clean` and `GET /report`.
  - D3.4: `POST /use-as-is`, and a `build_dashboard` job that marks the dataset ready.
  - D3.3: the corruption benchmark. With Nemotron, recovery was 92–97%, harm 0% and row loss 0% (`FEEDBACK.md`).
  - D3.5: the `sherlock` CLI (`clean`, `eval corruption`), the seeded samples, and Stop, which kills a running sandbox worker (directly or through `sandboxd`).
  - D3.6: the cleaning screens. The offer has its choices and "Remember my choice", the live log comes over SSE with the so-far counts, checks and budget, Stop works, and the end-of-run report has a full-report dialog.
  - **Verified live.**
    - The sample went upload → offer → clean → build → ready in the browser pane, locally (uvicorn plus Vite) and on https://sherlock-anw3.onrender.com, where the live log streams through Render.
    - `uv run sherlock clean sample` ran headless with the real model: 6 steps and 0 rows deleted.
    - The Cleaner ran on Render through `sandboxd`: 119 s, 6 steps, 0 rows deleted.
  - **Titanic expectations, checked by hand.**
    - Boat and body are marked as leakage and never changed. That needed a fix: the first run imputed `body`.
    - Age by title: it varies by run. The deployed browser run chose "Impute from title and passenger class" (5 fixed, 1 flagged, v2 → v8). Other runs chose finer groupings, or the global median committed with a flag.
    - Deck from cabin: the model offered it but chose "Fill with 'Unknown'".
- **Not done:**
  - Error boundaries; the rail, panel resizing, job tray and settings dialog (D4.4); library rename and delete (D4.5).
  - Header detection for a preamble that uses the data's delimiter. `broken_latin1.txt` needs header row 3 set in the preview (App Flow §18 says auto-detection tries the first 5 rows).
  - Placeholders in numeric columns are the Cleaner's weak spot in the benchmark: 28 of 102 recovered. Most were quarantined as parse failures.
  - Re-queued clean jobs start over (checkpoints are D8.6), and the "Cleaning automatically" toast isn't shown.
  - The dashboard builder (D4.2): the build job only marks the dataset ready.
- **Decisions made while I was offline:**
  - **Rows API.**
    - A stale `base_version` on `POST /edits` is always `409`, with the cells that changed since (possibly none); the client rebases and resends.
    - An edit that doesn't parse as its column's type is saved as NULL with its text in lineage, flag `invalid`.
  - **Lineage.** A non-null → NULL change now always counts as a changed cell; before, a failed cast was missed.
  - **Typing step.** A file with nothing to type gets no typing step and stays at v1. Values that cast but not losslessly (`007`) are quarantined like failures.
  - **Tests and fixtures.**
    - Tests run with no job workers by default; job tests opt in with the `run_jobs` fixture.
    - Fixture replies are matched by purpose and prompt substrings, most specific first.
  - **LLM reasoning** may be turned off only for `route`.
  - **Diagnosis schema.** It adds `preferred_option` (which the ambiguity vote counts) and `leave_as_is`.
  - **Cleaner.**
    - The best candidate runs on the full data before the gate, so the blast is measured, not estimated.
    - Every issue on a leakage or ID column is skipped, not just the leakage issue itself.
    - In a scoped clean, a candidate that retypes a column can't apply and scores 0.
    - A clean that ends any way but a model failure before the first step, Stop included, queues the dashboard build. A failure with no step returns to the offer, with the reason in `error`.
  - **"After upload"** is now followed by the profile job: `always` cleans, `never` builds.
  - **OpenAPI types.** openapi-typescript can't run on TypeScript 7, so `pnpm openapi` runs it through `npx` with TypeScript 5. The generated files are committed, and routes the schema doesn't type are typed by hand in `web/src/api/types.ts`.
  - **Interim screens.**
    - The CSV tab shows a read-only paged table until the Glide grid (D5.1).
    - The Dashboard tab shows "Last cleaning report" until the builder (D4.2).
  - **Benchmark scoring.** A placeholder's recovery counts if the cell is missing or holds the original value; yes/no compares equal to booleans.
  - **Samples.** `titanic_blanks.csv` isn't generated (cut 7 removed `predict`).
- **Token Factory spend:** about 0.65 M tokens this run (about 0.55 M on Ultra, mostly reasoning), across five Titanic cleans and three benchmark runs. At Token Factory's listed per-token rates that's well under the $5 cap. This is an estimate from `llm_calls`.
  - **Confirmed by the owner's console** (2026-10-24, after the run): the trial credit went from $0.94 to $0.00 and the $25.00 account balance is untouched, so the run cost at most $0.94.
  - A live call still succeeded afterwards, with the trial credit at $0.00.
  - The console's "Post-trial preference" says the account stops usage when the 30-day trial ends (29 days left) unless it's switched to paid usage.
- **What needs you:**
  - ~~Switch Token Factory to paid usage before the trial ends.~~ Done by the owner on 2026-10-24, so model calls draw on the $25 balance after the trial and the deployed app keeps its model through judging (PRD §9).
  - ~~The two judgement calls on cleaning quality.~~ Decided by the owner: missing values stay missing, and the critic's concerns can't block a commit on their own (applied, see below).
  - Review the `docs/` additions (TRD §4.3, §4.4, §7.1–§7.2, §7.9, §14; App Flow §3–§5).
- **The owner's cleaning decisions, applied the same night:**
  - Missing values stay missing unless a rule over related columns recovers them. A new hard verifier, `placeholder_fill`, rejects fills like "Unknown".
  - The reviewer's concerns no longer lower confidence; only its "changed something it shouldn't" verdict does.
  - **Titanic now:** cabin, home.dest and embarked stay missing, and age is imputed by class and sex and committed.
  - **Benchmark rerun:** 97.2%, 94.5% and 74.0% recovered, harm 0% and row loss 0%. Hr's drop is model variance (`FEEDBACK.md`).
- **The owner's design canvas, applied the same night:**
  - The "Sherlock UI examples" canvas is now the stated source for anything the UI/UX brief leaves open. The brief gained its details: the library panel (§5.0), the "v7 · 6 steps" version pill, the cleaning screen's measurements, the chat bar's placement, and the settings dialog. The changed-cell marker is now the canvas's 2px top line.
  - **Frontend:**
    - the Settings gear and dialog (the four cut-1 settings, which apply live)
    - library rows with issue counts
    - the steps pill
    - the 680px chat bar with its send button and the Chat bar setting
    - the empty state's chat bar in its column
    - the cleaning screen's mono tiles and its log grid
    - the CSV marks per §4.7
  - **API:** `Dataset` adds `issue_count` and `step_count`.
  - **Decision:** the cleaning board draws the centre alone, but the app keeps both side panels there, as App Flow §5 requires.
- **Decision for tomorrow:**
  - D4.1–D4.3 backend (widgets, the dashboard builder, agent v1).
  - Then D4.4–D4.8 frontend, starting with the Bklit and react-grid-layout checks (plan §2.0).

## 2026-10-25 (Sat, early hours): Day 4

- **Done** (each slice tested, documented, committed and pushed):
  - **D4.1, widgets.**
    - The spec model.
    - `{{rows}}` compiles to the quarantine exclusion, the predicate, the selection and the global filter as literal SQL, and sqlglot allows one SELECT over `t`.
    - Results are capped at 2,000 rows with a 10 s watchdog and a cache.
    - CRUD with soft delete, undo and duplicate; `explain`; the layout; selections.
  - **D4.2, the dashboard builder.**
    - Candidates come from roles, are scored in code, curated by Nemotron Super with a templated fallback, and the layout is packed.
    - Titanic got "Survival by sex", "Fare by class" and the KPIs. The four sample files all build with no failing widget.
  - **D4.3, chat v1.**
    - Route (Nano), resolve, `ask_data`, `find_rows`, `explain_widget`, `ask_history` and `create_widget`.
    - Compose (Super) with chips bound to result cells, streamed over SSE; pin.
    - Eval v0 (`uv run sherlock eval ask`) passed 31 and then 32 of 35, with 0 unsourced answers.
  - **D4.4–D4.8, frontend.**
    - The library rail, panel resizing, the job tray, and library rename and delete with Undo; on the backend, `PATCH`, `DELETE`, `restore` and `raw.csv`.
    - The dashboard: the react-grid-layout grid, the widget shell and its menu, the Bklit adapter, click-to-filter, "How do you know?", and the Add widget drawer.
    - The chat bar and thread, with streaming, blocks, sources, clarifications and Pin.
  - **Day 4 exit, checked in the browser on the sample:**
    - "Use as is" builds the dashboard.
    - "average fare by class" answers with a table and its SQL.
    - "add a chart of fare by port to the dashboard" creates the widget, reading port as `embarked`.
    - Clicking "female" filters every other widget.
    - Upload → clean → dashboard was checked through the API and the tests, not clicked through again.
- **Spikes:** Bklit passed. react-grid-layout passed, with its `WidthProvider` replaced by our own `ResizeObserver` (`FEEDBACK.md`).
- **Decisions made while you were offline:**
  - Compose moved from Nano to Super. Nano left chips with no words between them (TRD §8.1, `FEEDBACK.md`).
  - A chart doesn't filter itself on its own category: the clicked bar keeps the accent and the others fade.
  - The builder's scoring gives bars only η²: a target's bars count in full, measures' bars are halved when the file has a target, and count bars get a quarter of their unevenness. Outlier and correlation credit waits for the D6 chart types.
  - With no `LLM_BASE_URL` and no `LLM_MOCK`, model calls fail at once, so tests and bare runs use the fallbacks without retrying.
  - Answers stream their table first, then the prose.
- **Later the same morning:**
  - **Upload → offer → clean → dashboard, checked in the browser** with a generated messy file. The offer found the case variants and the money stored as text. The live log streamed, and the dashboard built itself on v4.
  - **Deploy.** CI can't start because of GitHub billing, so on the owner's instruction Render was deployed by hand (`d188d19`). It was live after about 90 s.
  - **The Day 4 exit, checked on the live site.**
    - The sample built 8 widgets.
    - "average fare by class" answered with the table and its SQL in 14 s.
    - "add a chart of fare by port to the dashboard" made the widget in 5 s.
  - **Fixes from those runs:**
    - The prose check now needs one text run of at least two words; live, "classavg_fare" had passed.
    - `create_widget` alongside another intent needs the message to say "dashboard", "widget" or "pin"; Nano had added a widget for "… as a chart".
    - The web bundle is code-split, 907 kB → 488 kB on first load.
    - Derived small-screen KPI tiles no longer trip react-grid-layout's minimum-width warning.
- **Not done:**
  - Prose fails twice for some answers, which then fall back to the table with its SQL.
  - Median answer time is 11–12 s, against the ≤ 4 s target to the first block (TRD §13); the first table arrives in about 4–6 s.
  - CI hasn't run on any Day 4 commit (GitHub billing); Render deploys need a manual trigger until it does.
  - The Filter builder button and the shared hover between widgets (D6).
- **Note on local dev:** another session's API was running on :8000 with the same `api/data` database. Two job runners on one database can claim each other's jobs, so for this session the API ran on :8001 with Vite on :5174 (`.claude/launch.json`, `web-8001`).
- **Decision for tomorrow:**
  - Day 5: the CSV tab within cut 5, and the notebook export v0 (D5.6).
  - Then D3.6's leftovers and Day 6 within cut 6.

## 2026-10-25 (Sun): Day 7, ML within cuts 4 and 7

- **Done** (tested, documented, committed and pushed in one slice):
  - **D7.1, `sherlock/ml/`.**
    - Framing and leakage, including a purity check for categories.
    - Stratified or plain 5-fold CV with seed 42, the preprocessing `Pipeline`, and the baselines (majority or mean, and the best one-column rule).
    - Permutation importance and partial dependence.
    - Planted truth passes: drivers found in order, the leak and the ID left out, noise reported as "no signal". `uv run sherlock eval ml` prints it.
  - **D7.2.**
    - `driver_analysis` with Auto (logistic or ridge, gradient boosting and a random forest, chosen by CV within the time budget); the other recipes are listed disabled with their reason.
    - The runs API (recipes, preview, runs, results, model card, code, cancel, and widget Re-run), the cache, and `run.updated`.
    - The cascade outdates runs. The builder adds "What drives <target>?" at 100 rows or more.
  - **D7.4.**
    - The analysis dropdown with reasons.
    - The setup form from the manifest, with chips struck through and their reasons, a warning when a chip is put back in, the scope chip and More.
    - Live progress, the importance view with a partial-dependence mini chart per factor, the model card drawer, Outdated with Re-run, and "Plain chart (SQL)".
  - **D7.5.**
    - `repro.py` per run; the model card's numbers come from executing it.
    - The notebook emits analyses via their runs. The execution test matches the model card exactly (the requirement is within 0.5 points).
  - **Browser check** on the sample (API on :8001 with its own `data/day7`): Titanic's driver widget shows Gradient boosting at 80.4% against 78.0% for sex alone, with sex, then age, ticket and pclass. Boat, body and name are excluded with their reasons.
- **Not done:**
  - D7.3, the answerers (`ask_why`, `ask_stats`, `ask_model` with explain-row, `ask_meaning`, `app_help`).
  - The confusion and ROC views, and "Who did it get wrong?" (D7.4). They need out-of-fold predictions, which came with `predict` (cut 7).
  - Calibration (TRD §7.5 step 7), and the time-series and group splits.
- **Decisions made while you were offline:**
  - **No SHAP.** It isn't a dependency, and permutation importance is model-agnostic and reproduces in the notebook with scikit-learn alone.
  - **No calibration.** It only matters for served probabilities, and no predictions are served (cut 7).
  - **JSON artifacts.** Run results are JSON (`results/importance.json`, `partial_dependence.json`), because pyarrow isn't a dependency.
  - **Analyses ignore the dashboard filter.** With a filter active, the setup's "Only the filtered rows" folds it into the run's own rows, so the cache key and the notebook see it.
  - **A chart becomes the analysis.** Running "What drives this?" from a chart turns it into the analysis titled "What drives <target>?". "Plain chart (SQL)" (widget Undo) brings the chart and its title back. The narrator wrote a poor card while the analysis still had the chart's title.
  - **Late runs settle themselves.** A run that finishes after the data changed checks itself like the cascade would (cascades skip runs still going). The notebook test caught a run left done on stale data.
  - **Undo tells the story again.** Widget Undo now re-tells the widget's story.
  - **`POST /widgets/{wid}/rerun` added** for the Outdated footer (TRD §4.8).
- **What needs you:**
  - No PRD change was made. Within cuts 4 and 7, PRD ML-2's method selector, ML-4, ML-5's method checks, ML-6 and ML-7 are cut by plan §5 as approved. ML-1 to ML-3 and ML-8 to ML-10 are met for `driver_analysis`.
  - The P0 items that the cuts don't remove and that are still open are D7.3 (the answerers) and D7.4's confusion and ROC views and "Who did it get wrong?". If they won't be built, dropping them needs a PRD change by you (plan §2.0: nothing is left to cut).
- **Token Factory:** Day 7's live use was the browser check: one curation, 10 narrations and 5 overviews on Nemotron Super, about 12k prompt and 22k completion tokens, well under $0.05. Tests use recorded fixtures.

## 2026-10-25 (Sun): overnight wrap-up, Days 5–7

- **Done** (each slice tested, documented, committed to `main` and pushed; Render deployed by hand after each):
  - **Day 5, within cut 5** (`79f07eb`; plan D5.1–D5.7 all checked).
    - The CSV tab: the paged Glide grid with header type, missing share and mini histograms; the changed, flagged, invalid and unsaved marks; cell edits, add and delete row, sort, Find, Save with conflicts and Discard; Clean with AI; Restore for quarantined rows; the Download menu.
    - The Changes panel with step detail and Undo. Undoing an earlier step replays the later ones (D5.5).
    - Cascade v0: every commit re-queries the dashboard's widgets, debounced, with its progress line and toast.
    - Notebook export v0 (D5.6): job, cache, preview, download, dialog, Ctrl+Shift+E. It's tested with a real kernel in pytest. `sherlock eval notebook --sets all` ran each of titanic3, sales_dated, wide_messy and reviews_text in a fresh venv after an edit and an undo with replay, and each rebuilt its version exactly (77–93 s per file).
  - **Day 6, within cut 6** (`52cc5eb`, then the review fixes in `00fbe36`; plan D6.1–D6.6 all checked).
    - Fact sheets in code per view type with their provenance, the chi², Kruskal-Wallis and Kendall tests, `verify`, relations, the narrator with the chip-only checks, the overview, and the `stories` job streaming `card.updated`.
    - The cascade with column-level dependencies: only the widgets and cards that read a changed column update. Edited cards get a suggestion, and "Ask first" marks cards outdated.
    - The story panel: cards, chips with the evidence drawer, related chips, two-way hover linking with the spotlight, badges, the TipTap editor with chip nodes and the `/` picker, suggestions, Ask why.
    - Custom visx histogram, heatmap, box plot and scatter, with builder candidates for them.
    - Story cards in the notebook, with evidence and unverified footnotes.
    - **Live exit check on Render, scripted against the API.** The sample built 7 widgets and the model wrote 8 cards 48 s after upload. Every chip matches its fact. Editing one `fare` cell cascaded in 22 s and changed only the 3 cards that read `fare`. The review fixes (no stuck `updating` cards, numbers in words rejected, both heatmap categories named) were deployed and are live.
  - **Day 7, ML within cuts 4 and 7** (`f0e13bc`; details in the entry above). `driver_analysis` with Auto, the runs API, the analysis UI, the model card and `repro.py`, and runs in the notebook.
  - **Final `uv run sherlock eval ask`** (live Token Factory, 2026-10-25 after `f0e13bc`): **34 of 35**, up from 32 on Day 4, with 0 unsourced answers and a median of 11.8 s per answer.
    - The one miss: "How many orders are there?" on `sales_dated.csv` answered "This file has no column that answers that.", although the file has `order_id`.
    - **Re-run after `cfb4b08`** (the ML answerers and per-tab intents; on `2a06f8b`): **33 of 35**, with 0 unsourced answers and a median of 11.7 s. "How many orders are there?" now passes.
      - The two misses are "Revenue by region" and "Revenue by product" on `sales_dated.csv`. In both, the generated SQL put the measure first (`revenue, region`). The eval keys each table on its first column, so the right values were keyed by revenue and didn't match.
      - The answers themselves were right (Central 104,063.01, East 198,168.56, …). On the first run, the same two questions passed with the category first.
      - So this is SQL column order varying between runs, plus a scorer that assumes the key comes first; it isn't a regression from `cfb4b08`.
  - **`broken_latin1.txt` in the fresh-venv notebook eval** (2026-10-25, later). `sherlock/eval/notebook.py` now passes per-file import options, as the import preview would (`IMPORT_OPTIONS`: `{"header_row": 3}` for this file). `all` is now the plan's five-file set.
    - `uv run sherlock eval notebook --sets broken_latin1.txt` (Latin-1, `;`, header on row 3): 2 steps and 6 widgets. It ran top to bottom in a fresh venv and rebuilt its version after the undo with replay (86 s). No fix was needed (TRD §14).
  - **Follow-up: the rest of Day 7** (`cfb4b08`, the same morning, within cuts 4 and 7).
    - **D7.3, the answerers.**
      - `ask_stats`: the test is chosen by the column types (Welch's t and Mann-Whitney, Kruskal-Wallis, chi-square, Pearson and Spearman), with effect sizes.
      - `ask_why`: answers from the driver run, cached or waited for.
      - `ask_model`: answers from the model card, and "who did the model get wrong?" answers with those rows.
      - `ask_meaning`: what the data says, with general knowledge in a labelled box.
      - `app_help`: retrieval over `docs/help/*.md`.
      - **Tool exposure by tab:** `create_widget` only on the Dashboard tab, `ask_story` only on Flow.
      - Every number is a chip on a computed cell.
    - **D7.4.**
      - The out-of-fold predictions are saved with each classification run. From them come the confusion matrix and ROC views (a view switcher on the widget and both in the model card), and "Who did it get wrong?", which opens those rows in the CSV tab via `?rows=`.
      - Checked in the browser on Titanic: 710 and 343 right, 256 wrong, AUC 0.859, "256 rows selected".
    - **Tests and fixtures.** The new model calls were recorded live into `chat_titanic.json`. 310 API tests pass, as do 47 web tests and the build.
  - **Live site:** `/healthz` ok (database, `/data` writable, SQLite lock, LLM reachable). Render deploy `dep-dbf0r8ivcj2c73eeiml0` of `f0e13bc` is live, and the served `assets/index-BAuGThCo.js` is the same file a fresh local `pnpm build` of `main` produces.
- **Not done:**
  - The "How many orders" miss above: counting rows when the user names an ID column. It passed on the re-run, so it may be model variance rather than a fixed bug.
  - The ask eval's group-by check keys each table on its first column, so a right answer whose SQL lists the measure first fails (two misses on the re-run). The fix is to match on whichever column holds the expected keys; it hasn't been made.
    - **Fixed later the same day:** the check now tries every column as the key, with a unit test for the flipped table (`test_eval_checks`) and TRD §8.1's scoring note. It wasn't re-run live, so 33 of 35 stands as the last live score. The values the re-run printed for those two questions match the expected ones, so by this rule it would likely have scored 35 of 35.
  - Answer time: the median is still 11.8 s against the ≤ 4 s target to the first block (TRD §13).
  - **Day 5:** the export dialog's Save and export button (the dialog says to save first) and the Flow palette's Export entry (D8). The grid's range paste wasn't verified (TSV paste is cut 5).
  - **Day 6:** relations don't yet weigh correlation between measures or ML dependencies (TRD §7.4). Gauges render as a KPI tile.
  - **Day 7:** D7.3 (the answerers) and D7.4's confusion and ROC views and "Who did it get wrong?"; see "What needs you".
    - **Follow-up (`cfb4b08`):** these are now built, so Day 7 is complete within cuts 4 and 7.
    - Still cut: `predict`, the predictions table, predicted cells and explain-row (cut 7), and the method chooser, coefficients, residuals and Compare with Auto (cut 4). `ask_model` says so when asked about one row.
    - `sherlock eval ask` wasn't re-run after the route prompt began listing intents per tab. Its routing fixtures and the chat tests pass.
    - The follow-up's live use was about 15k prompt and 20k completion tokens on Super, plus 10 Nano routes: about $0.03, which brings the night to about $0.28.
    - The eval re-run after it used about the same as the first eval, roughly $0.08 (its throwaway database is deleted when it finishes, so this is an estimate). That brings the night to about $0.36. The latin1 notebook eval makes no model calls.
  - Still open from earlier days: checkpoints for re-queued jobs (D8.6), error boundaries (D8 quality of life), and header detection for a preamble that uses the data's delimiter.
- **Decisions made while you were offline:**
  - **Glide passed its 1-hour check, so there's no fallback.** Editing, range selection, theming from the CSS variables and 500,000 paged rows all worked (`FEEDBACK.md`). Range paste wasn't verified, but cut 5 removes it.
  - **The notebook mirrors the app's DuckDB round trip** (`keep_types` after the load cell and each edit batch, `store_step` after each cleaning step). The app reads every version back through DuckDB, which decides the types, so the notebook does the same to rebuild identical values and dtypes (TRD §7.7).
  - **Scoped clean steps store `keep_outside_scope` in their `notebook_code`.** Then a replay in the sandbox and the notebook apply the same row and cell scope the Cleaner did (TRD §7.7, Schema §2.5).
  - **The builder's SQL breaks ties deterministically** (equal values ordered by the category). The notebook test compares the notebook's results with the app's, which needs a stable order (TRD §7.3).
  - **Narration runs on Super, not Nano.** Live, Nano typed chip markup into text runs, ran sentences together and timed out twice in thirteen calls. Super wrote valid cards, sometimes after one repair. This is the same move chat compose made on Day 4 (TRD §7.4, `FEEDBACK.md`).
  - **A `MARKUP` check on text runs** (`stories/narrate.py`). It rejects braces, brackets, `chip`, `column:` and `value:` inside a text run, because strict decoding can't stop JSON inside a string and the no-digits check misses markup. After the review, numbers spelled out in words are rejected too (live, Super wrote "six").
  - **The target counts as a shared column for relations.** Two widgets that both read the target are about the same outcome, so they link (TRD §7.4).
  - **CSV Find shows only the matching rows,** with the matching cells highlighted, until the find bar closes, so every match is visible without paging through the grid (App Flow §8.3).
  - **Shiki wasn't added.** Step code shows in a plain mono block (UI/UX brief §5.7): the highlighter's grammars and engine would add bundle weight for a cosmetic gain.
  - **The CSV tab is lazy-loaded** (`React.lazy`), like the dashboard, so Glide loads only when the tab first opens and first load stays near 488 kB. The story card editor (TipTap) is lazy as well. Added today to TRD §2's code-splitting note, which named only the dashboard and the charts.
  - Also: three Token Factory `529 System is overloaded` replies in one stories job were absorbed by the retry with backoff (`FEEDBACK.md`).
- **Token Factory spend:** an estimate, from `llm_calls` since the run began (2026-10-25 05:18 UTC). The sources are `api/data/sherlock.db`, `api/data/day7/sherlock.db`, the three `sherlock-stories-*` throwaway databases in the system temp folder, and the final eval's throwaway database. That database was deleted when the eval finished, so its share is estimated from Day 4's per-question token counts.
  - **Measured on disk:**
    - Super: 60 calls, 37k prompt and 82k completion tokens, about $0.09 at $0.30 per 1M input and $0.90 per 1M output.
    - Nano: 13 calls (the narration trial), 6k prompt and 30k completion tokens, about $0.01 at $0.06 per 1M input and $0.24 per 1M output.
    - Ultra: no calls tonight. There was no cleaning run.
  - **Estimated:**
    - The final eval: 35 Nano routes plus SQL, compose and two dashboard builds on Super, about 70k prompt and 70k completion tokens, roughly $0.08.
    - The live checks on Render (Day 6 exit and review, Day 7): roughly $0.05.
  - **Total: about $0.25**, well under the $5 cap. Token Factory's console has the exact figure.
- **What needs you:**
  - **The stray API on :8000.** Another session's API (older code, same `api/data`) is still running and claims job kinds it doesn't know: it claimed and failed a cascade job tonight. Stop it, or point it at its own `DATA_DIR`. Until then, local runs use :8001 with their own data directory.
    - **Done later the same day, on the owner's instruction:** the uvicorn on :8000 (`sherlock.main:app --port 8000` from `api/.venv`) was stopped while no job was queued or running. Port 8000 is free.
  - **CI is blocked by GitHub billing.** No overnight commit ran in GitHub Actions; tests ran locally and Render was deployed by hand. Fix the billing, or keep deploying by hand.
    - Still yours: billing is an account setting only you can change.
  - **PRD-level question from Day 7: resolved by the follow-up (`cfb4b08`).** Everything below is now built, so no PRD change is needed.
    - As first asked: the P0 items the cuts don't remove that were still open were D7.3 (`ask_why`, `ask_stats`, `ask_model`, `ask_meaning`, `app_help`) and D7.4's confusion and ROC views and "Who did it get wrong?". The confusion views needed out-of-fold predictions, which had come with `predict` (cut 7).
    - The choice was to build them on Day 8, or to drop them through a PRD change by you (plan §2.0: nothing is left to cut). They were built, so there's nothing to decide.
  - Review the overnight `docs/` additions: the as-built notes in TRD §7.3, §7.4 and §7.7, App Flow §7.4, §8, §9, §11 and §16, UI/UX brief §4.4–§4.7 and §5.6–§5.9, and Schema §2.5 and §2.13.
- **Decision for tomorrow:**
  - Day 8 within cuts 2, 3 and 9:
    - the Flow canvas with "make sense of this" (no rewrite proposals, no "take it toward X", no direction nodes);
    - chat completion;
    - the quality-of-life list without the `?` sheet;
    - checkpoints and the purge job;
    - eval ask grown to about 50 questions, with the grounding eval;
    - and D7.3 and the remaining D7.4 views if you keep them P0.
  - Then the feature freeze. Day 9 ships.

### 2026-10-25 (afternoon): fixes from the Day 1-4 reviews

- **Done** (on the owner's instruction: the findings that needed no product decision; each has a test and its doc note):
  - **A rate above 100%** (Day 4 F1, Rule 4). A two-valued number not coded 0/1 (1/2, say) was averaged as it was, so its "rate" was 140%. Now it counts its positive value (TRD §7.3).
  - **`contains` widget filters** (Day 4 F15). `%` and `_` matched as wildcards, so `contains "%"` matched every row. They're now escaped as in the rows API (TRD §6.3).
  - **"How do you know?"** (Day 4 F3). It showed the global filter even on the chart filtered by its own category, whose data doesn't apply it. The widget and the drawer now share `appliedFilter` (TRD §6.3, App Flow §7.3).
  - **`?widget=:id`** (Day 4 F12). The dashboard now scrolls to the widget, flashes it and drops the parameter, so chat's "Open the widget" works (App Flow §1).
  - **The DuckDB connection cache** (Day 2 M4). Evicting an older version closed its connection under a running query. An evicted connection now stays open until its last user lets go (TRD §3.2).
  - **Undo and hand-edit protection** (Day 2 M5). Undoing a later edit of a cell removed the protection an earlier edit had given it. The cell is now protected again under the earlier edit (Schema §2.7, TRD §7.8).
  - **Cleaner prompt hygiene** (Day 2 M7, TRD §3.5). Column names, earlier decisions, the diagnosis, the fix's code and the effect now sit inside each template's one `<data>` block, with `</data>` defused (TRD §7.2).
  - **The typing step** (Day 2 M2).
    - It no longer casts a float with more than 15 significant digits, a non-UTC offset, or fractions finer than a microsecond. Before, those silently lost information.
    - Its verifiers are computed from the written output instead of being fixed `pass` strings (TRD §7.1).
    - A first version of the check ran the statement a second time and made `wide_messy.csv` time out in the sample test. It now reads the Parquet the commit already wrote (7.5 s for that file).
  - **The OpenAPI client** (Day 2 M3). It was 24 routes behind (exports, cards, runs and more) and has been regenerated. `api/tests/test_openapi.py` now fails when it drifts (TRD §3.1).
  - **Checked in the browser** (local API on :8001 with its own data, the sample dashboard, no model calls).
    - With `sex = female` set, "Survival by Sex" asked for its SQL with no filter, and the Survival Rate KPI's SQL had `("sex" = 'female')`, matching its 466 rows.
    - `?widget=` scrolled to "Survival by Sex" and highlighted it.
- **Still open from the reviews, waiting on the owner's decisions:**
  - per-user budgets reset by dropping the cookie (Day 1 #1);
  - ragged CSVs importing as one column (Day 2 H1);
  - the Cleaner committing a step that quarantines most rows, or that its critic rejects (Day 3 H1, H2);
  - `export.csv` formula escaping, and the `nvidia/` prefix rule.
- **Not done:** keyboard access to click-to-filter and the widgets, the slide-over focus trap, reduced motion for charts, the 20-widget warning outside the drawer, wide-file candidate capping, compose repairs, and the smaller review items (`reviews/day-*.md`).

### 2026-10-25 (afternoon): the owner's four review decisions, applied

- **Done** (the owner chose the recommended option for each; each has tests and its doc note):
  - **Budgets that a dropped cookie can't reset** (Day 1 #1).
    - An app-wide daily ceiling on all users' model tokens (`APP_TOKEN_BUDGET`, default 10M per UTC day, summed from `llm_calls`).
    - At most 30 new users an hour per client IP (`NEW_USERS_PER_IP_HOUR`). The IP is the last `X-Forwarded-For` entry, which a client can't forge.
    - PRD §9 Security, TRD §3.5 and §15, App Flow §18.
  - **Ragged CSVs** (Day 2 H1).
    - A delimiter guess that barely appears in the lines is overruled.
    - Files whose row lengths defeat DuckDB's sniffer are read with explicit text columns.
    - Rows with extra fields keep the values in `col_N` columns and are quarantined, never dropped. The notebook's load cell does the same and rebuilds the version (a kernel test).
    - PRD LOAD-3a, TRD §7.1, Schema `import_options_json`.
  - **The Cleaner's damaging steps** (Day 3 H1, H2).
    - A new hard verifier, `quarantine_scope`, fails a step that quarantines more than 2 × its issue's count + 10 rows.
    - A step the critic says "changed something it shouldn't" is now skipped; its concerns alone still don't block.
    - PRD CLEAN-4a, TRD §7.2.
  - **`export.csv`**: text cells starting with `=`, `+`, `-`, `@`, a tab or a CR get a leading `'`, and typed columns export exactly (PRD CSV-12a, TRD §4.3).
  - **Rule 2**: chat roles must start with `nvidia/` as well as name Nemotron (TRD §3.5).
- **To confirm on the live site:** how many `X-Forwarded-For` hops Render sends. Each new user logs a short IP hash and the hop count. If a normal request shows more than one hop, the last entry is a Render proxy, not the client, and the cap would group every visitor together. Then the setting needs the other entry.
  - **Checked live the same afternoon.** A plain request arrives with two hops: the client, then a Render proxy whose address varies. The first deploy keyed on the last entry, which would have lumped visitors together by proxy node. It now takes the entry before the host's `TRUSTED_PROXY_HOPS` (1), with a test, and the logs showed no INFO lines until `sherlock.*` got a handler.
- **Cap raised (later the same afternoon, owner's instruction).** `NEW_USERS_PER_IP_HOUR` now defaults to 300, because 30 ran out while testing by hand. The deploy restarts the process, which empties the in-memory window.

### 2026-10-25 (evening): Days 8 and 9, within cuts 2, 3 and 9

- **Done** (each slice committed and pushed; the plan's §2 Day 8 and Day 9 notes list what each item covers):
  - D8.1–D8.2: the Flow canvas (API and React Flow tab) with "make sense of this" writing a synthesis card live on Nemotron Super.
  - D8.5: chat proposals for cell edits and Clean with AI (Approve and Reject), `update_widget` with Undo, multi-step plans, the running summary, export from chat.
  - D8.3: error boundaries, the offline banner, card delete with Undo, scroll memory.
  - D8.6: checkpoints with resume, the purge job, the Playwright flow (`pnpm e2e`).
  - D8.4: eval ask at 50 questions and the grounding eval, both run live; fixes from their misses.
  - D9.1: the cached sample (a seed built once with the real models, cloned per user in 0.2 s).
  - D9.2–D9.5: deployed by hand to Render; `scripts/live_check.py` passed on the public URL (sample, isolation, rate limit, a sourced answer, the cascade); the five-file notebook eval passed in fresh venvs; README, THIRD_PARTY.md and the example notebook.
  - Bugs found on the way, each with a test: first visits made several anonymous users at once (the library stream listened to the wrong one); an analysis widget could miss its story card; the overview's derived facts couldn't be re-checked; causal words "influences/affects/impacts" got through.
- **Not done:**
  - User tests and the baseline comparison (`docs/USER-TESTS.md`): they need three people who haven't seen Sherlock. The owner's, for Day 10 morning at the latest, since the README and Devpost cite them.
  - Done later the same evening: `docs/architecture.png` (rendered by `scripts/architecture.py`) and `docs/USER-TESTS.md` with both protocols and the Sherlock half of the baseline measured live (about 31 s and 4 steps for three questions, all three traced to their SQL; the under-18 count is 84 on the cleaned sample against 81 on the raw file, explained by the age step). The cold-start sessions and the by-hand timings stay open: they need real people.
  - From the earlier reviews, still open: keyboard access to click-to-filter, the slide-over focus trap, reduced motion in charts.
- **Decision for tomorrow (Day 10):** record the video from plan §9 on the live site (the sample is instant now; moment 6 filters instead of brushing, moment 7 uses "Make sense of this"), write the Devpost text from README sections, finalize FEEDBACK.md, submit. No feature work: the freeze holds, bugs only.

### 2026-10-25 (night): the demo-path honesty fixes and the seed rebuilt

- **Done** (owner's instruction: fix Day 7 F1 and F4, Day 8 F1, Day 6 F2 and F3, then rebuild the seed; code, tests and docs in `f064fd9`):
  - **Grouped folds** (Day 7 F1). A repeating ID-like column (target-encoded, values at least a quarter of its rows) keeps its rows in one fold. On Titanic that's `ticket`: the analysis no longer credits it, and its verdict is now "sex alone does nearly as well (78.1%)" against the model's 78.2%, where the leaky folds said "beats the best simple rule by 2.8 points" with ticket as driver three. `tests/test_answerers.py` expected the old verdict and now expects the honest one.
  - **Words around chips** (Day 7 F4), **synthesis claims** (Day 8 F1), **chat value labels** (Day 6 F2) and **card-edit chips** (Day 6 F3), each with a test (TRD §7.4, §7.4.1, §8.1, §4.6).
  - **The seed, rebuilt with the new `--keep-data`** so the cleaned data, steps and widgets (v4, the README's and USER-TESTS' numbers) stay as they were: the analysis ran again with grouped folds, every card and the overview were told again, and the synthesis written again. Two builds (15 Super calls each, about 34k and 33k tokens; the first one's analysis card read "with importance sex 1.00", which a reworded prompt rule fixed), then one synthesis rewrite after the second build's synthesis fell back to the cards' headlines (the seed script now retries it up to three times). Every chip matches its fact and no text run has a digit.
  - **Synthesis fallback rate checked.** Four live "make sense" refreshes on the new seed: three written by the model; the misses were a number in words and chip markup in a text run, not the new derivation or comparison checks.
  - **The example notebook** (`docs/examples/titanic3-v4.ipynb`) re-exported and run in a fresh venv: 29 code cells, "Rebuilt version 4", and the run cell reproduced the model card (accuracy 0.782, sex 1.00, pclass 0.0998, ticket 0).
- **Token Factory spend:** about 100k Super tokens (two seed builds, the synthesis rewrite and the four checks), roughly $0.07.

### 2026-10-25 (night): the docs, the reviews and the worktrees, trimmed

- **Done:**
  - `reviews/` is gone from the tree: the nine Day 1–9 reports (190 KB of Markdown) with their 78 screenshots and 3 timing files (3.7 MB in all). Every finding still open after `f064fd9` is now in one list, `docs/BACKLOG.md`, with the Day 10 submission steps and the owner's pending decisions. The reports, with their evidence and transcripts, stay in git history (`git show 9051876:reviews/day-7.md`).
  - The nine review worktrees (`.claude/worktrees/review-day*`) are unregistered from git. All were merged into `main` with nothing uncommitted.
  - Stale doc lines brought up to date:
    - TRD §2 has an as-built note for the layout (Day 7 F15).
    - TRD §7.7 and §8.1 no longer read as if `repro_render.py`, `ask_story` and `update_widget` were still to come, and §7.4 gives the whole causal word list (Day 8 F11).
    - Plan: the header has today's status, §3's finished lines are ticked (cut parts don't hold a line open), and D7.1 and D7.5 name the modules as built.
    - CLAUDE.md lists the backlog, the log and the user tests, and names `pnpm e2e` for the end-to-end flow (the script builds the app first).
    - `docs/official_page.md` says where the live rules differ: the video must be under three minutes.
  - Kept: the six specs, this log, `USER-TESTS.md`, the rules and rubric, `help/` (shipped in the image), `examples/`, `architecture.png`, `screenshot.jpg`, and `Sherlock UI examples-png/`, which UI/UX §1 makes part of the spec.
- **Not done:** the worktree folders are still on disk, held open by the idle review sessions; archiving those sessions frees them.
- **Decision:** open work lives in `docs/BACKLOG.md` from now on. A fix removes its line in the same commit.

### 2026-10-25 (night): every doc checked against the code

- **Done** (owner's instruction: the docs must match what's built; cut with care):
  - Each doc was read against the code at `e68327f`: PRD, App Flow and the help pages, UI/UX brief, TRD (§1–4, §5–7, §8–15), schema, plan, README, `THIRD_PARTY.md` and `USER-TESTS.md`.
  - Wrong statements were corrected in place: stale "not yet" notes, routes and fields, defaults, model roles, copy, commands. Specs the code doesn't meet stay as written, with a marker: "Removed by cut N" or "Not built yet (docs/BACKLOG.md)". No requirement, acceptance criterion or priority was dropped (the PRD's 98 IDs and labels are unchanged).
  - Every gap the pass found where the code falls short of a doc is in `docs/BACKLOG.md`, tagged with the doc section.
  - The help pages now describe the real UI; the retrieval tests pass. `tests/test_db.py` passes against the schema doc.
- **Not done:** the gaps themselves (code), and the owner decisions in BACKLOG §2.

### 2026-10-25 (night): the cleaning plan, part 1 (plan, ticks and the offer)

- **Done** (owner's decisions of 2026-10-25, PRD CLEAN-1 and the new CLEAN-8a):
  - **The cleaning plan.** Clean with AI no longer starts at once. Sherlock's code detectors diagnose the current version and the plan lists every fix in modules, all ticked (`cleaning/plan.py`, `clean_plans` in migration 002, `POST /datasets/{id}/clean/plan`, `GET`/`PATCH`/`DELETE /clean-plans/{pid}`). The user unticks fixes or whole modules, then Start cleaning (`POST /clean` with `plan_id`, a frozen copy in the job's params). Unticked fixes are skipped with no model call, "not in your plan". A plan made before an edit or undo is merged onto the current version, ticks kept.
  - **The offer** keeps its top three and loses the "All n issues" table; its buttons are Clean with AI and Clean it myself (the old Use as is, which now opens the CSV tab). Go step by step moved into the plan's Mode row, disabled (CLEAN-10 is still P1).
  - **The CSV tab**: Clean with AI opens the plan in the right panel in place of Changes, with the scope; the popover wrapper is gone (the package stays for the job tray). The grid is read-only with a banner while the status is `cleaning` or `building` (a backlog line, now removed).
  - **Why uploads skipped the offer** (owner's report): `after_upload: always` started a clean unattended, and nothing on screen said why. Now `always` ("Open the cleaning plan") makes a draft plan and stops at the offer, and Discard goes back to it; `never` ("I'll clean it myself") marks its build `automatic`. Both screens say which setting opened them, with a Change link to Settings at that field.
- **Not done:** part 2: rewriting a fix in plain words, adding steps, and editing the plan from chat (CLEAN-8b).
- **Decision:** the plan's numbers come from the detectors only (Rule 2); the model's per-issue diagnosis still runs during cleaning.

### 2026-10-25 (night): the cleaning plan, part 2 (editing, your steps and chat)

- **Done** (PRD CLEAN-8b, owner's decisions of 2026-10-25):
  - **Rewrite a fix** (✎ in the plan, Reset back to Sherlock's wording) and **add steps of your own** (a column or the rows, and an instruction; × removes them). They run first, under every hard check; the diagnosis can't end them as "leave as is", and at low confidence they commit with a flag ("kept because you asked for it") instead of being skipped. A user's step may quarantine at most a fifth of the rows, since it has no issue count to cap it.
  - **The prompts** carry the instruction inside their one data block; a user's step's issue line is a fixed phrase, so none of the user's text sits outside it. The step's decision records `asked`, which Changes, the report's new "Your steps" and the exported notebook show.
  - **Chat edits the plan** (`edit_plan`, schema `PlanEdits`): with a plan open, "don't touch cabin" or "also trim spaces in name" changes it at once, and the reply is written by code. Items are named to the model by ref (`f1`, `f2`, …), so the model never handles IDs.
- **Checked:** the Cleaner without a plan is unchanged: `sherlock eval corruption` against Nemotron recovered 92.1% (titanic_clean), 95.9% (sales) and 98.1% (hr) of damaged cells with 0% harm and 0% row loss, in line with D3.3's 92–97%.
- **Not done:** live runs of user steps against Nemotron (the tests use recorded replies); "Ask me before each fix" stays P1 (CLEAN-10).

### 2026-10-25 (late night): the worktrees gone, the docs checked again after the cleaning plan

- **Done** (owner's instruction: keep the docs, reviews and worktrees only where they're needed, and make the docs match what's built; cut with care):
  - The nine Day 1–9 review sessions are archived, `.claude/worktrees/` is deleted, and the nine `claude/review-day*` branches are deleted (all were merged into `main`). `reviews/` was already gone (its findings are in `BACKLOG.md`).
  - Every doc was read again against the code at `b7877dd`, after the cleaning plan's two commits. The fixes:
    - The After upload options, the offer's two buttons and the plan's Discard are now named as they are, in the TRD (§4.4, §7.1, §14), schema, UI/UX brief, App Flow and help pages.
    - The plan's API details are complete: `plan.updated`'s emitters, the PATCH op limit, `instruction`, `notes` and the `409` text. `ChatContext.plan_id`, the `undo_widget` and `open_model_card` actions, and `Source.kind` `general` are in TRD §4.9.
    - TRD §2 lists the real `scripts/`, `cleaning/plan.py`, `report.py`, `docker/entrypoint.sh` and the web folders. The Render plan is `standard`. CLAUDE.md no longer lists SHAP.
    - The README, THIRD_PARTY.md and the plan are fixed too: the P0 gaps outside the cuts, the unused tooltip and gradient packages, the cleaning plan as a post-freeze exception, and migration 002.
  - Sentences that only told what used to be true were dropped from the specs: "before the Day N review…", "not yet at D4.2, built since", and the popover the plan replaced. The history stays in this log and in git. No requirement, ID or priority changed.
  - `BACKLOG.md`: the sandbox temp test line is removed (fixed in `15dcccc`). Five lines now point at the cleaning plan's code. New lines: two cleans that skip the plan (an owner decision), small icon-button targets, a Discard edits that doesn't confirm, and two unused packages.
- **Kept:** all the docs. Each one is read by CLAUDE.md, the README, the image (`help/`) or the submission (`examples/`, the screenshots, the rules and rubric, `Sherlock UI examples-png/` per UI/UX §1).

### 2026-10-25 (late night): every clean goes through the plan

- **Done** (owner's decision, PRD CLEAN-1: nothing is cleaned without Start cleaning):
  - The new-rows toast's **Clean them** now opens the cleaning plan in the CSV tab's right panel, scoped to the saved rows ("The 2 rows you just added"), instead of starting a clean (`POST …/clean/plan` with `scope`). `useCleanScoped` is gone.
  - Approving chat's **"clean these rows"** (`clean_selection`) opens the plan with the proposal's selection ("The 3 rows you asked to clean") and answers the `CleanPlan`, not a `Job`. The toast says to look it over, then press Start.
  - The plan stores its scope (`clean_plans.scope_json`, migration 003), so a reload can't widen it to the whole file. The panel adds a first, picked radio for those rows, and in the centre layout a line "Only the n rows …". A whole-dataset scope clears it.
  - Docs: PRD CLEAN-8a, App Flow §8, §10, UI/UX §5.3a, TRD §4.4 and §8.2, Schema §2.15 and §2.21, and the help pages. The BACKLOG decision line is removed, and `clean_selection` no longer counts as a job started without the rate limit.
- **Checked:** `uv run pytest`, `pnpm test` (four new plan tests: the toast, the approval, the side panel's preset, the centre line), the type checks and `pnpm e2e`.
- **Not done:** a live run against Nemotron; neither path calls the model before Start.

### 2026-10-25 (late night): the specs read as the app, not the build diary

- **Done** (owner's choice of two cleanups):
  - `docs/Sherlock UI examples-png/` is deleted (6 MB, the 13 pre-build boards). UI/UX §1 keeps the design canvas link and names the commit that still has them; `docs/` is 1.2 MB.
  - The six specs lost their build history: dates and D-number tags on "As built" notes, "Day N review Fx, fixed …" provenance, "Before, …"/"used to …" stories, live-run anecdotes and superseded eval runs (TRD §14 keeps the latest numbers per eval). About 14 KB went, most of it from the TRD.
  - Kept: every heading, requirement ID and P-label, table, code block, `CREATE TABLE` column, "Removed by cut N" and "Not built yet" marker, and every note where the code differs from the spec. The plan keeps its day-by-day structure and D-numbers, which the other docs cite; this log and git keep the history.
  - Also fixed: UI/UX §2.1's `--changed` row named a corner marker (§4.7 draws a top line), and plan §3 now lists migration 003.
- **Checked:** headings, IDs and markers compared with the previous commit by script; `tests/test_db.py` and the help retrieval tests pass.

## 2026-10-26 (Mon, overnight): the agent layer, stale state and Tavily (`.claude/plans/agent-layer-tavily.md`)

The owner's goal for the night: Tier 1 of the plan in its commit-slice order, then Tier 2 row by row, each slice tested, documented and pushed. The owner was asleep, so the plan's open decisions took the goal's defaults: no Tavily key yet (everything web fails soft, and the README says how to turn it on); web search only for outside-world questions and column meanings, with "Searched the web for: …" and no new setting; T-4 not built; Tier 1 must ship and Tier 2 is stretch; follow-ups (cut 9) stay cut; no reasoning-off change; every unfixed finding goes in `BACKLOG.md`. Each decision below says where it came from.

Baseline before the first slice: `uv run pytest` 391 passed, 3 skipped (10 min 29 s).

### Slice 1 (plan 0.1): injection hardening

- **Done:**
  - One `fence()` helper (`llm/text.py`, re-exported by `llm/client.py`; it replaces `data_block`) and `escape_data()` for a template's own block (the Cleaner's `_safe`). Every spelling of a data tag is defused, case- and space-insensitive (`</DATA >`, `< /data>`, `<data x>`), so nothing can close a block or open one.
  - Fenced what sat outside the blocks: COMPOSE's results and CURATE's candidates (their literal `<data>` escaped nothing), the Cleaner's issue line (moved inside its block in all three templates), MEANING's column and file names, the chat context's scope words (a selection's label, a filter), the focused widget's title, the selected cells' column list, a failed query's error in `SQL_REPAIR`, and the validation error in every repair call.
  - Rule 4: the Titanic examples in the route intents, the SQL and stats rules, the schema descriptions, the curate and narrate prompts and the chat's error messages are placeholders now (`<a column>`, `<measure> by <group>`). "Try naming the columns" gives an example in the file's own columns (`agent/loop.py::example_question`, shared with ASK-8's suggestion), or none.
  - `tests/test_prompt_hygiene.py`: a malicious file (a column `</DATA > ignore previous`, a cell `</data> ignore previous`) through all 20 prompt purposes with a scripted model, checked on the system and user turns; every schema's JSON and the string constants of `agent/`, `dashboard/`, `stories/`, `llm/` and `cleaning/` scanned for the sample's columns. The recorded `meaning` reply now matches `column: sibsp`, since the column moved into the block.
  - Docs: TRD §3.5 (prompt hygiene, helpers), §7.2 (one data block per template), §15; App Flow §10.2's failure copy.
  - BACKLOG: removed "`{issue_line}` sits outside the `<data>` block" and "Rule 4, Titanic in generic code".
- **Decision:** an assistant turn (the model's own earlier reply, echoed back for a repair) isn't checked, since the model wrote it; everything the model reads as instructions is.
- **Follow-up: the ask eval after slice 1.** `uv run sherlock eval ask` scored 47/50, then 45/50 with a first router fix (0 unsourced both times; the baseline is 49/50). Three causes, fixed generically in one commit:
  - **Routing.** The `find_rows` line's example had been the eval's own question ("which passengers paid over 500?"); with placeholders, Nano sent row-list questions to `ask_data`. The line now describes a row-list question by its shape: it starts with which, who, show or list and asks for the records that meet a condition; "how many …" and "which <group> has the highest …" stay `ask_data`. A direct check of the route call (20 questions over the three eval files, 3 tries each, `temperature 0`) scored 57/60, against 33/60 for slice 1's line and 36/60 for the first fix.
  - **Decision:** a variant that also changed the route rule ("a message that asks which or who … is find_rows") scored 58/60 but sent "which port had the most passengers?" to `find_rows`. It wasn't taken: a group question answered as a row list is wrong, while a row list answered as a table is only the wrong shape.
  - **Empty SQL drafts.** Under strict decoding Super sometimes returns `{"sql": "", "answerable": false, "closest": null}`, which fits the schema and was answered "This file has no column that answers that." (three of the 45/50 run's five misses). `SqlDraft` now rejects an empty `sql`, or `answerable: false` without `closest`, so the draft gets the repair. The first wording of the error mentioned the `SELECT 1 AS none` query and nudged a repair into a wrong "unanswerable"; it now asks for the query that answers the question.
  - **Text search.** The row-filter prompt matches each meaningful word of a "mentions …" request on its own (`ILIKE … AND …`), since the text may word it another way. The baseline's one standing miss ("Which reviews mention damaged packaging?", 167 rows) matched the exact phrase and got 0.
  - Tests: `test_llm_client.py` (an empty draft is repaired; an honest unanswerable draft passes, one without `closest` doesn't). Docs: TRD §8.1 (the route line, `ask_data`, `find_rows`).
  - **Eval:** `uv run sherlock eval ask` **49/50, 0 unsourced**, median 9.8 s. Both earlier misses passed. The one miss was "What does sibsp mean?": the general-knowledge sentence named neither siblings nor spouses this time. It passed in both earlier runs tonight (model variance in the `meaning` call).
- **Gate:** run once for slices 1–4, the router fix and the cleanup merge together, at `781dc6e` (see slice 4): `uv run pytest` 413 passed, 3 skipped; `corepack pnpm test` 88 passed; `corepack pnpm e2e` 1 passed. Pushed.

### Slice 2 (plan 0.2): cut-off replies

- **Done:**
  - `Completion.finish_reason` from the transport (`OpenAITransport`, and fixtures with an optional `finish_reason`). A reply cut off at its cap (`length`) is asked again once with twice the cap, at most 8,192 tokens, instead of going to the repair call with the same cap; the cut-off attempt is logged with `ok = 0` and "cut off at N tokens". A reply still cut off after that raises `StructuredOutputError` without a repair, and the caller's fallback applies.
  - The thread summary's cap went from 600 to 1,500 tokens (reasoning stays on: TRD §3.5 lets only `route` turn it off).
  - `strip_reasoning` drops an unterminated `<think>` and everything after it, as its docstring already claimed.
  - Tests (`test_llm_client.py`): `length` then `stop` makes two calls with caps 1,000 and 2,000 and no repair message; the cap stops at 8,192 and a reply still cut off isn't repaired; `complete` without a schema does the same; an unterminated `<think>` is stripped.
  - Docs: TRD §3.5 (traces, `Completion`, cut-off replies) and §8.1 step 1. BACKLOG: the `strip_reasoning` half of the D2 LLM client line is gone; the `embed` half stays.
- **Gate:** run once for slices 1–4, the router fix and the cleanup merge together, at `781dc6e` (see slice 4): `uv run pytest` 413 passed, 3 skipped; `corepack pnpm test` 88 passed; `corepack pnpm e2e` 1 passed. Pushed.

### Slice 3 (plan 0.3): one shared model gate, the deadline, and refused requests

- **Done:**
  - **One gate per role**, process-wide (`llm/client.py::gate`, a `BoundedSemaphore` per role): `LLM_CONCURRENCY_LARGE`/`MEDIUM`/`SMALL`, 2/6/4. The per-request clients of chat, jobs and the stories pool share it; a slot is held only for the request, not during backoff.
  - **Retries:** the 2/4/8 s backoff is jittered to 80–120%, and a 429's `Retry-After` is honoured when longer (one past the 120 s cap gives up at once).
  - **A refused request** (a 4xx other than 429) fails at once as `LLMRequestError` (`502 llm_request_failed`, "…trying again won't help"), a subclass of `LLMUnavailable`, so every fallback still applies. New error code in `errors.py` and TRD §4.
  - **The deadline:** `CallScope.deadline` bounds attempts, the HTTP timeout and retry waits (`DeadlineExceeded`, "This answer ran out of time."). A chat message's scope gets `started + 90 s`; a step that hits it ends the plan with the usual "I stopped early" note and compose still runs on what was found.
  - Tests: 20 threads per role through per-call clients never pass 2 (large) or 6 (medium) in flight; `Retry-After: 3` waits 3 s; a 400 makes one call and raises `LLMRequestError`; `OpenAITransport` maps a 429 (with its header), a 400 and a 503; the deadline stops at 40 s of a 40 s budget and a passed deadline makes no call; a chat message with no time left makes no model call. The two exact-backoff tests inject the jitter.
  - Docs: TRD §3.5, §4 (error codes), §8.1 (budgets as built), §10 (the three settings) and `.env.example`. BACKLOG §6's Day 2 list no longer names the 4xx and `OpenAITransport` cases.
- **Gate:** run once for slices 1–4, the router fix and the cleanup merge together, at `781dc6e` (see slice 4): `uv run pytest` 413 passed, 3 skipped; `corepack pnpm test` 88 passed; `corepack pnpm e2e` 1 passed. Pushed.

### Slice 4 (plan 1.1 + 1.2): one update job per dataset, write guards and failure hooks

- **Done:**
  - **One writer per dataset.** The runner's claim skips a queued `cascade`, `stories` or `build_dashboard` job while another of those kinds runs for the same dataset (`runner.SERIAL_KINDS`, a `NOT EXISTS` in the claim's subquery), so they run one at a time in queue order; other kinds and other datasets aren't held up.
  - **Card writes guarded by the version told.** `stories.service._upsert` and `_set_status` are one conditional statement each, written only while the card's version is still `datasets.current_version` (`outdated` is always written). A tell overtaken by a newer version stores nothing, returns those widgets as `overtaken` and leaves their cards `outdated`; the overview isn't rewritten.
  - **`version_built` after the cards, forward only.** The cascade records each widget's new version only after `tell` returns, as `MAX(version_built, v)`, and not for an overtaken widget, so a cascade that dies, is cancelled or is overtaken mid-tell is told again by the next one, and an older cascade can't move a widget back (the verification's "version_built backwards" finding).
  - **A user's change wins.** Every widget write of the cascade carries `WHERE updated_at = <read value>`; unaffected widgets keep their status and error instead of being reset to `ready`.
  - **Failure hooks.** `cascade` and `stories` register `on_failure`: cards still `updating` become `outdated` (`settle_updating`), except an analysis card whose run is still queued or running. `ml.on_failure` marks the run's widget cards `outdated`; `rerun_widget` marks the card `updating` while the run runs. `_recover` cancels a job that was cancelled while it ran (and runs its hook) instead of re-queueing it.
  - Tests: two cascades and a stories job for one dataset with 4 workers run one after another while another dataset's cascade runs alongside (`test_jobs.py`); a restart cancels a cancel-requested running job and settles its card; `tell` on an overtaken version writes no text, no `ready` and no overview (`test_stories.py`); Cancel mid-tell leaves no card `updating`, and the next cascade re-tells the cancelled one's cards; a user's widget change between the cascade's read and write survives the old query's error; a failed re-run leaves the analysis card `outdated` after `updating`.
  - Docs: TRD §3.3 (the claim, failure hooks, recovery, the stories job), §4.8 (Re-run), §7.4 (no card left `updating`), §7.6 (one writer, write guards, `version_built`, failure hooks); App Flow §16 (as built).
- **Decisions:**
  - A cascade queued behind a long `stories` job (the build's first stories, about a minute) now waits for it rather than racing it; the cards end on the newer version either way.
  - A card told before Cancel took effect stays `ready` on the new version (its numbers are current); only the cards not yet told become `outdated`.
  - A widget whose title alone the user changed mid-cascade keeps its old `version_built` until the next cascade; the footer's version stamp of a SQL widget comes from its data, so nothing shows it.
  - BACKLOG: no line closes (A1, A16–A18 were audit findings, not BACKLOG lines). D6 F11 (the progress line clears only on `cascade.done`) stays open: a cancelled cascade ends with `job.failed`.
- **Gate (slices 1–4, the router fix and the cleanup merge, at `781dc6e`):** `uv run pytest` 413 passed, 3 skipped (11 min 47 s, in the `sherlock-verify` worktree); `corepack pnpm test` 14 files, 88 passed; `corepack pnpm e2e` 1 passed (11.6 s). Pushed to `origin/main` as `781dc6e`. The cleanup branch (`25333fa`, another session's) was merged after this slice; `docs/LOG.md` kept both sides.

### Slice 5 (plan 1.3): the trustworthy-source rule

- **Done:**
  - **`stories/trust.py`.** A card is usable when it's `ready`, it and its widget aren't deleted, and its numbers hold on the current version: its sheet is on that version, or the steps since its sheet's version touch none of its `depends_columns` and don't change everything. A synthesis or answer card without a sheet is usable when the cards it cites are. `Trust.why_not` says why not in a few words; `usable_cards`, `is_usable`, `outdate_citing` and `audit` use it.
  - **The overview** reads only usable widget cards, and its sheet now depends on their columns; with nothing usable to read, a stale overview becomes `outdated`. Under "Ask first" the cascade marks the overview and the syntheses citing the outdated cards `outdated` with them.
  - **Analysis cards** tell only a `done` run (`build_sheet` fails on an outdated one, so the card stays `outdated` until Re-run). A card with no facts on the new version stays `ready` only while its old sheet holds.
  - **Syntheses, `ask_story` and Make sense of this** cite usable cards only and say which they left out ("I left out <title> (<why>): … Refresh them to use them."); fewer than two usable cards is `422` (Make sense) or `409` (a synthesis's Refresh), with that sentence. `fact_for` ignores deleted cards; `DELETE /cards/{cid}` and purge re-run `check_sources`, so a synthesis citing a gone card shows `sources_changed`.
  - **`ask_model`** labels an outdated run "(version N, outdated)" and adds a Re-run sentence.
  - **The notebook** gives every card or Flow card that isn't usable an italic "Out of date (<why>) …" note under its heading (D8 F7).
  - **The invariant check:** `trust.audit` after every cascade marks any `ready` card that isn't usable `outdated`, logs a warning with the count, and the cascade's result carries `audited`.
  - **`sherlock eval grounding`** gains the stale-reuse scenario (`grounding.stale_reuse`): delete and restore a card a synthesis cites, then under Ask first edit one cell of the column most cards read; it checks the synthesis left `ready`, the overview isn't `ready`, the cascade's audit and a fresh audit find 0, and the notebook notes every card that isn't `ready`.
  - Tests: `test_stories.py::test_only_usable_cards_feed_another_output` (Ask first outdates the overview and a synthesis citing a fare card; audit 0; `usable_cards` is exactly the cards that read no fare; `sources` leaves the fare card out with its reason; Make sense with one usable card is refused with the note; the notebook notes each card that isn't ready; Refresh of the overview reads only usable cards, and an analysis card on an outdated run stays outdated; a purged widget's card leaves its synthesis `sources_changed`); `test_grounding_eval.py` asserts the stale-reuse scenario on recorded replies; `test_answerers.py::test_ask_model_says_when_its_run_is_outdated`.
  - Docs: TRD §7.4 (pipeline), new §7.4.2, §7.6 (the audit), §7.7 (cards that aren't current), §8.2 (`ask_model`, `ask_story`), §14 (stale reuse); PRD STORY-5 and STORY-6 acceptance (no non-ready source feeds another card; the overview and syntheses follow under Ask first); Schema §6 (purge re-checks syntheses); App Flow §12 (left-out cards).
  - BACKLOG: removed D8 F7 (an outdated synthesis in the notebook without a note). D7 F14 (`pick_run` prefers the newest run) stays, with the new label noted. Added: a synthesis outdated under Ask first doesn't come back by itself.
- **Decisions:**
  - "Sheet on the current version" (the plan's words) would make every card the cascade correctly left alone unusable after any edit, so usable means "the sheet's numbers hold on the current version": on that version, or nothing it depends on changed since.
  - Cards being written right now (`updating`, or a synthesis citing one) aren't the audit's to fix: their job settles them. Everything else that isn't usable and still says `ready` is.
  - A card whose widget was deleted isn't usable, but a synthesis citing it isn't marked for that: Restore brings the widget and its card back.
- **Eval:** `uv run sherlock eval grounding` (live): titanic3 10 cards (10 by the model), 25 of 25 chips, 23 of 23 facts holding; sales_dated 11 cards (11), 37 of 37 chips, 35 of 35 facts; 0 text runs with numbers, 0 causal, 0 bad labels, both syntheses by the model. **Grounded 62 of 62 chips, no problems.** Stale reuse: titanic3 edited `fare` (synthesis after the delete `sources_changed`, overview `outdated`, 4 cards outdated, 6 notebook notes for 6 cards not ready, audit 0); sales_dated edited `revenue` (`sources_changed`, `outdated`, 5, 7 of 7, 0).
- **Gate:** after rebasing onto the other sessions' slices 7, 8, 9, 10, T-0 and T-3 (tip `742fba7`, with 2b.2, 2b.3 and 2b.6): `uv run pytest` 453 passed, 3 skipped; `corepack pnpm test` 97 passed; e2e (through `e2e-locked.sh`) 1 passed. Before the rebase, at the first `6253c5a`: pytest 416 passed, 3 skipped; vitest 88 passed; e2e 1 passed.

### Slice 6 (plan 1.4): export consistency

- **Done:**
  - **The export key follows the cards.** The cascade bumps `state_rev` when it starts and when it ends, and `DELETE /cards/{cid}` bumps it, so a notebook cached before a cascade, built during one, or holding a deleted card isn't served afterwards.
  - **An export waits for the cards.** While a cascade, stories job or build is queued or running for the dataset, the export job waits up to 20 s (`jobs/export.py::WAIT_S`), logging "Waiting for the story cards to finish updating…", then reads the dataset again. If they're still busy, the notebook's first cell says the cards were being updated, and each card that isn't current carries its slice 5 note.
  - **One widget never fails the export.** A widget whose query fails on the version (or an analysis whose cells can't be built) becomes "*This widget fails on version N: <reason> …*" under its title, the first cell counts the failures, and `counts.widgets` counts only what was emitted.
  - Tests (`test_notebook.py::test_one_broken_widget_or_an_update_never_spoils_an_export`): a widget with a broken query leaves the export done with its note and the count; an unchanged repeat is cached, and a deleted card makes the next export a new one; a cascade still running after the wait gives the first cell's note; one that ends within the wait is waited for (≥ 1 s) and gives none.
  - Docs: TRD §4.6 (`DELETE` bumps `state_rev`), §7.6 (the export key), §7.7 (export consistency), §9 (the cache's invalidations); PRD NB-9 acceptance; App Flow §17.3.
- **Decisions:**
  - The wait covers queued jobs too: a cascade still in its 2 s debounce is about to change the cards.
  - No new setting for the wait (the goal's "no new settings"); 20 s is the plan's number and a module constant.
  - A failing widget's card still follows its note: it's `outdated` by then (slice 4) and says so in its own note.
  - BACKLOG: no line closes and none is added.
- **Eval:** `uv run sherlock eval notebook` (live, through `eval-locked.sh`, at the first `6253c5a`): titanic3, 2 steps, 8 widgets, runs in a fresh venv and rebuilds the version, 149 s.
- **Gate:** after rebasing onto the other sessions' slices 7, 8, 9, 10, T-0 and T-3 (tip `742fba7`, with 2b.2, 2b.3 and 2b.6): `uv run pytest` 453 passed, 3 skipped; `corepack pnpm test` 97 passed; e2e (through `e2e-locked.sh`) 1 passed. Before the rebase, at the first `6253c5a`: pytest 416 passed, 3 skipped; vitest 88 passed; e2e 1 passed.

### Slice 7 (plan 1.5): the widget data key carries its spec

- **Done:**
  - The web `Widget` type has `updated_at` (the server always sent it), and it's the last part of `keys.widgetData` and `keys.explain`. A chart changed from chat (`update_widget`), a PATCH or an Undo gets a new key once the widget list is read again, so it redraws from its new query. Before, chat's "make it a pie chart" retitled the widget and kept the old query's rows (A20).
  - `widget.updated` goes through `invalidateWidget`: the list is read again, and that widget's data and explain queries already on the event's `updated_at` are read again too (nothing in their key moved). Older keys aren't re-read on the way, so a changed spec costs one data read, not two. The dashboard's Undo no longer re-reads every widget's data, only its own.
  - Chat's Undo reuses `useWidgetActions().undo` instead of its own request.
  - **Found by the new e2e step, fixed here:**
    - A pie drawn in a chat answer covered the answer's Undo button. Bklit's pie is an `aspect-square w-full` box, so in a wide, 220 px-tall chat block it became a square as wide as the thread and spilled over what sat under it (on the dashboard the widget clipped it). The adapter now sizes it on the box's height (`h-full w-auto max-w-full`), and the chat chart block clips its content.
    - Undo brought back the query but kept the title chat gave it, so the restored KPI read "Average fare by sex". A spec change that renames a chart now keeps the replaced title in `view.options.undo_title` (the pattern `chart_title` already uses for analyses); Undo restores it, and a second undo puts the new one back (`widgets/service.py`; `test_chat_actions.py`).
  - Tests: `dashboard.test.tsx` renders a widget under a fake `EventSource` (`src/test/eventsource.ts`, for 2b.1 too); a `widget.updated` with a new `updated_at` and spec redraws it with one more data read, and one with the same `updated_at` reads the data again. It fails on the old `queries.ts` (the chart keeps "38.2%"). The e2e flow now ends on the dashboard: focus "Top 3 fares by class", "make it a pie chart" (the recorded `update_widget` reply), the pie shows female and male, and the answer's Undo puts it back.
  - Docs: TRD §4 (web: widget data keys), §4.5 (Undo restores the title) and §5.1 (the web app's reaction to `widget.updated`); App Flow §10.2.
- **Decisions:**
  - The event invalidates only the queries on its own `updated_at` rather than every query of the widget, because an older key is about to be replaced; invalidating it would read the same new data twice.
  - The e2e step picks the KPI "Average fare paid" by its dashboard element (story cards share the article role), not "Top 3 fares by class": the built sample dashboard has no widget of that title (in its place is "Rate of survived"), though the recorded curate reply names it. A KPI's one-column rows can't draw the pie's slices, so the step fails on the old key.
- BACKLOG: no line closes (A20 was an audit finding).
### Slice 8 (plan 2.1): receipts

- **Done:**
  - `GET /chat/messages/{mid}/calls` and `GET /jobs/{jid}/calls` read `llm_calls` back as a `Receipt`: every call of one answer or one job, oldest first, with its role, model, purpose, tokens, latency, `ok` (and a failed attempt's error), `repaired` and `cached`, and a total (calls, failed, repaired, cached, tokens, the summed latency). One module, `sherlock/llm/calls.py`, holds the query; `scripts/seed_sample.py`'s per-role spend line uses its `by_role`. At most 500 calls are listed, and the total counts them all. Another user's message or job is `404`.
  - **"How I worked it out"** (`web/src/components/chat/Receipts.tsx`), collapsed and fetched only when opened: inside the chat's "How do you know?" (which every Sherlock message now has, so a clarification or a failed answer shows its calls) and at the end of the cleaning report's full report. Each step in plain words with its model ID, time and tokens, "(repair)" and "(failed)" marks, then "Total: 4 calls · 5.3 s waiting on them · 2,500 tokens · 1 repair".
  - Migration `004_llm_calls_indexes.sql`: `llm_calls.cached` and indexes on `message_id`, `job_id` and `created_at`.
  - Tests: `tests/test_receipts.py` (a mocked chat answer lists route, sql and compose in order, with the same IDs as the log and matching totals; the user's own message is empty; a stranger gets `404`; a mocked clean lists its diagnose, propose and critic calls; totals count a failed attempt, a repair and a cached web row; a long job lists the first calls and totals all; the indexes exist). `web/src/components/chat/receipts.test.tsx` (the panel in "How do you know?" fetches only when opened and renders the rows and the total; the empty case; the cleaning report's). `tests/test_db.py`'s version check and `tests/test_healthz.py`'s `schema_version` now compare with the newest migration file instead of a fixed 3, so parallel slices' files don't each have to edit them.
  - Gate: `uv run pytest` 417 passed, 3 skipped (16 min; the one failure of the first run was `test_healthz`'s fixed 3, fixed above and rerun); `pnpm test` 92 passed; `pnpm e2e` passed (the flow opens How do you know? on the answer, now with the receipt inside).
  - Docs: TRD §3.5 (logging, web rows), §4.9, §4.10; Schema §1, §2.18; App Flow §5, §10.2; UI/UX §4.8. `openapi.json` and `schema.d.ts` regenerated.
- **Decisions:**
  - **Web rows need no column of their own.** A web request is an `llm_calls` row with `role = 'web'`, `model` the tool (`tavily-search`, …), NULL tokens (so no budget counts it) and `cached = 1` when the web cache answered. Receipts own `cached` (in 004), so the `tavily` stream's `005_web_cache.sql` doesn't add it; told that stream, and wrote it in the shared notes.
  - **The path is `/chat/messages/{mid}/calls`,** as the plan names it, although the pin route is `/messages/{mid}/pin`; the other streams' plans refer to this path.
  - **Errors in plain words** (UI/UX §7): the panel says "(failed)" or "(cut off, asked again)" rather than the raw error, which the API still returns (at most 200 characters).
  - The total's time is the calls' latencies summed ("waiting on them"), not the answer's wall time, which a parallel stories pool would make smaller.
- **BACKLOG:** the `llm_calls` line keeps only what's open: the table is never purged (the daily budget's scan has its index now).

### Slice 9 (plan 2.2): `sherlock llm stats`

- **Done:**
  - `uv run sherlock llm stats [--days N] [--json]` (`cli.py`, `llm/calls.py::stats`): the model-call log per purpose and per role, with p50 and p95 latency and tokens per call over the calls that answered, the tokens in all, and the repair rate (repairs ÷ first tries), fail rate (failed attempts ÷ attempts) and fallback rate (calls with `fallback_from` ÷ attempts; 0 until 2b.8's column exists); plus the tokens per chat message, p50 and p95. Markdown tables, or JSON. The database is opened read-only (`mode=ro`), so it can run against a live app's file.
  - Run against the main checkout's `.env` database (`api/data/sherlock.db`, read-only, its modified time unchanged): 111 calls of 2026-10-25. The output and what it shows are in `FEEDBACK.md` ("The model-call log"), and TRD §14 says how the figures are computed.
  - README: the median-latency column now cites it, with the numbers it prints (curate 9.3 s, story 9.8 s, overview 9.4 s, chat SQL 4.1 s, compose 6.6 s, route 1.4 s; Ultra's 2.8 s and 6.0 s and Super's critic 3.8 s were already its numbers). Two new bullets: where Token Factory sped up the build, and every purpose by name with "How I worked it out" and `llm stats`.
  - `uv run sherlock eval notebook --sets all` (offline, no model): 5 of 5 rebuild their version, 107–198 s each on a laptop busy with other sessions' suites. The table is in TRD §14, the README's notebook row cites it.
  - Tests (`tests/test_receipts.py`): seeded calls give the expected p50/p95, tokens, repair, fail and fallback rates per purpose and per role, the tokens per message, `--days`, and the markdown row; the CLI prints JSON and markdown and leaves the database file unmodified.
  - Docs: TRD §14 (model-call stats; the notebook run), plan §4 (the command), `FEEDBACK.md`, README.
  - Gate: `uv run pytest` 419 passed, 3 skipped (16 min); `pnpm test` 92 passed; `pnpm e2e` passed.
- **Decisions:**
  - **"About 1,500 tokens per chat message" was a call's size, not an answer's.** Each logged call was 1,000–3,600 tokens; the three logged chat answers came to 2,700–7,400 tokens (median 6,717), and Nano's share is its one route call, about 1,200. The README's `small` row now says "about 1,200 tokens per chat message (its one route call)", and the Cost bullet gives the whole answer's tokens.
  - Latency and tokens are over the calls that answered, so a 30 s timeout doesn't count as a slow answer; the fail rate counts it.
  - The local log is small (111 calls, before tonight's changes). It is the committed source the BACKLOG line asked for; the refresh from the deployed app's database is left as a BACKLOG step, since this session doesn't deploy or read the Render disk.
- **BACKLOG:** the README line now lists only what's left: Ultra's cost from the console, the refresh from the deployed database, and a read-over of the Token Factory sentence for the Devpost text.

### Slice 10 (plan 2.3): the cleaning log's line is built in code

- **Done:**
  - A commit or flag line's text comes from the step's full-data verifier report (`verifiers.effect_line`): "Changed 120 cells, quarantined 1 row; 99 → 0 numbers stored as text". The model's `expected_effect` moved to `note`, shown under it in smaller grey text, and only when it has no digit and no number in words (`loop.prose`, which reuses `stories.narrate.number_in_words`).
  - The same rule covers the model's other words that reached the cleaning screens: the diagnosis' cause in "Left as is: …" (the fixed "the values look legitimate" when it has a number) and in the step's decision (`reason` null), and the critic's concerns in a flag's reason and the step's `review` (concerns with a number are dropped).
  - Every outcome line of an issue that called the model carries `calls: {count, models, latency_ms}`, from the job's `llm_calls` rows since the issue started; the log shows "3 model calls · Nemotron-3-Ultra-550b-a55b, nemotron-3-super-120b-a12b · 12.3 s".
  - Tests: `test_cleaning_units.py` (the line's numbers equal the report's, in order; singular and user-step forms; digits and number words keep a sentence out), `test_cleaner.py` (the messy file's two outcome lines, exactly, with their notes and three calls each across both models; a "Left as is" skip has one call), `cleaning.test.tsx` (the entry shows the line, the note and the calls).
  - Docs: TRD §5.1 (`job.log` `text`, `note`, `calls`), §7.2 ("The log's words"); App Flow §5 (as built). BACKLOG: removed D3 M2 ("The cleaning log shows the model's own numbers").
- **Decisions:**
  - "Changed 263 cells", not the plan's "Fixed 263 cells": the report counts changed cells, and a flagged step isn't known to be right.
  - A sentence with a number in words is dropped as well as one with digits ("quarantines the one value" passes, since `number_in_words` leaves out "one" on purpose, D8 F1), so the stricter half of Rule 2 holds without a new word list.
  - A model sentence with a number is dropped whole, not edited: cutting the number out leaves a sentence nobody wrote.
  - The calls line names the model IDs without the `nvidia/` prefix; receipts (slice 8) own the fuller per-call view.
### Tier 2 row 2b.1: the event stream catches up

- **Done:**
  - **In order.** `jobs/events.py` `emit` writes the row and publishes it under one process-wide lock, so streams get events in id order. Before, two threads could write 10 and 11 and publish 11 first, and the client, which skipped any id at or below the last it saw, dropped 10.
  - **An opening id.** Each stream reads the newest event id after it subscribes and sends it as an `id:` line alone, after any replay and before the first live event. It dispatches nothing, but the browser keeps it as its last event ID, so a stream that drops before its first event reconnects with `Last-Event-ID` and gets what it missed (before, it came back live-only).
  - **The newest 5,000.** A replay is bounded by that newest id and keeps the newest 5,000 rows, sent oldest first (it was the oldest 5,000, so a client far behind got stale events and never the latest).
  - **The client.** `sse.ts` keeps a set of the last 2,000 ids it handled instead of "skip at or below the last", so an event that arrives late is still handled and a replay's copy isn't. Every reopen, the browser's own or ours, calls `onReopen`: the dataset stream reads every query on screen again (all but `me`), the library stream the dataset list and the jobs, since a capped replay or a live-only reopen can still miss something.
  - Tests: `test_jobs.py`: a stream's last frame after a replay, and its first live-only, is `id: <newest>`; with the cap at 2 the replay is the newest two; two threads emitting at once publish in id order (a bus that holds the first publish; it fails without the lock). `sse.test.ts` with the fake `EventSource`: a late event is handled and a replayed one isn't; the browser's reconnect and ours (after 1 s, `?last_event_id=9`) each call `onReopen` once, the first open doesn't; a dataset stream that reopens reads the dataset again.
  - Docs: TRD §4 (web: `sse.ts`, reopen) and §5.2 (in id order, the opening `id:` line, the newest 5,000, the live skip after a replay).
  - BACKLOG: removed the D2 SSE line (out-of-order ids; a library stream that drops before its first event); "SSE replay and event order" and "`sse.ts` dedup, reopen and backoff" are out of Day 2's untested list.
- **Decision:** both fixes the plan offered, not one: the lock fixes the order at the source, and the client's id set still matters for a replay that overlaps live events after a reopen. `onReopen` reads everything on screen rather than a list of keys, because a reopen is rare and a missed event can be of any type.

### Slice 11 (plan 2.4 + 2.5 + 2.6): output agreement, merge safety, and the two new benchmark corruptions

- **Done:**
  - **2.6, the new sets** (`eval/corruption.py`, `eval/synthetic.py`). `dates_dmy` and `dates_mdy`: 400 clinic visits whose every date has a day of 12 or less (and never day = month), written day-first in one and month-first in the other, so no reading of the data tells them apart. `lookalikes`: 600 members with "Plan A"/"Plan B"/"Plan C", "Region 1" to "Region 4" and "Austria"/"Australia" (each 30%), with case variants and money damage. The scorer gained **Wrong** (damaged cells changed into a value that isn't the clean one; left as it was, emptied, or the same number typed isn't wrong), and two texts compare as dates only when both are ISO: pandas had read "13/05/2015" or "04/03/2021" left as text as a date and counted it recovered. The output now ends with every skipped issue and its reason.
  - **2.4, output agreement** (`verifiers.compare`, `gate.disagree`, `cleaning/loop.py`). Each passing candidate's result on the sample is kept. When two of them give different values to more than 1% of the cells they both change, the issue is skipped before the full run (no full run, no critic call), with two cells both ways: "Skipped: the candidates disagree on 57% of the cells they both change (Title case vs Most frequent spelling: mcdonald → Mcdonald vs McDonald; MCDONALD → Mcdonald vs McDonald)". The gate's agreement is the share of candidates whose result matches the best one's on at least 99% of the cells either changes (a no-op or a failed candidate doesn't agree).
  - **2.5, merge safety** (`helpers._merge_refusal`, used by the detector, `canonicalize_categories` and the new hard check `merge_safety`). A merge is refused when the values differ only in their numbers ("Region 1"/"Region 2"; "Region 01"/"Region 1" are the same number) or when both are common (each on 5% of the rows and more than one). Case and spacing variants always merge ("male " → "Male"). The detector no longer pairs "region 1"/"region 2" (87.5) or "austria"/"australia"; `canonicalize_categories` joins each value to its most similar kept spelling ("Austrlia" → "Australia", not "Austria") and drops a model's unsafe mapping entries; the propose prompt gets the detector's details (its `pairs`) inside its data block.
  - **Dates that read both ways** (plan 2.6's case, PRD CLEAN-4b). The import's typing step had typed such a column day-first without a word (the format list tries `%d/%m/%Y` first): `profile/infer.parse_dates` now leaves a column as text when the other reading of its day/month format parses every value and reads some differently. The Cleaner then skips it with no model call and no budget used, "Left as text: every date reads both ways (03/04/2021 is 3 Apr 2021 or 4 Mar 2021; …), so the order is yours to choose", unless the user rewrote the fix. The vote stays for a `mixed` column.
  - **A bug the tests found:** `normalize_whitespace_case(mode="keep")` raised "cannot insert <column>, already exists" for every column the Cleaner passed it (two Series of one name in a `groupby`), so every "keep the most frequent spelling" candidate failed. It counts in a frame of its own now. That is why `sales` region and `hr` department fell to 0 recovered in "before" run 2 below: that run's candidates were "keep" ones.
  - Tests: `test_cleaning_units.py` (look-alikes not merged by the helper, a mapping or the detector; the hard check's two failures and a typo that passes; `compare` on two date readings, on numbers of different types, and on one cell in 200; the gate with output agreement; a named Series through "keep"), `test_samples_and_eval.py` (Wrong, ISO-only text dates, the new sets), new `test_cleaner_checks.py` with its own recorded replies (`fixtures/llm/cleaner_checks.json`): two candidates that disagree are skipped after only diagnose and propose with the exact reason; a visits file keeps its dates as text with no model call, and its date strings a digit apart don't pair as near-duplicates; the benchmark's month-first case ends 0 recovered, 0 wrong.
  - Docs: PRD CLEAN-4b (new, add-only) and §7.3.1; TRD §6 (`verifiers`), §7.1 (the typing step, `near_duplicate_categories`), §7.2 (rules as built, dates that read both ways, the comparison in the loop, helpers, `merge_safety`, agreement, the propose template), §14 (the sets, Wrong, ISO dates, the skip table); Plan §6; App Flow §5; UI/UX §5.4.
- **The benchmark** (`eval-locked.sh … corruption`, live Nemotron, three runs as the brief allowed):
  - **Before, run 1** (02:23, before any change, with the old scorer and sets):

    | Set | Rows | Damaged cells | Recovered | Harm | Row loss | Quarantined | Steps | Time | Ended by |
    |---|---|---|---|---|---|---|---|---|---|
    | titanic_clean | 1,043 | 509 | 97.2% | 0.00% | 0.0% | 81 | 4 | 64 s | done |
    | sales | 1,500 | 765 | 96.1% | 0.00% | 0.0% | 18 | 4 | 80 s | done |
    | hr | 800 | 269 | 94.1% | 0.00% | 0.0% | 5 | 5 | 94 s | done |

  - **Before, run 2** (02:28, with 2.6's sets and scorer, before 2.4 and 2.5). Its Wrong column for placeholders counted "-999" typed as -999.0 as a wrong value (titanic 14, sales 18, hr 5); the rule was corrected before the "after" run, so read those three as 0 wrong. `sales` region and `hr` department are the "keep" bug above.

    | Set | Rows | Damaged cells | Recovered | Wrong | Harm | Row loss | Quarantined | Steps | Time | Ended by |
    |---|---|---|---|---|---|---|---|---|---|---|
    | titanic_clean | 1,043 | 509 | 97.2% | 2.8% | 0.00% | 0.0% | 81 | 4 | 100 s | done |
    | sales | 1,500 | 765 | 56.9% | 2.4% | 0.00% | 0.0% | 73 | 4 | 106 s | done |
    | hr | 800 | 269 | 53.5% | 1.9% | 0.00% | 0.0% | 5 | 3 | 97 s | done |
    | dates_dmy | 400 | 400 | 100.0% | 0.0% | 0.00% | 0.0% | 0 | 0 | 2 s | done |
    | dates_mdy | 400 | 400 | 0.0% | 100.0% | 0.00% | 0.0% | 0 | 0 | 10 s | done |
    | lookalikes | 600 | 288 | 100.0% | 0.0% | 0.00% | 0.0% | 0 | 4 | 150 s | done |

  - **After** (02:51, this slice):

    | Set | Rows | Damaged cells | Recovered | Wrong | Harm | Row loss | Quarantined | Steps | Time | Ended by |
    |---|---|---|---|---|---|---|---|---|---|---|
    | titanic_clean | 1,043 | 509 | 92.1% | 5.1% | 0.00% | 0.0% | 81 | 5 | 117 s | done |
    | sales | 1,500 | 765 | 97.6% | 0.0% | 0.00% | 0.0% | 18 | 4 | 103 s | done |
    | hr | 800 | 269 | 98.1% | 0.0% | 0.00% | 0.0% | 0 | 3 | 75 s | done |
    | dates_dmy | 400 | 400 | 0.0% | 0.0% | 0.00% | 0.0% | 0 | 0 | 2 s | done |
    | dates_mdy | 400 | 400 | 0.0% | 0.0% | 0.00% | 0.0% | 0 | 0 | 6 s | done |
    | lookalikes | 600 | 288 | 41.7% | 0.0% | 0.00% | 0.0% | 0 | 1 | 90 s | done |

    | Set | Damage | Recovered | Wrong |
    |---|---|---|---|
    | titanic_clean | age: sentinel | 1/41 | 26 |
    | titanic_clean | embarked: case | 156/156 | 0 |
    | titanic_clean | fare: money | 312/312 | 0 |
    | sales | product: typo | 45/45 | 0 |
    | sales | region: case | 300/300 | 0 |
    | sales | unit_price: money | 375/375 | 0 |
    | sales | units: sentinel | 27/45 | 0 |
    | hr | city: mojibake | 36/36 | 0 |
    | hr | department: case | 120/120 | 0 |
    | hr | hire_date: dmy_date | 97/97 | 0 |
    | hr | salary: sentinel | 11/16 | 0 |
    | dates_dmy | visit_date: dmy_text | 0/400 | 0 |
    | dates_mdy | visit_date: mdy_text | 0/400 | 0 |
    | lookalikes | country: case | 0/48 | 0 |
    | lookalikes | monthly_fee: money | 120/120 | 0 |
    | lookalikes | plan: case | 0/60 | 0 |
    | lookalikes | region: case | 0/60 | 0 |

  - **Read together:** harm is 0.00% on every set, and Wrong is 0 on the three new ones. The silent guess is gone: before, the import typed both date sets day-first, right on one and wrong on all 400 of the other; after, both stay text for the user to order (2b.9). `sales` and `hr` recover more than either "before" run (97.6% and 98.1%; the "keep" fix and model variance). Two numbers fell, and the benchmark of this run didn't yet print its skip reasons, so their causes aren't known (both are in BACKLOG):
    - `lookalikes` 41.7% (was 100%): its three case fixes (plan, region, country) were skipped this run. The same file through the Cleaner with scripted "keep", "title" and `canonicalize_categories` candidates commits all three, 100% recovered and 0 harm, so the code path works; what the model proposed for these look-alike values didn't pass. `sales` region and `hr` department case fixes in the same run were 300/300 and 120/120.
    - `titanic_clean` age placeholders: 26 of 41 were filled with values (Wrong 26) where the "before" runs left them empty. One fill candidate on its own agrees with itself, so output agreement can't catch it; this is the run-to-run variance in imputation FEEDBACK already records.
- **Decisions:**
  - **"The cells they change" is read two ways.** Disagreement (the skip) counts the cells *both* candidates change, so a conservative candidate that leaves a cell alone doesn't veto a fix; agreement (the confidence) counts the cells *either* changes, so a no-op doesn't count as agreeing.
  - **A disagreement skips a requested step too:** the data doesn't settle which value is right whoever asked; the reason shows both, so the user can rewrite the fix.
  - **The check runs on the sample, before the full run,** so a disagreement costs no full run and no critic call (the plan put it in the gate; `gate.disagree` holds the rule and the loop applies it early).
  - **"Common" needs more than one row:** at 5% of rows alone, every value in a file under 20 rows is common and nothing could merge (the existing 8-row helper test).
  - **The typing step stops guessing an order** (outside the plan's file list, `profile/infer.py`): without it the Cleaner never saw the ambiguous column, and step 1 committed the guess as "automatic". Dotted dates stay day-first by convention.
  - **Dates that read both ways cost no model call:** three diagnose votes, candidates and a skip would spend Ultra calls to reach the same "can't tell". The vote stays for `mixed` columns, where some values show the order.
  - **`canonicalize_categories` joins the most similar head** rather than the first one that matches: the old order put "Austrlia" into "Austria".
  - The propose prompt says to merge only the detector's pairs and never values that differ only in their numbers or two common ones; the code refuses those merges anyway.
- **BACKLOG:** added the two open benchmark numbers above (lookalikes case fixes skipped live; titanic age placeholders imputed by a lone candidate).

### Slice 13, part 1 (plan T-0): the Tavily client

- **Done:**
  - `tavily-python` 0.8.5, pinned (`api/pyproject.toml`, `uv.lock`), with what it installs (`requests`, `httpx`, `tiktoken`, `urllib3`, `certifi`) in `THIRD_PARTY.md`, and a "Web retrieval" note there: retrieval only, under Tavily's terms.
  - `sherlock/web/client.py`: `WebClient.search`, `extract` and `map` with every parameter fixed (`basic` search, five results, `include_answer: false`, no raw content, no images, no auto-parameters; extract with a query and three chunks per page; map one level deep, 20 links, no external ones). A caller picks only the query or URLs, the topic and a time range; there is no way to pass `include_answer` or call `research()`.
  - **Fail-soft:** no key, `WEB_SEARCH=off`, the hourly limit, too little time before the call's `CallScope.deadline`, a timeout, a 4xx, a 5xx, a connection error or a bad reply all raise `WebUnavailable` with the one line the answer shows instead. Nothing else is raised.
  - The timeout is `TAVILY_TIMEOUT_S` (8 s) or the time left before the deadline; a process-wide gate of four (`llm/client.py::gate`, role `web`).
  - Migration `005_web_cache.sql`: `web_cache` (24 h, read only when fresh, deleted by the purge job) and `llm_calls.results`. Every call, cached or not, is an `llm_calls` row with `role = 'web'`, `model` `tavily-search|extract|map`, `cached` (receipts' 004 column) and `results`, and NULL tokens, so the token budgets and the app-wide ceiling don't count it; receipts already name these rows ("Searched the web").
  - Settings `WEB_SEARCH`, `TAVILY_TIMEOUT_S`, `WEB_RATE_LIMIT` (20 per user per hour, cache hits not counted) and `WEB_MOCK` (recorded responses, like `LLM_MOCK`); `TAVILY_API_KEY` declared in `render.yaml` with `sync: false`; `.env.example`.
  - `sherlock/web/fixtures.py`: a fixture transport that captures every request (for tests and the offline eval to come) and a failing one.
  - `tests/conftest.py` empties `TAVILY_API_KEY`, so no test can reach Tavily. `tests/test_web.py` (15 tests): the exact parameters sent; a caller can't widen them; extract and map parameters; a cache hit makes no call and keeps the first retrieval date; a stale entry is asked again and purged; a timeout and a 502 fail soft, logged and not cached; a transport raising anything fails soft; no key sends nothing and writes no row; `WEB_SEARCH=off` wins over a transport; a key turns the live transport on; the hourly limit per user (cache hits free, another user unaffected, free again after an hour); the deadline bounds the timeout and stops a call with no time left; the live transport refuses an empty key; through `requests`, the body posted to `/search` holds `include_answer: false` and the bearer key, a 500 and a 400 fail, a timeout times out, and no request goes to `/research`.
  - Docs: TRD §2 (the `web/` package), new §3.6 (the web client), §10 (five settings), §12, §15; Schema §1, §2.18 (web rows, `results`), new §2.22 (`web_cache`), §5, §6.
- **Decisions:**
  - **T-0 lands before T-1.** T-1's routing waits for the `chat-checks` stream's slice 12; the client and the cache don't, so they land as their own commit (the goal allows smaller slices). Nothing calls the client yet, so the app behaves exactly as before.
  - **Never keyless.** `tavily-python` 0.8.5 sends unauthenticated "keyless" search and extract requests when it has no key. With no `TAVILY_API_KEY` Sherlock makes no transport at all, and the live transport refuses an empty key, so nothing leaves the process until the owner sets one.
  - **`llm_calls.results`** (005) holds how many results or pages a web call returned, for the receipts' "5 results" (T-5). Receipts' 004 owns `cached`, so 005 doesn't add it.
  - **`WEB_MOCK`** is a developer setting like `LLM_MOCK`, not a user setting (goal default 2 asks for no new user setting).
  - **The cache is shared by every user.** A request holds only words and column names and the response is public web content, so one user's search can answer another's within 24 h; each user's hit is still logged under them.
  - **The gate is four calls, fixed** in code rather than a sixth setting; it can become one if a key's rate limit needs it.
  - A call refused before it went out (no key, the limit, no time) writes no `llm_calls` row: nothing was sent and nothing cost a credit.

### Slice 15, part 1 (plan T-3): "use this data dictionary"

- **Done:**
  - **New P1 requirement LOAD-7** (PRD §7.1, add-only): an optional "Data dictionary URL" in the import preview; Sherlock reads the page with Tavily and keeps a note on each column it describes.
  - `agent/web.py::read_dictionary` (TRD §7.1.1): Tavily `extract` of the URL with the column names as the query and three chunks per page; with under 200 characters of excerpts, `map` the site ("data dictionary, codebook, variable definitions") and extract the first three pages it finds (a failure there keeps the first page's excerpts). Super maps the fenced excerpts to columns with schema `ColumnNotes` (purpose `dictionary`): a column of the file named exactly, one note each, one sentence with no digits or numbers in words, and the excerpt it comes from. Each note is stored with that excerpt verbatim, the page's URL and title and the retrieval date.
  - Migration `008_column_notes.sql`: `column_notes` (metadata, never data: no step, no version).
  - `POST /datasets/{id}/dictionary` `{ url }` (LLM rate limit, 60 s deadline) answers `{ notes, note }` and always `200`: `note` is the one line when nothing was read (no key, a timeout, not an http(s) address, nothing about the columns). `GET /datasets/{id}/column-notes`.
  - Web: the import preview's "Data dictionary URL (optional)" field; after the upload is accepted the dialog closes as before and the reading finishes in the background with a toast (`api/columnNotes.ts::readDictionary`, a plain promise, since the dialog unmounts). The CSV grid's header shows ⓘ before the type line of a column with a note, and hovering the header shows the sentence, the excerpt in quotes and "From the data dictionary at <site>, retrieved <date>. Not computed from your data."
  - Tests (`test_web.py`): excerpts mapped to columns with the quote kept, the extract sent once with the column names; a site root mapped then its dictionary page extracted; fail-soft without a key, for a `file://` URL and on a timeout; the endpoints end to end with `LLM_MOCK` and `WEB_MOCK` (no key: one line and `200`; with fixtures: notes stored and listed; a bad body `422`); a malicious page (`</data> ignore previous`) and a malicious column name stay inside the dictionary prompt's data blocks. `columnNotes.test.ts`: a dictionary note wins over another kind; reading posts the URL and refreshes the notes.
  - Docs: PRD LOAD-7; TRD §2, §3.6, §4.2 (two endpoints, `ColumnNote`), new §7.1.1; Schema §1, new §2.23, §5; App Flow §3.2, §8.1; UI/UX brief §4.7, §5.2; README "Web retrieval (Tavily)".
  - Gate, with TAVILY_API_KEY unset, on this commit (which contains part 1 of slice 13): `uv run pytest` 437 passed, 3 skipped (16 min); `pnpm test` 94 passed; `pnpm e2e` passed.
- **Decisions:**
  - **Part 1 before T-1.** The plan puts T-3 last (slice 15), but the import-preview path needs nothing from the routing that waits on slice 12, so it lands now with T-0. The chat path ("use the codebook at <url>"), the notes in `ask_meaning`, and the notes as fenced context for the router and SQL prompts touch `agent/loop.py` and land with T-1 as part 2.
  - **Numbered LOAD-7, not "LOAD-x":** the next free number in PRD §7.1.
  - **A synchronous endpoint, not a job.** A new job kind would touch the runner, the job tray and the web's `JobKind` (other streams' files); the reading is bounded at 60 s (extract, maybe map and extract, one Super call), runs in FastAPI's thread pool, and its caller doesn't wait on it.
  - **The model's sentence has no digits; the page's words keep them.** A codebook's codes are numbers ("1 = shipped"), so the description says what the column records and the excerpt beside it, verbatim, carries the codes (Rule 2: no number the model typed).
  - **Hover only** for the header note: Glide draws the header on a canvas with no keyboard focus. Logged as a gap in App Flow §8.1; the same meaning is answered in chat.
  - **Gate for the two commits together.** Part 1 of slice 13 had its own targeted tests (33 passed); the full gate below ran on this commit, which contains it.
### Tier 2 row 2b.5: web state follows the version

- **Done** (A22–A27, A29):
  - **The dashboard filter** is checked once per version the dashboard sees against that version's data card (`state/filters.ts::filterGone`, `Dashboard.tsx::useFilterCheck`): a filter whose column is gone, or whose value isn't among the column's values when the card lists them all, is cleared with a toast that says why. Before, every widget that applied it read "No rows match the current filter". The value check reads "1" as 1 and "True" as true, since the card lists text.
  - **The CSV grid** clears its selected cells on a new view (version, sort, Find): they're row positions that now hold other rows, and they were the chat's "3 rows selected". An open Find runs again on a new version, so its rows and count are that version's.
  - **A failed page** of rows is asked for twice more (0.5 s, 1 s); then the grid reads "Couldn't load these rows: …" with Retry, instead of a bare error that only a reload cleared.
  - **The open cleaning plan** is read again on `version.created`, which merges it onto the new version (the server's merge on read, with its toast). Until it's back, the header reads "Sherlock checked v4; the data is v5. Checking the plan again…".
  - **The library stream's** `dataset.status` also reads the dataset's steps, cleaning report and cards again: a status change ends a clean or a build.
  - **Two tabs:** the edits buffer follows another tab's change through the `storage` event (an edit shows; a save or Discard clears this tab's buffer, so the same edits can't be saved twice). A new `chat.updated` event on the dataset stream (`routers/chat.py::thread_changed`, after `POST /chat` saves its answer and after a proposal is approved or rejected) makes another tab read its thread again.
  - Tests: `follow-version.test.tsx` (the plan and the thread re-read on their events; `applyStatus`'s keys; `filterGone` cases; the filter cleared on a new card; the plan's version line), `grid.test.tsx` (two retries then Retry; a retry that succeeds; the selection cleared on a new version, with Glide's editor stubbed), `csvtab.test.tsx` (Find runs again on v3), `csv.test.ts` (the storage event), `test_chat_actions.py` (`chat.updated` after an answer, a reject and an approve).
  - Docs: TRD §5.1 (`chat.updated`; the web app's reactions), §5.2 (emitted); App Flow §4.1 (a new version while the plan is open), §7.3 (the filter), §8.1 (a new view, a failed page, two tabs), §10.2 (two tabs).
- **Decisions:**
  - Find runs again on a new version rather than closing: the user still wants the search, and "No cells match." closes it when nothing matches.
  - The filter check runs once per version, not when a filter is set: a value just clicked is in the data, and the card's text form of a value could differ from the clicked one (dates).
  - BACKLOG: no line closes (A22–A29 were audit findings).

### Fix: `pnpm build` failed on the column-note hover's type

- `Grid.tsx`'s `onItemHovered` (slice 15, T-3) read `args.bounds` on any `GridMouseEventArgs`, but only a header event has `bounds`, so `tsc -b` failed and with it `pnpm build`, the Docker image's web step (`api/Dockerfile`). vite alone doesn't type-check, so vitest and the e2e passed. The handler now returns early for anything but a header; behaviour is the same (a non-header event already cleared the note). Checked: `tsc -b`, `pnpm build`, the CSV and column-note vitest files. Found by the `web-state` session while rebasing 2b.5.
### Tier 2 row 2b.7: user-written text

- **Done** (A37, A38, D6 F18):
  - **Number words.** `mark_unverified` matches a number spelled out as well as digits (`TYPED`: `NUMBER` or the narrator's `NUMBER_WORDS`), so "zero" or "twice" in a card edit becomes an unverified chip. Roman numerals are left out: "XL" in a user's sentence is more often a size.
  - **"Written on v5, data is now v7"** on an edited card once the data is past the version its words describe (`StoryCard.tsx::UserTextBadges`, on the panel's card and its Flow node). It stays after Dismiss, which was the gap: the suggestion went and nothing said the words were old. `PATCH /cards/{cid}` now sets the card's `version` to its sheet's (as Accept does), so the badge names the version the user wrote on, not the one Sherlock last wrote it on; the cascade moves an edited card's sheet but not its `version`.
  - **"Has numbers you typed; check them"** on a card with unverified chips once the data moved on: the dashed chips said "typed by you", but nothing said they may be out of date.
  - The web reads the dataset's version from the cache (`useCurrentVersion`, a disabled query), so a card doesn't read the dataset again.
  - Tests: `test_stories.py` ("Zero", "twice", "one in" and "three" become chips, "XL" doesn't; an edit's `version` is its sheet's), `StoriesPanel.test.tsx` (both badges on v7 for words written on v5; none on v5; only the typed-numbers badge on a card the user didn't edit).
  - Docs: PRD STORY-7 (acceptance, add-only), UI/UX §4.5, TRD §4.6 (`PATCH /cards`), App Flow §11. `openapi.json` and `schema.d.ts` regenerated (the route's description is its docstring).
  - BACKLOG: removed D6 F18 (a number word typed in a card edit isn't marked unverified).
- **Gate for 2b.1, 2b.5 and 2b.7** (pushed together, after rebasing three times onto other streams' pushes): the full pytest and the e2e on the tip, vitest and `tsc -b` on the tip and on each of the three commits, and after each rebase the protocol's `test_db`, `test_openapi` and `test_prompt_hygiene` plus the slices' own test files. Running the full pytest (16 min) and e2e for each commit after every rebase would have kept them off `main` while other streams kept landing. The rebase onto T-3 changed `Grid.tsx` (its header notes read a query), so 2b.5's grid test renders through a stateful host to keep its query client.
- **Decision:** the badges compare `Card.version` with the dataset's current version rather than with the sheet's, so a card whose chips are current but whose words were written earlier still says so. "one" alone isn't a typed number (the narrator's list leaves it out too; "one of the groups" is ordinary English), so BACKLOG's D8 F1 line about "one", "single" and "pair" stays.

### Tier 2 row 2b.9: the user picks the date order

- **Done:**
  - An ambiguous-dates item in the cleaning plan has `date_order` (null, "dmy" or "mdy"), `both_ways` (up to three of its values read each way, "03/04/2021 · 3 Apr 2021 · 4 Mar 2021") and `needs_order` (every date reads both ways). A new plan op, `set_date_order`, sets or clears it ("Set the date order of visit_date to day-first."); `merge` keeps it by key.
  - The plan panel asks "Which order are these dates in?" under the fix: the three values in a small table and two toggle buttons, Day first and Month first (`DateOrder` in `CleanPlanPanel.tsx`). Without an order it says why it matters: dates that every one reads both ways stay text.
  - The Cleaner runs a picked order as the user's instruction ("Read every date in visit_date day-first (dd/mm/yyyy): parse it with order_hint "dmy"."), `requested` like a rewritten fix, with **one** diagnose call instead of the three-way vote. The report lists it under "Your steps" and the step's decision says "You asked: …". The skip for dates with no order now ends "…, so the order is yours to choose: pick it in the cleaning plan".
  - The benchmark gains `dates_dmy_picked` and `dates_mdy_picked`: the two date sets cleaned through a plan with the right order picked (`run_case` makes the plan, sends `set_date_order` and starts it).
  - Tests: `test_cleaner_checks.py` (the plan item's three values both ways; `set_date_order` refuses another value and another item; a picked order runs diagnose once, then propose and critic, parses 03/04/2021 as 3 April and lists the order under "Your steps"; the benchmark's two picked sets, 60 rows each, end 100% recovered and 0 wrong through `run_case`, on recorded replies), `cleaning.test.tsx` (the picker shows the values both ways, picks, marks and clears; the panel sends the op).
  - Docs: PRD CLEAN-8b (acceptance); TRD §4.4 (`PlanItem` and `set_date_order`), §7.2 (a picked order; the skip's wording), §14 (the picked sets); App Flow §4.1, §5; UI/UX §5.3a; Plan §6. `openapi.json` and `schema.d.ts` regenerated (`PlanOp.order`).
- **Decisions:**
  - **The picked sets weren't run live:** the brief allowed only the slice 11 before and after runs, so the proof is the recorded-reply run above. `uv run sherlock eval corruption --sets dates_dmy_picked,dates_mdy_picked` runs them live.
  - **Chat doesn't set the order** (its `edit_plan` schema is the chat stream's file): it can still rewrite the fix in words ("read the dates day-first"), which lets the run go ahead the same way.
  - The order is offered on every ambiguous-dates item, `mixed` too, where it replaces the vote; only an `ambiguous` one needs it to run.
  - A picked order is the user's request, so a low-confidence result commits with a flag rather than being skipped, and disagreeing candidates are still skipped (slice 11).
- **Gate:** `uv run pytest` 431 passed, 3 skipped (the one failure of the first run was this row's own test still expecting `lookalikes` last in the case list; fixed and rerun); `pnpm test` 95 passed; e2e passed. Slice 11's gate: pytest 428 passed, 3 skipped, its one failure a sandbox timeout while another pytest ran (`test_sandbox.py` 42 passed alone); vitest 93 passed; e2e passed on a rerun.
- **BACKLOG:** added "The e2e flow can see the chat answer twice": two of six e2e runs tonight failed at `flow.spec.ts:30` under load, `origin/main` itself among them, and every run alone passed.

### Tier 2 row 2b.8: the Nemotron fallback (Super → Ultra)

- **Done:**
  - **A circuit breaker per role**, process-wide like the gate (`llm/client.py::Breaker`, `breaker(role)`): it opens after 3 transient failures (429, 5xx, timeouts, connection errors) within 60 s and closes 30 s later; an answer clears the count. A refused request and a cut-off reply don't count.
  - **The fallback** (`FALLBACK = {"medium": "large"}`): a Super call goes to Ultra when Super's breaker is open as it starts, or at once (no backoff wait) when a failed attempt opens it or the next retry would start with under 5 s before the deadline. Only while Ultra's own breaker is closed and the deadline and the 120 s cap leave it 5 s. `_complete` now prepares the request once and `_send` runs one role's attempts, so Ultra's call goes through Ultra's gate, under the same deadline, with the 120 s cap counted over the whole call and Super's waits kept in `waited_s`.
  - Migration `007_llm_fallback.sql`: `llm_calls.fallback_from`. Ultra's row says `role = 'large'`, `fallback_from = 'medium'`; receipts carry it (`ModelCall.fallback_from`, "(in place of the medium model)" in "How I worked it out"), and `sherlock llm stats` now reads a real fallback rate.
  - `tests/conftest.py` closes every breaker before and after each test, so one test's failures can't send the next test's Super calls to Ultra.
  - Tests (`test_llm_client.py`): the breaker opens on 3 in 60 s, not on 3 spread wider, closes after 30 s, and an answer clears it; three Super failures go to Ultra without the third wait, the rows say so, the next call goes straight to Ultra, and Super is asked again 30 s later; a deadline-starved Super call goes to Ultra with the time left; no fallback with under 5 s left or with Ultra's breaker open; twenty Super calls with Super open-circuited all reach Ultra, at most two at a time. `test_receipts.py`: the receipt and the fallback rate. `receipts.test.tsx`: the mark.
  - Docs: TRD §3.5 (retries, logging, the fallback), §4.9 (`ModelCall`); Schema §1, §2.18; App Flow §10.2; UI/UX §4.8. `openapi.json` and `schema.d.ts` regenerated.
  - Gate: `uv run pytest` 447 passed, 3 skipped (16 min); `pnpm test` 96 passed; `pnpm e2e` passed.
- **Decisions:**
  - **"Deadline-starved" means the next Super retry would start with under 5 s before the deadline.** Then Ultra gets the time left at once, instead of a doomed Super retry or a backoff that passes the deadline. A Super call waiting for a free Super slot isn't covered (BACKLOG): falling back there would move chat's overflow onto Ultra's two slots, which the Cleaner uses.
  - **The thresholds are constants, not settings** (`BREAKER_FAILS`, `BREAKER_WINDOW_S`, `BREAKER_OPEN_S`, `FALLBACK_MIN_LEFT_S`): the plan fixes 3, 60 s and 30 s, and none needs tuning per deployment.
  - **Only Super falls back.** Ultra has nothing larger to go to, and Nano's route call already falls back to one `ask_data` step.
  - The ask eval wasn't rerun: the fallback changes nothing while Super answers, which is every call of a healthy run, and the plan names no eval for 2b.8. It can only turn a failing Super call (the 529s in `FEEDBACK.md`) into an answer.
  - **Out of the plan's order:** 2b.8 landed before 2b.1–2b.7, which other streams own, since the owner asked for parallel work (`parallel.md`).
- **BACKLOG:** added "The Nemotron fallback doesn't cover a full Super gate".
- **Found in passing:** `pnpm typecheck` (which `pnpm build` runs) failed in `web/src/components/csv/Grid.tsx` after 41fc04d, while `pnpm e2e` (which uses `vite build`) passed. Told the `tavily` stream, whose file it is; its fix (3bb807d, "Narrow the column-note hover…") landed before this row.

### Slice 12 (plan 2.7 + 2.8 + 2.9): chat results checked in code, clarifications with buttons, one wording check

Built in the `chat-checks` worktree, in parallel with the other streams (the owner asked for parallel sessions; `.claude/plans/parallel.md`).

- **Done:**
  - **2.7, result checks.** `Toolkit.findings` checks every `ask_data` result that ran: no rows; a result column null in every row; a column the message names (resolved, or a resolved value's column) that the query never uses (sqlglot, `SELECT *` exempt); a text literal compared with a bare column (`=`, `<>`, `IN`) that isn't among that `VARCHAR` column's values in the value index. What was found goes back once (purpose `sql_check`, `prompts.RESULT_REPAIR`, fenced), e.g. "sex = 'Female' matches no row: sex has 'male', 'female'."; the repaired query replaces the first only when it runs and shows no more findings. `resolved` and the column types are passed into `Toolkit`.
  - **2.8, clarifications with buttons.** `answerers.Clarify` carries two or three options and what each stands for. A name nothing resolved becomes "Which column do you mean by “fair”?" (`resolve.candidates`) once the SQL step can't write the query; `ask_meaning` asks which column, `ask_stats` which two columns (`insight.pair_options`), and `explain_widget`/`update_widget` which widget (the only one is used without asking). The message's focus keeps the previous answer's and adds `clarify: {name, means}`, so the choice resumes with the name resolved ("“fair” is column fare" in the context).
  - **2.9, one wording check.** `stories/wording.py` holds the narrator's lists (`CAUSAL`, `NUMBER_WORDS`, `ROMAN`, `MARKUP`), with `wording_problem` and `title_problem`; `narrate` imports them (a new module, because importing `narrate` from `agent/` was circular through `stories.facts` → `agent.compose`). Applied to compose prose and a number's label (a repair, then the fallback), `closest` (the file's example instead), the router's clarification (failing options dropped; under two, no clarification), `reading` (not shown) and chat widget titles (the templated title instead, `answerers.widget_title`). A `value:` label now accepts a cell only from a result column that isn't a number type, or a value the DataCard knows. The COMPOSE rule says text runs hold no numbers in words.
  - Tests: `tests/test_chat_checks.py` with recorded replies in `tests/fixtures/llm/chat_checks.json` (a wrong-case literal repaired end to end; the four findings; "average fair by class" → buttons → resumes with `fare`; which column; router options checked; a failing router clarification is answered instead; compose refuses "twice" and "leads to"; titles and readings fall back); `test_prompt_hygiene.py` covers `sql_check` (its findings quote the evil value fenced); `test_chat.py`: the value-label rule, and "make this a line chart" asks with widget buttons.
  - **Found by the eval: an empty model-card answer.** When compose fell back on an `ask_model` answer, the loop still dropped every model-card table the (missing) prose didn't cite, so the answer was "Here is the result (9 rows)." with no table. The fallback now keeps them (`test_a_model_card_answer_keeps_its_tables_when_compose_falls_back`).
  - The recorded clarification in `chat_titanic.json` said "the three classes", a count the model typed; it now reads "the passenger classes", since the check refuses the old option.
  - Docs: TRD §7.4 (the wording module), §8.1 (clarifications, resolution, `ask_data`'s result checks, `closest` and `reading`, widget titles, compose's validator, the wording check), §8.2 (`ask_data`), §3.5's hygiene test; PRD ASK-6, STORY-3 and STORY-8 acceptance; App Flow §10.2.
  - BACKLOG: removed "Widget titles written in chat aren't checked" (STORY-3), "A chat `value:` label can show a count" (STORY-8) and "Some clarifying questions are open text" (ASK-6). Added: a name that matches two columns about equally isn't asked about before the query, and the result check's repair costs a call on an honest empty answer.
- **Decisions:**
  - A clarification for an unresolved name comes only after the SQL step can't write the query, not before it ("if critical", TRD §8.1 step 3). Before the query, "survival" (75 against `survived`) or "passenger class" would have stopped answers the SQL step reads correctly, a direct risk to the ask eval.
  - A date or a yes/no cell may still be a `value:` label (a category in time, not a measure); only number-type cells must be chips.
  - A route clarification that fails the wording check is answered as routed rather than repaired: a second route call that fails again would fall back to a bare `ask_data` and lose the route's entities.
  - Code-built clarification options are the file's own names, so they aren't wording-checked (a product called "Two-pack" stays a button).
  - A named column must be used only when its role groups, measures or dates the rows. In the second eval run "How many reviews are there?" resolved "reviews" to the free-text column `review`, the check asked for it to be used, and the repair turned `count(*)` into a count of `review` (the same 600 here, but not on a file with empty reviews). ID and free-text columns named like the records are now left out of that finding.
- **Ask eval** (`uv run sherlock eval ask`, live, one run at a time under `eval-locked.sh`):
  - At the branch's base (`781dc6e`, before this slice): **49/50**, 0 unsourced, median 9.7 s. Miss: "What does sibsp mean?" (the general sentence named neither siblings nor spouses).
  - After 2.7–2.9: **48/50**, 0 unsourced, median 13.7 s. Misses: "Which passengers paid more than 500?" routed to `ask_data` (a table, not a row list), and "Units sold by product" with no table. Neither the result check nor the wording check left a line in the log (no repair message names them), and answers that make no model call but the route took 2–3 s instead of under 1 s, so the run was slower across the board.
  - A second run with every miss dumped (a wrapper around the harness, not committed): **49/50**, 0 unsourced, median 10.6 s. Miss: "How accurate is the model?", compose failed twice on an existing rule (`value:model accuracy`) and the fallback was the empty answer above. The result check fired once ("How many reviews are there?", above).
  - With the role rule and the fallback fix, rebased on `origin/main` (receipts, the Tavily client, the data dictionary): **49/50**, 0 unsourced, median 10.7 s. Miss: "Which passengers paid more than 500?", routed to `ask_data` (four rows as a table, not a row list); the route call is unchanged by this slice, and slice 1's route check measured this kind of miss.
  - Receipts name the result check's call "Checked the result" (`Receipts.tsx`, with a test).
- **Gate:** `uv run pytest` 452 passed, 3 skipped; `pnpm test` 97 passed; `pnpm e2e` 1 passed.

### Tier 2 row 2b.2: answer cards re-run their stored queries

- **Done:**
  - **The cascade checks answer cards** (`stories.service.recheck_answers`, TRD §7.6's `rerun_fact_sql`): a `ready` answer card whose numbers read a column that changed since its sheet's version is `outdated` under "Ask first"; under "Automatic" its stored queries run again, and the same numbers keep it `ready` on a sheet of the new version, while moved numbers (or a query that no longer runs) make it `outdated`. The result carries `answers: { checked, kept, outdated }`.
  - **Refresh works on an answer card** (no longer `409`): a `stories` job with `answer_ids` runs its queries again, stores the new numbers and sets the changed badge when one moved; `409` only when a query no longer runs.
  - **What an answer reads** (`answer_depends`): its sheet's columns plus every column its facts' queries name. Add to Flow stores that union, since the result's column names alone are often aliases.
  - **A cascade is queued** when the dataset has a live widget, a live card or a run, so an answer card or a run without a dashboard is checked too (A6).
  - `queue_stories` never merges a widget request into an answer Refresh job.
  - Tests (`test_chat.py::test_an_answer_card_reruns_its_queries_when_its_columns_change`): an edit to a column the answer doesn't read checks nothing; an edit to `fare` re-runs "average fare by class" and leaves the card `outdated` with its old numbers; Refresh brings the new numbers, the changed badge and the current version.
  - Docs: TRD §3.3 (the cascade trigger, `answer_ids`), §4.6, §4.9 (Refresh), §7.6 (as built since 2b.2, replacing "isn't there").
  - BACKLOG: removed "Answer cards never go stale".
- **Decisions:**
  - Tier 2 rows run in parallel across sessions now, not strictly 2b.1 → 2b.10 (the owner asked for parallel work; `.claude/plans/parallel.md`).
  - Moved numbers make an answer card `outdated` rather than updating it silently: its words were written by the model about the old numbers and aren't re-composed. Refresh is the user taking the new numbers, and the changed badge says so.
- **Gate:** after rebasing onto the other sessions' slices 7, 8, 9, 10, T-0 and T-3 (tip `742fba7`, with 2b.2, 2b.3 and 2b.6): `uv run pytest` 453 passed, 3 skipped; `corepack pnpm test` 97 passed; e2e (through `e2e-locked.sh`) 1 passed. Before the rebase, at the first `6253c5a`: pytest 416 passed, 3 skipped; vitest 88 passed; e2e 1 passed.

### Tier 2 row 2b.3: change-detection gaps

- **Done:**
  - **Undo impact from the diff** (A3): `undo.undo_impact` takes every count from `diff_versions`, including rows quarantined again (undoing a restore) and the new `rows_restored` (undoing a quarantine); it said `quarantined: 0` before.
  - **`changes()`** treats `rows_restored` as a change of rows, and reads `restore_row_ids` on the step an undo undid, so undoing a restore affects every widget.
  - **`depends_on`** (A4): with the version's columns, `SELECT *` (also with `EXCLUDE`) and `a.*` of `t` read every column; a column qualified by an alias of `t` counts; `COUNT(*)` and a CTE's `b.*` don't. The cascade and the fact sheets pass the columns, so a pinned chat table updates.
  - **`ml.depends`** (A5) adds the columns of the run's selection's predicate.
  - **Outdated runs and the switch to Automatic** (A19): a run already `outdated` keeps its widgets affected, so a later cascade under Automatic re-runs it; `PUT /me/settings` switching Ask first → Automatic queues a cascade (`reason: "settings"`) for each dataset with an outdated card or run, which also tells the outdated cards again.
  - Tests: new `tests/test_change_detection.py` (one per gap: the undo's impact, an undone restore and `rows_restored` in `changes()`, `*`/`EXCLUDE`/alias/`COUNT(*)`/CTE in `depends_on`, a selection's columns in `ml.depends`); `test_stories.py::test_switching_to_automatic_brings_outdated_cards_and_runs_up_to_date`.
  - Docs: TRD §4.1 (the settings switch), §6.2 (undo impact), §6.4 (`depends_on`), §7.6 (change detection), §7.8 (undo impact).
- **Decisions:**
  - An aliased `t` resolves to the columns it names rather than to every column (the plan's wording): that's exact, and a `*` still reads everything.
  - A switch to Automatic re-tells every card left `outdated`, not only those an edit since touched: the user asked for the cards to update on their own, and outdated cards were waiting for exactly that.
  - BACKLOG: no line closes (A3–A5, A19 were audit findings) and none is added.
- `PUT /me/settings`'s new docstring changed the route's OpenAPI description: `openapi.json` and `schema.d.ts` regenerated (`scripts/dump_openapi.py`, `pnpm openapi`).
- **Gate:** after rebasing onto the other sessions' slices 7, 8, 9, 10, T-0 and T-3 (tip `742fba7`, with 2b.2, 2b.3 and 2b.6): `uv run pytest` 453 passed, 3 skipped; `corepack pnpm test` 97 passed; e2e (through `e2e-locked.sh`) 1 passed. Before the rebase, at the first `6253c5a`: pytest 416 passed, 3 skipped; vitest 88 passed; e2e 1 passed.

### Tier 2 row 2b.6: the rest of the backend

- **Done:**
  - **Syntheses are written again under Automatic** (A15): a cascade that leaves a synthesis `sources_changed` queues a `stories` job with its `synthesis_ids` (after the cascade, since stories jobs wait for it), which rewrites it with the changed badge; only syntheses with at least two usable sources are queued, the others keep Refresh. Under Ask first nothing is rewritten.
  - **The real row count** (A33): `run_query` adds `total`, the query's real row count, counted again only when the rows were capped at 2,000; the notebook's "first 50 of N rows" uses it.
  - **A deleted widget's runs** aren't exported as extra runs.
  - **Canvases and gone cards** (A34): purge prunes the canvases of the cards it hard-deletes and emits `canvas.updated`; a save that still holds a gone card's node drops it instead of answering `422` about it (a node for a card the canvas never had is still refused, so ownership holds), and the pruned etag makes the stale tab reload with `409`.
  - **The cleaning log** (A28): the cleaning screen loads the log so far from `GET /jobs/{jid}/log` and follows the live stream for new lines, each line once (`mergeLog`), instead of replaying the dataset's whole event stream; until the stream's first progress event it shows the job's stored progress.
  - Tests: `test_stories.py::test_under_automatic_a_synthesis_is_written_again_and_a_deleted_widgets_run_leaves_the_notebook`; `test_widgets.py::test_a_capped_result_reports_its_real_row_count`; `test_canvas.py::test_purge_prunes_the_canvas_and_a_save_drops_a_card_that_is_gone`; `cleaning.test.tsx` "loads the log so far from the job's own log and keeps each line once".
  - Docs: TRD §4.5 (`WidgetData.total`), §4.7 (validation, pruning by purge), §4.10 (`GET /jobs/{jid}/log` for the cleaning screen), §7.4.1 (rewritten under Automatic), §7.7 (the real count, a deleted widget's runs); App Flow §5 (the log).
- **Decisions:**
  - A synthesis is rewritten by a queued stories job rather than inside the cascade, so the cascade makes no extra model call and its own failure hook stays simple.
  - The plan's "validate drops unknown card nodes" is limited to cards that were on the stored canvas; dropping any unknown id would also accept another dataset's card IDs silently, which `test_canvas.py` rightly refuses.
  - Once purge has hard-deleted a widget, its runs lose their widget and count as finished runs no widget shows again (purge clears `runs.widget_id`). Left as is: a hard-deleted widget is ten minutes past its Undo.
- `test_only_usable_cards_feed_another_output` (slice 5) failed once in the gate: it took "the fare card" from a set, whose order changes with the hash seed, and expected no usable synthesis even when the synthesis didn't cite that card. It now takes the first fare widget in sorted order and expects the synthesis among the usable cards when it cites none; it passes under three hash seeds.
- **Gate:** after rebasing onto the other sessions' slices 7, 8, 9, 10, T-0 and T-3 (tip `742fba7`, with 2b.2, 2b.3 and 2b.6): `uv run pytest` 453 passed, 3 skipped; `corepack pnpm test` 97 passed; e2e (through `e2e-locked.sh`) 1 passed. Before the rebase, at the first `6253c5a`: pytest 416 passed, 3 skipped; vitest 88 passed; e2e 1 passed.

### Tier 2 row 2b.4: a version on every chat message

Built in the `chat-checks` worktree (Tier 2 rows run in parallel, as the owner asked for parallel sessions).

- **Done:**
  - Migration `006_message_version.sql` (the number `parallel.md` reserved): `messages.version`, the dataset's `current_version` when the message was written, filled for older messages with the newest version created at or before them (versions only go up; an undo is a new version). `Message` carries `version` (TRD §4.9, web `types.ts`).
  - **History lines say their version.** The context's recent messages and the running summary's lines read "[v5] assistant: …", so an answer from before an edit reads as older to the router and the SQL step.
  - **Add to Flow refuses an older answer.** `POST /messages/{mid}/pin` with `target: "flow"` answers `409` "This answer was worked out on version 3; the data is now version 5. Ask again to add the current numbers to Flow.", and `GET /chat` drops `add_to_flow` from an older answer's actions. An `answer` card's fact sheet is on the current version, so it can't hold an older version's numbers. Pinning a chart to the dashboard still works (the widget runs on the current version).
  - **`update_widget` merges the draft into the widget's spec** (`answerers.merged_spec`): the query, the view and its x and y (or a KPI's value) change; the row predicate and selection, `inherit_global_filters`, the other columns and the other view options stay. Before, the draft rebuilt the spec and dropped them.
  - **Selections are counted on the current version when read** (`widgets.service.selection_rows`): the chat context's words, `clean_selection`'s proposal and a cleaning plan's scope count the selection's usable rows now, not the stored `row_count` from the version it was made on (Schema §2.16 already said so).
  - Tests: `tests/test_chat_versions.py` (an answer's version, Add to Flow refused after an edit and offered again on a new answer, the "[v1]" history lines in the route prompt, a widget's predicate, `inherit_global_filters` and a view option kept through "make it a pie chart", `merged_spec` for a KPI, a selection of four counted as three after an edit in the proposal and the plan's scope, and the migration's backfill on a database migrated up to 005).
  - Docs: Schema §2.15 (`messages.version`) and §2.16 (as built); TRD §4.9 (`Message.version`, the pin refusal), §8.1 (history lines, `update_widget`, selections); App Flow §12 (Add to Flow); web `Message` type.
  - BACKLOG: no line closes (A8, A14, A35 and A36 were audit findings). Added under "Chat answers … don't say which version": the thread shows no mark on an older answer yet.
- **Decisions:**
  - Add to Flow **refuses** rather than labels an older answer: a card labelled "from v3" would still sit on the canvas beside current cards, and the trust rule (slice 5) keeps non-`ready` cards out of other outputs anyway. Asking again costs one message.
  - A message from before the migration whose time is before the file's first version keeps `version` NULL, and is treated as current (no refusal), since nothing says otherwise.
- **Ask eval** (`eval-locked.sh <worktree> ask`):
  - First run: **48/50**, 0 unsourced, median 10.2 s. Misses: "Which passengers paid more than 500?" (routed to `ask_data`, as in slice 12's runs) and "Units sold by product" (`SELECT SUM(units) … GROUP BY product`, with no product names). Not pushed.
  - Both misses showed up in slice 12's runs without this row too, so the rerun looked for a cause in the answers rather than in 2b.4. Second run: **48/50**, 0 unsourced, median 12.0 s. Misses: the same routing one, and "Average fare by port of embarkation" with the same shape of query (grouped by `embarked`, which it didn't select).
  - **Fix, generic (its own commit):** the result check (plan 2.7) finds a column the outer query groups by but doesn't select, and the one repair adds it (`answerers._hidden_groups`; a group by position or by an expression is left alone). TRD §8.1, `test_chat_checks.py`.
  - Third run, with the fix: **49/50**, 0 unsourced, median 10.9 s. Miss: "What does sibsp mean?" (the general sentence named neither siblings nor spouses, the base run's miss).
- **Gate** (rebased on `7c8cf4e`, with both commits): `uv run pytest` 492 passed, 3 skipped; `corepack pnpm test` 116 passed; `corepack pnpm build` ok; `pnpm e2e` 1 passed.

### Tier 2 row 2b.10: claim checks in code

Built in the `chat-checks` worktree.

- **Done:**
  - **`narrate.claims`**, run by `check_wording` on every story, overview bullet and synthesis (a failure is a repair, then the fallback). A sentence is split into clauses (commas, semicolons, colons, and, but, while, whereas); in each clause a ranking word is checked against the name nearest it (the first after it, else the last before it):
    - "highest", "most", "top" (and largest, biggest, greatest, maximum) must name `top_group`, `peak_period`, `max_x`, `max_y` or `driver_1`;
    - "lowest", "least" (and fewest, smallest, bottom, minimum) must name `bottom_group`;
    - "first" to "fifth" next to a column (a `column:` label or a `driver_<n>` chip) must be that factor's rank, where the facts rank factors at all: "Ticket comes third" needs `driver_3` = ticket (BACKLOG D6 F8). "First class" next to a value label isn't a rank.
    - "rises", "increases", "grows" (and "falls", "declines", "decreases", "drops") need a `trend` that says so or, when no trend says the opposite, a `change` or `correlation` of that sign: "survival decreases for lower classes" on a bar chart (D6 F8) has none.
    - A clause with no name claims nothing about a group and isn't counted. On merged sheets (`w3.top_group`, `c1.top_group`) keys are read without their prefix.
  - The story and overview prompts say to use these words only of what the facts name.
  - **The grounding eval counts them** (`grounding.card_claims`): "Claims checked" and "Claims failed" columns, `claims_checked` and `claims_failed` in the summary line, and each failure as a problem. A card the user edited isn't read (their words).
  - Tests: new `tests/test_claims.py` (the top and bottom groups, two clauses in one sentence, a name chip, a clause with no name; "Ticket comes third" against `driver_3`, `driver_1` as the top, "first class" not a rank; trend, change and correlation; the narrator refuses a wrong claim, on a merged sheet too; the eval's count). `test_grounding_eval.py`: the planted card's "It rose by 12 points" is now also an unbacked trend (three problems, not two). `test_stories.py`: the synthesis test's facts carry the card's `top_group`, as a real synthesis's do, and "highest for male" is refused.
  - Docs: TRD §7.4 (the claims check), §14 (the grounding eval's claims); PRD STORY-8 (requirement and acceptance).
  - BACKLOG: removed "Rankings the narrator states with no fact behind them" (D6 F8).
- **Decisions:**
  - The nearest name in the clause, not the sentence: "First class paid the most, and third class the least" checks "most" against first class and "least" against third.
  - A trend word is backed by a change or a correlation of the same sign when no trend fact contradicts it, so "increased from the first month to the last" passes on a `flat` trend with a positive `change`.
  - Comparatives ("higher", "more") aren't claims here: comparing two numbers across cards was already checked (`check_comparison`), and inside one card both numbers are chips.
- **Grounding eval** (`eval-locked.sh <worktree> grounding`, live): titanic3 9 cards and sales_dated 11, every one by the model; 68 of 68 chips grounded, every cited fact holding (65), 0 text runs with numbers, 0 causal phrases, 0 bad labels; **claims_checked 12, claims_failed 0**; both syntheses by the model; the stale-reuse scenario passes on both files. The claims check sent one story back for its repair ("most" said of `pclass` where the top factor is `sex`), and the repair passed.
- **Gate:** `uv run pytest` 497 passed, 3 skipped; `corepack pnpm test` 116 passed; `corepack pnpm build` ok; `pnpm e2e` failed once (its output wasn't kept), then passed twice in a row, with no change in between.

## 2026-10-26 (Mon, morning): new browsers turned away, and a cleanup for judging

The owner reported that https://sherlock-anw3.onrender.com didn't open in a private window or another browser, then asked for a cleanup that leaves the project ready to keep building and for judges to test.

- **Cause:** every request without a cookie got `429` "Too many new visitors from your network". Render's logs showed a `new user: ip <hash>, 2 forwarded hop(s)` line every 5.3 s, all `GET /api/v1/me` and all one hash, which was the hash of the owner's own public IP. Two background shells left by earlier Claude Code sessions were still running on the owner's machine: one (since 2026-10-24 22:21 local) looped `until curl …/api/v1/me … && [ now -gt now ]; do sleep 5; done`, whose second test can never pass, so it made a new user every 5 s for about 27 hours and kept that IP's window at the 300 cap; the other waited forever for `"boots":2x` in `/healthz` (boots is past 40). Both were stopped, and a fresh browser profile loaded the library at once. The Day 9 refusals (D9 H1) fit the same loop, which was running then; the logs show the cap keys on each visitor's own IP, so that backlog line is gone.
- **Done:**
  - Purge (Schema §6): users with no dataset at all, unseen for 24 h, are deleted, which also clears the loop's users; Cleaner work folders under `/data/.clean/` older than an hour are deleted unless their job is queued or running. `tests/test_purge.py` covers both.
  - The web app shows a refused first visit as a whole page ("Sherlock can't open a new workspace yet", the server's message, Try again), and any other failure of `GET /me` as "Sherlock couldn't start", instead of an app shell where every request fails. `useMe` doesn't retry a `429` (`StartupError.tsx`; `App.test.tsx`).
  - The empty library says that CSVs stay with the browser (App Flow §18's small print, which wasn't built).
  - `/healthz` reports `commit`, from `GIT_COMMIT` or Render's `RENDER_GIT_COMMIT`, so a deploy by hand can check that the new build is serving (D9 F13). `LOG_LEVEL` now sets the `sherlock.*` loggers' level.
  - The notebook's requirements cell says how to get pip into a uv venv (D9 F14).
  - Dropped `@radix-ui/react-tooltip` and `@visx/gradient`, which nothing imported; `THIRD_PARTY.md` lists what the web dependencies install, by license (D9 F11).
  - README and TRD §11: the deploy check compares `commit` with `main`, and says to poll `/healthz`, not `/api/…`, from scripts.
- **Decision:** 24 h for an empty workspace matches the other purge ages. A visitor who comes back later with no CSV loses only their settings.
- **How it was done:** in a separate worktree (`sherlock-cleanup`, branch `cleanup`), because another session was committing to `main` in the main checkout at the same time; the branch was rebased onto `main` and fast-forwarded in.
