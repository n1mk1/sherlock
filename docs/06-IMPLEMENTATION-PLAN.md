# Sherlock · Implementation Plan

Version 1.3 · 2026-10-26 · Build order from an empty folder to a submitted project. Deadline 2026-10-30 13:00 EDT; internal deadline 2026-10-29.

**Status, 2026-10-26.** Days 1–9 are built within the nine cuts (§2.0), merged to `main` and deployed (https://sherlock-anw3.onrender.com). After the Day 8 freeze the owner approved two exceptions: the cleaning plan (PRD CLEAN-8a, CLEAN-8b) and the agent-layer and Tavily work (route guards, chat checks, receipts, web retrieval with Tavily, the data dictionary). Day 10 (submission) is left.

---

## 1. Working rules

- **Build in vertical slices.** Each day ends with something that runs end to end, even if thin. A horizontal layer that can't be exercised isn't done.
- **Commit each verified slice to `main` and push.** Use a feature branch only for work longer than half a day.
- **Mock the model when building UI.** Recorded LLM replies (`api/tests/fixtures/llm/`, loaded through `LLM_MOCK`) let the frontend and pipelines be built without credits or waiting on Token Factory.
- **Definition of done for a task:** it runs on the Titanic sample locally, its automated test passes, it's reachable from the UI (if it has one), and it's committed.
- **Cut, don't slip.** Each day has a "must" and a "stretch". If a must isn't done by the end of the day, the cut order in §5 applies the next morning.
- **Keep `FEEDBACK.md` open.** Every surprise with Token Factory, Nemotron, hosting or Bklit goes in it when it happens.

Two-person split, if available: **Backend** owns `api/` (pipelines, agent, ML, data), **Frontend** owns `web/` (shell, grid, charts, Flow, chat UI). The TRD's API contract is the handshake. The team is solo, and the frontend builds against the real API (§2.0).

---

## 2. Day-by-day

### 2.0 Replan · 2026-10-24 (in force)

Nothing was built Oct 20–23, so the build started on Oct 24, five days late, with a solo team. Approved by As Wasti on 2026-10-24:

- **Cuts applied:** all nine rows of the cut order in §5. The table below says what each removes. The never-cut list in §5 is unchanged.
- **Dates:** the schedule below replaces the dates of Days 1–9. The days keep their item numbers as references ("D2.3" is Day 2, item 3). Each item keeps its definition of done (§1); an item narrowed by a cut is done when what remains is done. Days 1–9 finished on 2026-10-25, ahead of this schedule.
- **Process changes (no scope dropped):**
  - The frontend builds against the real API, not an OpenAPI mock server (this replaces D2.9's mock handler). Recorded LLM fixtures (§1) are still used.
  - The three Day 1 spikes (D1.5) became 1-hour checks at the start of the work that uses them: Bklit before the dashboard (D4.7), Glide before the CSV tab (D5.1), react-grid-layout with the dashboard grid. All three passed; the results are in `FEEDBACK.md`.

| Date | Work (day.item) |
|---|---|
| Sat Oct 24 | D1.1 scaffold · D1.2 Nemotron smoke test · D1.4 migrations, identity, ownership, rate limiter, `/me` |
| Sun Oct 25 | D1.3 hello-world deploy first (timeboxed to 3 h; the VM fallback the same day if the `/data` exit check fails) · D2.1–D2.8 backend |
| Mon Oct 26 | D3.1–D3.5 the Cleaner · D4.1–D4.3 widgets, dashboard builder, agent v1 · D2.9–D2.10 shell and Library |
| Tue Oct 27 | D3.6 cleaning screens · D4.4–D4.8 frontend · D5 (within cut 5) · D6.1–D6.6 (within cut 6) |
| Wed Oct 28 | D7 (within cuts 4 and 7) · D8.1–D8.6 (within cuts 2, 3 and 9) · **feature freeze at 12:00** · D9.1–D9.5 ship |
| Thu Oct 29 | Day 10: video, Devpost, `FEEDBACK.md`, submit |
| Fri Oct 30 | Morning buffer only |

What each cut removes:

| Cut | Removed | Stays |
|---|---|---|
| 1 | D4.4: the settings dialog beyond four settings | mode, accent, chatbar, after-upload |
| 2 | D8.1, D8.2: `propose_card_edit` and "rewrite" proposals | |
| 3 | D8.1, D8.2: the "take it toward X" path, direction nodes and the building-state checklist | canvas, card/note/synthesis nodes, labeled edges, "make sense" |
| 4 | D7.2, D7.4, D7.5: the `linear_regression` and `logistic_regression` methods, the method control, the coefficients and residuals views, Compare with Auto | Auto; `repro.py` for Auto |
| 5 | D5.1–D5.3, D5.7: range selection, TSV copy/paste, fill down, duplicate row, buffer undo/redo, the Review changes drawer, find and replace, the filter row, quick views, the cell provenance tooltip, status-bar stats, right-click menus, jump to row, Ctrl+arrow | the paged grid, cell edits, add/delete row, sort, find, Save (conflict handling, Discard), the Changes panel with Undo; kept because other P0s need them: Clean with AI (P0-02), the Download/Export notebook entry (P0-12), Restore for quarantined rows (Rule 3) |
| 6 | D6.2: the material hash and the material-change check | every affected card is re-narrated |
| 7 | D7.2, D7.4, D7.5: the `predict` recipe, the predictions table, predicted cells, explain-row; `samples/titanic_blanks.csv` | `driver_analysis` |
| 8 | D4.7: brushing and the brush → selection chip (no spike ran first, so brushing was the safe cut) | click-to-filter; ML scope comes from a filter or the whole dataset; §9 moment 6 filters instead of brushing |
| 9 | D4.3: the suggested-questions endpoint and UI; D4.4, D8.3: the `?` shortcuts sheet | chat; the `/` shortcut |

**Hosting change (owner's decision):** D1.3 deploys to Render (`render.yaml`, PRD §9) instead of a Nebius Serverless Endpoint, because the account's Nebius AI Cloud tenant is suspended and the rules don't require Nebius hosting. The exit check is unchanged. The Nebius steps in D1.3 and D9.2 stay valid as the alternative (`scripts/deploy.sh`).

If a Must from this table slips, §5 has nothing left to cut, so any further drop needs a PRD change by the owner.

### Day 0 · Oct 19 (evening): decisions locked

- [x] These six documents written.
- [x] Nebius account and project, Token Factory access, credit balance noted. Token Factory serves every model call; the balance is in `FEEDBACK.md`; the AI Cloud tenant is suspended (§2.0).
- [ ] The GitHub repo `sherlock`, public, MIT license visible. The repo is `n1mk1/sherlock` with `LICENSE` (MIT) at the root, but it is still private.

### Day 1 · Oct 20: foundations, model facts, first deploy

Done. The scaffold, the Nemotron smoke test (Ultra, Super and Nano pass; `LLM_TOOLS_MODE=native`; `embed` is empty because the catalog has no NVIDIA embedding model), the Render deploy with the `/data` exit check passed (TRD §11), and identity, ownership, rate limits and `/me`. The theme-token stretch is done.
Items: 1 scaffold (`api/`, `web/`, `docker-compose.yml`, `.env.example`, README, `FEEDBACK.md`, `LICENSE`, CI) · 2 Nemotron smoke test (sets `MODEL_LARGE/MEDIUM/SMALL/EMBED`, `NVIDIA_EMBED_MODELS`, `LLM_TOOLS_MODE`, TRD §3.5) · 3 hello-world deploy (§2.0 hosting change) · 4 migration 001, the `sherlock_uid` identity middleware, the ownership dependency, the rate limiter, `GET /me`, `PUT /me/settings` · 5 spikes: Bklit, Glide Data Grid, react-grid-layout (run as 1-hour checks, §2.0).

### Day 2 · Oct 21: ingest, profile, steps, sandbox, shell

Done. Upload to `v1.parquet` with `_row_id`, the profile with its 16 detectors and the data card, versioned steps with undo, the sandbox and `sherlock-sandboxd`, jobs over SSE with replay, the rows API, the `llm/` client, and the typing step as step 1. The web shell and Library run against the real API (§2.0).
Items: 1 `ingest/` and `POST /datasets`, `POST /datasets/sample`, `GET /datasets`, `GET /datasets/{id}` · 2 `profile/` and `cleaning/detectors/`, `GET /datasets/{id}/datacard` · 3 `steps/` (`commit_step`, `notebook_code` on every step, undo latest) · 4 `sandbox/` worker and launcher · 5 `jobs/` runner, SSE with replay, the `profile` job · 6 rows API (`GET /rows`, `POST /edits`) · 7 `llm/` client, schemas, repair, retries, budgets, `llm_calls` · 8 the typing step (TRD §7.1 step 3b) · 9 three-panel shell, theme tokens, generated API client, SSE hook with resume, TanStack Query and stores · 10 Library panel (status badges, dropzone, import preview, sample button).

### Day 3 · Oct 22: the Cleaner

Done. The headless Cleaner (TRD §7.2) with verifiers, gate and helpers, the corruption benchmark, "Use as is", the `sherlock` CLI, the seeded samples, job cancellation, and the cleaning screens. `sherlock clean sample` ran headless with the real model and deleted 0 rows; the Titanic expectations were checked by hand.
Items: 1 `cleaning/verifiers.py`, `gate.py`, `helpers/` · 2 `cleaning/loop.py`, `POST /datasets/{id}/clean`, `GET /datasets/{id}/report`, `job.log` events · 3 `eval/corruption.py` · 4 "Use as is" (`POST /use-as-is`) · 5 `sherlock` CLI (`clean`, `eval`, `export`), the synthetic samples, `POST /jobs/{jid}/cancel` · 6 cleaning offer, in-progress and report screens.

### Day 4 · Oct 23: shell, dashboard builder, widgets, chat v1

Done within cuts 1, 8 and 9. Widgets with SQL compile and validation, the dashboard builder, chat v1 with eval v0, the rail, job tray and four-setting dialog, the react-grid-layout dashboard with the Bklit adapter and click-to-filter, and the chat thread. Not built: suggested questions and the shortcuts sheet (cut 9), brushing (cut 8); the dashboard's Filter button and filter builder are not built yet.
Items: 1 `widgets/`, widget CRUD, `/data`, `/explain`, `PUT layout`, `POST /datasets/{id}/selections` · 2 `dashboard/` candidates, scoring, curation, layout, `build_dashboard` job · 3 `agent/` v1 (route → `ask_data` / `find_rows` / `explain_widget` / `ask_history` → compose → verify; `create_widget`), `POST /datasets/{id}/chat`, eval v0 in `samples/eval/ask_questions.yaml` · 4 shell completion: rail, settings dialog, shortcuts sheet, job tray with Cancel and Retry · 5 Library rename and delete with Undo · 6 widget menu and the 20-widget warning · 7 dashboard grid, widget shell, Bklit adapter, "How do you know?", click-to-filter, brush, Add widget drawer · 8 chat bar and thread, blocks, sources, suggested questions, `/` shortcut.

### Day 5 · Oct 24: CSV tab

Done within cut 5. The paged Glide grid with marks, cell edits, add/delete row, Save with conflicts and Discard, Find, Clean with AI, the Changes panel with Undo and replay, cascade v0, Restore for quarantined rows, and notebook export v0 with its execution test. Code in the Changes panel is a plain mono block (no Shiki). Not built yet: the type-aware cell editors (PRD CSV-5, not covered by cut 5) and the export dialog's Save and export button.
Items: 1 Glide grid, header metadata, cell marks, provenance tooltip · 2 editing buffer and Save → `POST /edits` · 3 toolbar: Find, Download, Clean with AI popover · 4 Changes panel with Undo and the replay confirmation · 5 undo with replay, `user_edited_cells`, "run cleaning on new rows", cascade v0 · 6 notebook export v0 (`notebook/`, `POST /datasets/{id}/exports/notebook`, `GET /exports/{id}`, the export dialog, Ctrl+Shift+E) · 7 right-click menus, jump to row, Ctrl+arrow (PRD CSV-3, CSV-14) and Restore for quarantined rows.

### Day 6 · Oct 25: stories and the cascade

Done within cut 6. Fact sheets, the narrator with chip-only output (on `medium`, TRD §7.4), `verify`, the overview, the column-level cascade (every affected card re-narrated; no material hash), the story panel with two-way hover linking and the TipTap editor, the custom visx charts, and story cards in the notebook. The exit ran with a `fare` edit, since no widget on the sample dashboard read `age`.
Items: 1 `stories/` fact sheets, significance helpers, relations, narrator, `verify_claim`, overview, `stories` job, `card.updated` · 2 cascade (TRD §7.6) · 3 story panel, chips and evidence drawer, hover linking with the spotlight, badges, TipTap editor with the `/` picker, the suggestion side by side, Ask why → chat · 4 cascade UI · 5 visx histogram, heatmap, box plot, scatter (gauges render as a KPI tile) · 6 story cards in the notebook.

### Day 7 · Oct 26: ML

Done within cuts 4 and 7. `driver_analysis` with Auto (`ml/plan.py`, `ml/core.py`, `ml/analysis.py`), planted-truth tests (`sherlock eval ml`), the runs API, the chat answerers `ask_why`, `ask_stats`, `ask_model`, `ask_meaning` and `app_help`, the analysis UI with importance, partial dependence, confusion, ROC and "Who did it get wrong?", and `repro.py` (`ml/repro.py`, embedded by `notebook/cells.py`) whose metrics match the model card. Not built: predictions, OOD, calibration and explain-row (cut 7), and the `TimeSeriesSplit` choice (TRD §7.5).
Items: 1 scope, framing, leakage, split, preprocessing, baselines, explain · 2 recipes, registry, manifests, `GET /recipes`, runs API, caching, `run.updated`, the builder's driver widget · 3 answerers and tool exposure by tab (TRD §8.2) · 4 analysis dropdown, setup form from the manifest, progress, result views, model card drawer, `?rows=` to the CSV tab, Outdated with Re-run · 5 `repro.py`, `GET /runs/{rid}/code`, run cells in the notebook (metrics within 0.5 pp).

### Day 8 · Oct 27: Flow, polish, freeze

Done within cuts 2, 3 and 9. The Flow canvas (JSON Canvas with an etag) on React Flow with "make sense of this" synthesis cards, error boundaries and the offline banner, export entry points from Flow and chat, eval ask at 50 questions plus the grounding eval, chat proposals and multi-step plans, job checkpoints, the purge job and the Playwright flow test. The feature freeze applies from here (the owner's two exceptions are in the status line).
Items: 1 `canvas/`, `add_canvas_node`, `add_canvas_edge`, `ask_story`, "make sense", "take it toward X", rewrites · 2 Flow tab: nodes, labeled edges, connect mode, palette, minimap, selection → chat context, direction checklist, "Open widget" · 3 toasts with Undo, `?` sheet, remember-where-I-was, empty states, error boundaries, offline banner, notebook export from Flow and chat, canvas notes in the notebook · 4 eval ask ≈ 50 and the grounding eval · 5 chat completion: value-index resolve, clarifications, multi-step plans, follow-up focus, `update_widget`, `edit_cells` and `clean_selection` proposals, Add to Flow · 6 checkpoints and resume, the purge job, the Playwright flow test (`corepack pnpm e2e`) · 7 feature freeze.
Results (D8.4, live): eval ask 49 of 50, 0 unsourced; grounding 69 of 69 chips matching their facts, no digits or causal words.

### Day 9 · Oct 28: ship

Done. The cached sample (built once with the real models, cloned per user with fresh IDs; it ships in the image at `api/samples/seed/titanic3/`, TRD §4.2), the deploy with the five-file set checked on the public URL and every notebook executed in a fresh venv, the README, `THIRD_PARTY.md`, and the isolation and rate-limit checks (`scripts/live_check.py`). The sample's notebook is `docs/examples/titanic3-v4.ipynb` (the cached sample is v4). Still the owner's: the cold-start user tests and the by-hand baseline (§7).
Items: 1 `scripts/seed_sample.py` and the sample clone · 2 final deploy, the five-file end-to-end set on the public URL, the example notebook in `docs/examples/` · 3 README in the §7 order, with latency, tokens and cost per role · 4 `THIRD_PARTY.md`, Bklit Studio absent, the sample's license note · 5 rate limits, budgets and isolation on the public URL.
Results (D9.2, public URL, 2026-10-25): 31 of 31 checks; titanic3 built in 54 s, sales_dated 48 s, reviews_text 46 s, broken_latin1 cleaned and built in 61 s, wide_messy cleaned in four steps and built in 685 s; all five notebooks passed `sherlock eval notebook --sets all` in fresh venvs.

### Day 10 · Oct 29: submit

1. Record the video from the demo script in §9: a screen recording of the live site, with voice-over and a caption for each hero moment. Upload it to YouTube (public). The live rules say the video "should be less than three (3) minutes" and judges needn't watch past 3:00, so it ends by 2:55.
2. Write the Devpost description with the sections in §7.
3. Finalize `FEEDBACK.md` into the feedback field, in the structure in §7.
4. Submit. Verify the submission page shows the repo, URL, video and track.

Before submitting, also: make the repo public (after a secret scan), run the user tests and the baseline (§7), fill in the README's figures, and set `TAVILY_API_KEY` on the deployed service.

### Oct 30 (morning): buffer only. No changes to the deployed app unless it is down.

---

## 3. Task inventory by module (checklist)

A box is ticked when everything on its line is built except what a cut removed (§2.0). A line stays open while a part outside the cuts is missing.

### Backend

- [ ] `config.py`, `main.py` lifespan (migrations, job runner), `/healthz`, `/metrics`: all but `/metrics`
- [x] `db/` migrations 001–008 (`db/migrate.py` applies each file it hasn't, by number); repositories for users and datasets (`db/users.py`, `db/datasets.py`); every other table is read and written by the module that owns it
- [x] identity middleware, ownership dependency, rate limiter
- [x] `storage.py` folder layout, locks, byte accounting (`folder_bytes`)
- [x] `ingest/` sniff, import, `_row_id`, sample loader (`sample_seed.py`)
- [x] `profile/` types, roles, stats, histograms, top values, issues, value index, the typing step (D2.8). Embeddings are optional and off: the catalog has no NVIDIA embedding model
- [x] `cleaning/detectors/*` (16 detectors)
- [x] `cleaning/verifiers.py`, `gate.py`, `helpers/*`, `loop.py`, prompts (D3.1, D3.2); `plan.py` (CLEAN-8a, CLEAN-8b)
- [x] `sandbox/` worker, `sherlock-sandboxd` launcher, limits, allowlist, protocol
- [x] `steps/` commit, undo latest, undo with replay (D5.5), lineage queries, user-edited cells
- [ ] `jobs/` runner, events, SSE, cancellation, checkpoints, purge job: the Nebius Serverless Jobs backend isn't built
- [x] `widgets/` spec, compile, validate, execute, cache, explain; SQL and analysis widgets (D4.1, D7)
- [x] `dashboard/` candidates, scoring, curation, validation, layout, job; custom-chart candidates (D6.5) and the driver widget (D7.2)
- [x] `stories/` fact sheets, stats helpers, relations, narrator, verify, overview, cascade (D6); no material hash (cut 6)
- [x] `ml/` plan, core, analysis, registry, runner, repro: `driver_analysis` with Auto (D7). Explain-row and predictions (cut 7) and compare-auto (cut 4) are cut
- [x] `agent/` loop, router, resolve, 11 answerers (`ask_data`, `find_rows`, `explain_widget`, `ask_history`, `ask_why`, `ask_stats`, `ask_model`, `ask_meaning`, `app_help`, `web_context` on every tab, `ask_story` on Flow), actions, verify, compose, focus, summaries, the planner, `edit_plan` (CLEAN-8b); suggestions are cut 9
- [x] `llm/` client, schemas, repair, budgets, logging (D2.7)
- [x] `web/` Tavily client and cache, `agent/web.py` (`web_context`, column meanings from the web, the data dictionary, the web eval). Web context on anomaly cards (PRD STORY-9) isn't built
- [x] `canvas/` model, persistence, pruning (D8.1)
- [x] `notebook/` exporter job (`jobs/export.py`), cell renderers (load, helpers, step, edit batch, widget, chart, run, card, note), repro code, embedded outputs, allowlist scan, cache, `exports` table, download endpoint, nbconvert execution test (D5.6, D6.6, D7.5, D8.3)
- [x] chat threads, messages, pin and proposals (`routers/chat.py`, `agent/loop.py`, `agent/actions.py`, `routers/proposals.py`; there is no `chat/` package)
- [ ] `routers/*` for every endpoint in TRD §4: all but the cut ones and the `{ prompt }` form of `PATCH /widgets/{wid}`, which answers `422` (TRD §4.5)
- [x] `eval/` corruption benchmark, planted-truth, grounding, ask-anything, notebook, web (§4)
- [x] `scripts/` `seed_sample.py`, `deploy.sh`, `live_check.py`, `example_notebook.py`, `dump_openapi.py` (§4)
- [ ] tests: unit, integration (mocked LLM), fixtures: all but the mocked clean → build → stories run on all five files of the end-to-end set (TRD §14); the five files are only imported and profiled (`api/tests/test_samples_and_eval.py`)

### Frontend

- [x] theme tokens (light and dark, five accents, `app/theme.css`), fonts, mode, accent and reduce-motion applied by `app/ThemeSync.tsx`. The Bklit charts' Motion animations don't follow the reduce-motion setting (no `MotionConfig`; some follow only the OS preference)
- [x] API client (generated), SSE hook with resume, TanStack Query, error boundaries (`components/shell/ErrorBoundary.tsx`)
- [x] stores (`src/state/`): `ui` (panels, rail, Edit layout, focused widget, the chat thread's state), `filters` (global filter), `edits` (the buffer), `flow`; settings live in the `me` query; the selection is cut 8
- [x] shell: panels, rail, tabs, header rows, job tray, settings dialog (the four cut-1 settings), toasts; the shortcuts sheet is cut 9
- [x] library: list, status badges, upload, dropzone overlay, import preview, sample, rename/delete with Undo
- [x] cleaning: offer, in-progress (log, so-far, checks), report view, the cleaning plan panel (`components/dataset/`)
- [ ] dashboard: grid, widget shell (all states, Outdated), filter bar, add-widget drawer, explain drawer, KPI tile: all but the Filter button and filter builder
- [ ] charts: Bklit components, adapter, custom heatmap/histogram/box/scatter, highlight/point, click-to-filter, table view, accessible summary: all but the Bklit charts' accessible summary (the custom visx charts have one); brushing is cut 8
- [ ] csv: grid data source, theme bridge, marks, editors, buffer UI, toolbar, find bar, changes panel, clean-with-AI popover, status bar (row count, cell count, position): built within cut 5, except the type-aware editors (PRD CSV-5, P0)
- [x] ml: dropdown, setup form from the manifest, progress, result views (importance with partial dependence, confusion, ROC; `MlResult.tsx`), model card drawer; predicted cells are cut 7
- [x] stories: panel, card, chip, evidence drawer, badges, editor, suggestion view, hover linking, spotlight
- [x] flow: canvas, node types, edges and labels, connect mode, palette, minimap, context chip; the direction checklist is cut 3
- [x] chat: bar, thread, renderers (number, table, chart, text, proposal, clarification, plan), sources, Pin, Add to Flow; suggested questions are cut 9
- [ ] export: dataset menu (⋯), Download menu, export dialog, progress toast with Download again, Ctrl+Shift+E, Flow palette and chat entry points: all but the dialog's Save and export button
- [x] Playwright flow test (`web/e2e/flow.spec.ts`, `corepack pnpm e2e`): sample → dashboard and stories → ask → a cell edit from chat → its stories update → Flow "make sense" → Export notebook → file downloaded → a chart changed from chat and undone → the cell edit undone, with axe checks and the production CSP

---

## 4. Environments and commands

`uv` commands run in `api/` unless they say `--project api` (then from the repo root). pnpm comes through Corepack: run it as `corepack pnpm …` in `web/` (`web/package.json` pins `pnpm@12.15.0` and Node ≥ 24).

| Purpose | Command |
|---|---|
| Install | `uv sync` (in `api/`) · `corepack pnpm install` (in `web/`) |
| Run locally | `docker compose up` (API on :8000, web on :5173), or `uv run uvicorn sherlock.main:app --reload` plus `corepack pnpm dev` (Vite proxies the API to `VITE_API_TARGET`, default `http://localhost:8000`) |
| Tests | `uv run pytest` (the `live` Token Factory tests are deselected; `-m live` runs them) · `corepack pnpm test` (vitest) · `corepack pnpm typecheck` (`tsc -b`; vitest and e2e don't type-check) · `corepack pnpm build` (`tsc -b`, then `vite build`) · `corepack pnpm e2e` (`vite build`, then the Playwright flow) |
| Evals | `uv run sherlock eval corruption` · `… eval ask` · `… eval ml` · `… eval grounding` · `… eval notebook` (export and execute in a fresh venv) · `… eval web` (offline on recorded fixtures; `--live` needs `TAVILY_API_KEY`, `--record` rewrites the Nemotron fixtures). Every eval but `ml` takes `--sets a,b`; `notebook --sets all` is the five-file end-to-end set (TRD §14) |
| Clean a file headless | `uv run sherlock clean <file.csv or sample> [--timeout 900]`: imports it, prints the live log and the report |
| Model-call stats | `uv run sherlock llm stats [--days N] [--json]`: per purpose and role, p50/p95 latency, tokens, repair, fail and fallback rates, read-only from `llm_calls` (TRD §14) |
| Export a notebook | `uv run sherlock export notebook <dataset_id> --out out.ipynb` |
| Seed the sample | `uv run --project api python scripts/seed_sample.py [--out DIR] [--keep-data]`: writes `api/samples/seed/titanic3/`. `--keep-data` keeps the seed's cleaned data and reruns its analyses and stories (TRD §4.2) |
| Deploy | Render (prod): push to `main`, then a Manual Deploy in the Render dashboard. CI is blocked, so `autoDeployTrigger: checksPass` never fires (README "Deploy", TRD §11). Then check that `/healthz` reports the new `commit`. Nebius alternative: `./scripts/deploy.sh setup` once, then `./scripts/deploy.sh` (build, push, restart), `./scripts/deploy.sh check` (the `/data` exit check), `./scripts/deploy.sh url` |
| Check the deployed site | `uv run --project api python scripts/live_check.py [--url …] [--files all\|none]`: health, the instant sample, isolation, rate limits, a sourced answer, the cascade; `--files all` also uploads the five-file set and executes each exported notebook here |
| Refresh the example notebook | `uv run --project api python scripts/example_notebook.py` (writes `docs/examples/titanic3-v<N>.ipynb` and its raw file from the cached sample) |
| Generate the API client | `uv run --project api python scripts/dump_openapi.py`, then `corepack pnpm openapi` (reads `web/src/api/openapi.json`, TRD §3.1) |

Environments:
- `local`: compose sets `DATA_DIR=/data` in the container (`./data` on the host). Without Docker, `.env.example`'s `DATA_DIR=./data`. The LLM can be mocked with `LLM_MOCK`, set to a fixture file or folder such as `tests/fixtures/llm` (from `api/`).
- `prod`: the Render web service with a disk at `/data` and the real Token Factory. A Nebius Serverless Endpoint is the alternative.

---

## 5. Cut order (apply the morning after a missed "must")

If the team is solo on Oct 20, cuts 1, 2, 3, 4 and 7 apply from Day 1. This table is the only way a P0 item may be dropped (PRD §5).

**Applied 2026-10-24: all nine cuts.** §2.0 lists what each removes.

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

Sample files live in `api/samples/`.

| File | Purpose | Source |
|---|---|---|
| `titanic3.csv` | the sample and eval baseline | OpenML 40945, bundled: 1,309 rows, 14 columns, ARFF `?` written as empty cells |
| `titanic_blanks.csv` | prediction demo (50 `survived` values blanked) | derived. Not made: cut 7 removed `predict` |
| `sales_dated.csv` | time-series path (5,000 rows × 8, monthly) | generated |
| `wide_messy.csv` | 60 columns, mixed formats, sentinels (800 rows) | generated |
| `reviews_text.csv` | free-text column (600 rows × 6) | generated |
| `broken_latin1.txt` | wrong delimiter (`;`), Latin-1, header on row 3 (150 data rows × 4) | generated |
| `eval/ask_questions.yaml` | 61 questions over `titanic3.csv`, `sales_dated.csv` and `reviews_text.csv`, with expected answers and tolerances; every PRD ASK-2 area has one | written by hand (v0 with D4.3, 50 with D8.4, extended since); expected values computed with DuckDB from the CSVs |
| `eval/web_questions.yaml`, `eval/web/llm.json`, `eval/web/tavily.json` | the web eval's 20 questions, recorded Nemotron replies and hand-made Tavily stand-ins (TRD §14) | written by hand; `--record` rewrites `llm.json` |
| `seed/titanic3/` | the cached sample that Try with sample clones (TRD §4.2) | `scripts/seed_sample.py` |
| `samples/eval/corruption/*` | clean sets plus the injection config | code, not files (below) |

The five-file end-to-end set is `titanic3.csv`, `sales_dated.csv`, `wide_messy.csv`, `reviews_text.csv` and `broken_latin1.txt`. `titanic_blanks.csv` would only serve the prediction demo. The four synthetic files were generated once from seeded code and are committed as they are.

In `broken_latin1.txt` the two preamble lines use the data's delimiter, so the sniffer reads them as data (152 rows) unless the import preview sets header row 3. This header-detection gap is known (App Flow §18: "auto-detection tries the first 5 rows").

The corruption benchmark's clean sets come from `sherlock/eval/synthetic.py` (seeded generators; `titanic_clean` is the sample's complete rows on eight plain columns), and the damage plan (column, kind, share, seed) is in `sherlock/eval/corruption.py` (TRD §14):
- `titanic_clean`, `sales` and `hr`: the original three sets.
- `dates_dmy` and `dates_mdy` (`synthetic.visits`, 400 rows whose every date reads both ways, written day-first in one and month-first in the other) and `lookalikes` (`synthetic.lookalikes`, 600 rows with "Plan A"/"Plan B", "Region 1" to "Region 4" and "Austria"/"Australia"). They score a guess and a wrong merge.
- `dates_dmy_picked` and `dates_mdy_picked`: the two date sets cleaned with the order picked in the plan.

---

## 7. Submission artifacts

What each artifact must contain is set by PRD §12 (the official rules and the judges' rubric). The owner of every artifact is As Wasti.

- **Repo:** `README.md`, `LICENSE`, `FEEDBACK.md`, `THIRD_PARTY.md`, `docs/` (these), the architecture diagram (the README's Mermaid flow), a screenshot, and `docs/examples/titanic3-v4.ipynb` (the sample's exported notebook, viewable on GitHub, with its raw file). Public and readable without a login; `LICENSE` (MIT) at the root so it shows at the top of the repo page; no secrets in the history (`.env` ignored, a secret scan before making it public). `FEEDBACK.md` is kept from Day 1 and finalized on Day 10.
- **README sections, in order:** what Sherlock is in two sentences and the hosted URL · a screenshot · try it (sample, then your own CSV) · **NVIDIA models and Nebius** (a table per role: model ID, what it does, median latency, tokens and cost per sample run; the Nebius services the deployed app uses; the request/data-flow diagram) · how trust works (sources, chips, verifiers, quarantine) · results (cleaning benchmark, ML planted-truth tests, grounding test, ask-anything eval, user test and baseline comparison) · **known limitations** (failed eval questions, cleaning cases the benchmark misses, files that fail, anonymous identity with no recovery, 7-day expiry, anything not shipped from P0) · accessibility · local setup and run (`.env.example`, a Token Factory key, `docker compose up`) · deploy · tests and evals · license and third-party notices.
- **User tests and baseline:** for each tester (at least 3, none who has seen Sherlock): who they are, the CSV, the task, time to first sourced answer, where they hesitated, what they said, what was changed because of it. Plus the baseline comparison: the same 3 questions on the same file by hand and with Sherlock (time, steps, and how many answers could be traced to their source). Results go in the README's Results.
- **Public URL** on Render (or the Nebius alternative), live through the judging period and the winner announcement (PRD §9, TRD §11).
- **YouTube video** under 3:00, public, from the §9 script. Day 10.
- **Devpost description, in this order:** the problem and who has it (PRD §3.1) · what Sherlock does, in one line · the demonstrated result (benchmark, eval and user-test numbers) · how it works (architecture, which NVIDIA model does what and why that size, what runs on Nebius) · how it differs from existing tools (PRD §3.2) · limitations · what comes next (P1 and P2 highlights). Day 10.
- **`FEEDBACK.md`,** written for the Most Valuable Feedback criteria (completeness, viability, potential impact). For each of Token Factory, the Nemotron models (per model) and Nebius hosting: what we used it for, what worked, each problem with steps to reproduce and its effect on the build, and a concrete, buildable suggestion with who it would help.
- **Devpost form:** track (Best Apps and Agents), URL, video, repo, feedback, pre-existing project (no), city (if an IRL event was attended). Day 10.

---

## 8. Daily checklist

Each day: pull → run tests → work the "must" list top-down → commit per slice → update `FEEDBACK.md` → push.

---

## 9. Demo script (video, ≤ 3:00)

The live rules ask for *less than* three minutes (Day 10 item 1), so the script ends by 2:55.

The hero moments the PRD's video metric refers to, in recording order. Every moment that uses a model carries a small caption naming the NVIDIA model and the Nebius service behind it (for example "Nemotron 3 Ultra on Nebius Token Factory plans each fix"), so the integration shows throughout.

1. 0:00 to 0:15. The problem and who has it in one line (PRD §3.1), then Try with sample: the dashboard and its stories appear in seconds.
2. 0:15 to 0:40. Upload a messy CSV: the import preview, the cleaning plan (untick one fix, ask the chat to add a step), the headless cleaning log, the report with "rows deleted: 0".
3. 0:40 to 1:00. Hover a widget to light up its story card, then click a number chip: "How do you know?" shows the SQL.
4. 1:00 to 1:25. Ask a question in chat and get a sourced answer; pin it to the dashboard. Pin to dashboard shows only under a chart block (`agent/loop.py`), so use a question whose answer has a chart.
5. 1:25 to 1:45. Edit a cell in the CSV tab and save: only the dependent cards update. Undo the step.
6. 1:45 to 2:10. Click a bar to filter (cut 8 removed brushing), run "What drives this?", and read the model card against its baselines, with the leakage column excluded.
7. 2:10 to 2:30. On the Flow canvas, select three cards and run "Make sense of this": a synthesis card with chips appears.
8. 2:30 to 2:50. Export the notebook and run it in Jupyter: it rebuilds the current version.
9. 2:50 to 2:55. Close on the architecture: which Nemotron model does what on Nebius Token Factory, hosting on Render, and one result against its baseline.
