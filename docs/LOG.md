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
- **Token Factory spend:** about 0.65 M tokens this run (about 0.55 M on Ultra, mostly reasoning), across five Titanic cleans and three benchmark runs. At Token Factory's listed per-token rates that's well under the $5 cap. This is an estimate from `llm_calls`: please confirm against the Token Factory balance.
- **What needs you:**
  - Confirm the Token Factory balance.
  - The two judgement calls on cleaning quality before the demo:
    - Should "missing values" in text columns stay missing rather than become `'Unknown'`? The detector's proposal currently suggests "keep as Unknown".
    - Should the critic's concerns lower confidence less, so fills like "Median by title" commit outright?
  - Review the `docs/` additions (TRD §4.3, §4.4, §7.1–§7.2, §7.9, §14; App Flow §3–§5).
- **Decision for tomorrow:**
  - D4.1–D4.3 backend (widgets, the dashboard builder, agent v1).
  - Then D4.4–D4.8 frontend, starting with the Bklit and react-grid-layout checks (plan §2.0).
