# Sherlock · Backend Schema

Version 1.3 · 2026-10-25 · Every table, column, file and index. SQLite holds app state; Parquet holds data (queried through in-memory DuckDB); the filesystem holds artifacts.

---

## 1. Conventions

- IDs are strings: a 2–4 letter prefix and a ULID (`ds_01J…`, `stp_`, `wdg_`, `crd_`, `fs_`, `run_`, `job_`, `msg_`, `prp_`, `sel_`, `usr_`, `iss_`, `exp_`, `pln_`). ULIDs sort by creation time.
- Timestamps are ISO-8601 UTC strings (`TEXT`).
- JSON columns are `TEXT` containing JSON, validated by pydantic models on write; the shape is named in the column comment and defined in the [TRD §6](04-TRD.md).
- Soft deletes use `deleted_at`; a purge job removes rows and files 10 minutes after soft delete (datasets, widgets, cards) or at TTL expiry.
- SQLite settings: `PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000; PRAGMA synchronous=NORMAL`.
- Migrations: numbered SQL files in `api/sherlock/db/migrations/`, applied at startup, tracked in `schema_migrations`.
  - `001_initial.sql` creates every table and index in §2.1–§2.19, `002_clean_plans.sql` adds `clean_plans` (§2.21) and its index, `003_plan_scope.sql` adds `clean_plans.scope_json`, `004_llm_calls_indexes.sql` adds `llm_calls.cached` and three `llm_calls` indexes (§2.18), `005_web_cache.sql` adds `web_cache` (§2.22) and `llm_calls.results`, `007_llm_fallback.sql` adds `llm_calls.fallback_from` (§2.18), and `008_column_notes.sql` adds `column_notes` (§2.23). From 004 on, each slice of work that changes the schema has its own numbered file, so files written in parallel land in any order: `migrate()` applies every file it hasn't applied, by number. The column comments here can be longer than the SQL files'; the test compares tables and columns, not comments. `schema_migrations` itself is created by `sherlock/db/migrate.py` before any migration runs.
  - Each migration runs in one transaction.
  - A test (`api/tests/test_db.py`) parses this document and fails if a table or a column, in order, differs from the migrated database. So any change to §2 needs a new migration in the same commit.
- ID prefixes are 2–4 letters (`ds_` is two). ULIDs are 26 Crockford base32 characters, generated in `sherlock/db/util.py`. Request IDs (`req_…`) use the same format but are never stored.
- As built: `ver_` is never generated, since a version is keyed by `(dataset_id, version)` (§2.3). Issues use `iss_` and exports `exp_`. Cleaning plans use `pln_` and their items `pit_` (inside `items_json`, §2.21). Canvas nodes and edges the AI adds get `nd_` and `ed_` IDs inside `canvas_json` (`canvas/service.py`).

---

## 2. SQLite tables

### 2.1 users

```sql
CREATE TABLE users (
  id              TEXT PRIMARY KEY,            -- usr_…
  cookie_token    TEXT NOT NULL UNIQUE,        -- random 256-bit, stored hashed (sha256)
  settings_json   TEXT NOT NULL DEFAULT '{}',  -- Settings
  storage_bytes   INTEGER NOT NULL DEFAULT 0,  -- sum of dataset folder sizes
  tokens_used_today INTEGER NOT NULL DEFAULT 0,
  tokens_day      TEXT,                        -- YYYY-MM-DD the counter applies to
  created_at      TEXT NOT NULL,
  last_seen_at    TEXT NOT NULL
);
```

A user with no datasets who hasn't been seen for 24 h is deleted by the purge (§6). `last_seen_at` is refreshed at most once a minute.

### 2.2 datasets

```sql
CREATE TABLE datasets (
  id               TEXT PRIMARY KEY,           -- ds_…
  user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name             TEXT NOT NULL,              -- display name, editable
  original_filename TEXT NOT NULL,
  is_sample        INTEGER NOT NULL DEFAULT 0,
  status           TEXT NOT NULL,              -- profiling|offer|cleaning|building|ready|failed
  error            TEXT,
  current_version  INTEGER NOT NULL DEFAULT 0, -- 0 until v1 exists
  row_count        INTEGER,
  column_count     INTEGER,
  import_options_json TEXT NOT NULL,           -- {delimiter, encoding, header_row, skip_rows}
                                               -- plus, for ragged files only, width and header_fields (TRD §7.1)
  last_tab         TEXT,                       -- csv|dashboard|flow
  last_opened_at   TEXT,
  expires_at       TEXT NOT NULL,              -- created_at + DATASET_TTL_DAYS
  folder_bytes     INTEGER NOT NULL DEFAULT 0,
  next_row_id      INTEGER NOT NULL DEFAULT 1,  -- next _row_id to assign; never decreases, so ids are never reused
  state_rev        INTEGER NOT NULL DEFAULT 0,  -- bumped on any widget, card, run, layout or canvas write (export cache key)
  created_at       TEXT NOT NULL,
  deleted_at       TEXT
);
CREATE INDEX datasets_user ON datasets(user_id, deleted_at, last_opened_at DESC);
CREATE INDEX datasets_expiry ON datasets(expires_at);
```

### 2.3 versions

```sql
CREATE TABLE versions (
  dataset_id   TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  version      INTEGER NOT NULL,               -- 1 = raw import
  parquet_path TEXT NOT NULL,                  -- relative to the dataset folder; an undo version points at an earlier version's file (TRD §7.8)
  row_count    INTEGER NOT NULL,
  column_count INTEGER NOT NULL,
  columns_json TEXT NOT NULL,                  -- [{name, type}] in order, after the step
  step_id      TEXT,                           -- the step that produced it (NULL for v1)
  effective_step_ids_json TEXT NOT NULL DEFAULT '[]', -- ordered ids of the steps whose effects make up this version (undone steps removed)
  created_at   TEXT NOT NULL,
  PRIMARY KEY (dataset_id, version)
);
```

### 2.4 datacards

```sql
CREATE TABLE datacards (
  dataset_id TEXT NOT NULL,
  version    INTEGER NOT NULL,
  card_json  TEXT NOT NULL,                    -- DataCard
  created_at TEXT NOT NULL,
  PRIMARY KEY (dataset_id, version),
  FOREIGN KEY (dataset_id, version) REFERENCES versions(dataset_id, version) ON DELETE CASCADE
);
```

### 2.5 steps

```sql
CREATE TABLE steps (
  id             TEXT PRIMARY KEY,             -- stp_…
  dataset_id     TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  no             INTEGER NOT NULL,             -- 1..n per dataset, dense
  kind           TEXT NOT NULL,                -- clean|edit|undo|ml_column|computed_column
  from_version   INTEGER NOT NULL,
  to_version     INTEGER NOT NULL,
  summary        TEXT NOT NULL,
  column_targets_json TEXT NOT NULL,           -- ["age"]
  columns_added_json  TEXT NOT NULL DEFAULT '[]',
  columns_removed_json TEXT NOT NULL DEFAULT '[]',
  code           TEXT,                         -- pandas (clean/computed_column); the system typing step stores a DuckDB statement over the frame
  edits_json     TEXT,                         -- EditBatch (edit)
  notebook_code  TEXT NOT NULL,                -- Python (pandas, or DuckDB for the typing step) that reproduces this step in the exported notebook:
                                               --   clean/computed_column: code followed by `df = result`; edit: generated from edits_json at commit;
                                               --   undo: a comment only (the exporter emits the version's effective chain)
  helpers_used_json TEXT NOT NULL DEFAULT '[]',-- helper function names referenced by code (for vendoring into the notebook)
  impact_json    TEXT NOT NULL,                -- Step.impact
  confidence     REAL,
  gate           TEXT,                         -- commit|flag|skip|user
  flag_reason    TEXT,
  decisions_json TEXT NOT NULL DEFAULT '[]',
  verifiers_json TEXT NOT NULL DEFAULT '{}',
  replayed_step_ids_json TEXT,                 -- for undo with replay
  undone_step_id TEXT,                         -- for kind=undo: which step was undone
  created_by     TEXT NOT NULL,                -- system|cleaner|user|chat (system = the automatic typing step)
  job_id         TEXT,
  created_at     TEXT NOT NULL,
  UNIQUE (dataset_id, no)
);
CREATE INDEX steps_dataset ON steps(dataset_id, no DESC);
```

A cleaning step from a scoped clean (some rows, or hand-edited cells kept) ends its `notebook_code` with `result = keep_outside_scope(df, result, rows=[…], cells=[…])` before `df = result`, so the notebook and a replay apply the same scope (TRD §7.7–§7.8). An undo step's `replayed_step_ids_json` lists the steps it replayed.

### 2.6 lineage

One row per changed cell per step per version that application of the step produced (a replay adds rows). For Titanic-scale data this is small; for 500k-row files it can be large, so it is append-only and indexed by `(dataset_id, row_id, column)`.

```sql
CREATE TABLE lineage (
  dataset_id TEXT NOT NULL,
  step_id    TEXT NOT NULL REFERENCES steps(id) ON DELETE CASCADE,
  row_id     INTEGER NOT NULL,
  column     TEXT NOT NULL,
  old_value  TEXT,                              -- values stored as text (typed in the version)
  new_value  TEXT,
  flag       TEXT,                              -- NULL|flagged|quarantined|predicted|invalid (predicted only for P1 ml_column steps; P0 predictions live in run results)
  version    INTEGER NOT NULL,                  -- the version this application of the step produced (a replay writes new rows)
  PRIMARY KEY (dataset_id, step_id, version, row_id, column)
) WITHOUT ROWID;
CREATE INDEX lineage_cell ON lineage(dataset_id, row_id, column);
```

Row-level events (added, deleted, quarantined, restored) are stored with `column = '_row'` and `new_value` ∈ `added|deleted|quarantined|restored`.

Flags as written (TRD §7.9): `quarantined` on a cell that lost its value in a row the same step quarantined (the original text stays in `old_value`); `flagged` on every changed cell of a step with gate `flag`; `invalid` on an edited cell whose value didn't parse as the column's type (the cell is NULL in the version and `new_value` keeps the typed text).

### 2.7 user_edited_cells

Tracks cells the user edited by hand so "Clean with AI" can skip them. Written by `commit_step` for edit batches; rows whose step is undone are deleted.

When an undo deletes a cell's row, the cell stays protected if an edit batch still in the new version's effective chain also edited it. Its row then points at the latest such batch, found from that batch's lineage. Example: edit `age` → 5, edit `age` → 6, undo the second. The cell shows 5 and stays protected, now under the first batch.

```sql
CREATE TABLE user_edited_cells (
  dataset_id TEXT NOT NULL,
  row_id     INTEGER NOT NULL,
  column     TEXT NOT NULL,
  step_id    TEXT NOT NULL,
  PRIMARY KEY (dataset_id, row_id, column)
) WITHOUT ROWID;
```

### 2.8 issues

Detected issues per version (the DataCard's `issues`, normalized for querying and for tracking what the cleaner handled).

```sql
CREATE TABLE issues (
  id         TEXT PRIMARY KEY,                 -- iss_…
  dataset_id TEXT NOT NULL,
  version    INTEGER NOT NULL,
  detector   TEXT NOT NULL,
  column     TEXT,
  count      INTEGER NOT NULL,
  severity   REAL NOT NULL,
  details_json TEXT NOT NULL,                  -- examples, proposal
  handled_by_step_id TEXT,
  outcome    TEXT,                             -- fixed|flagged|skipped|NULL
  skip_reason TEXT
);
CREATE INDEX issues_dataset ON issues(dataset_id, version, severity DESC);
```

### 2.9 widgets and layouts

```sql
CREATE TABLE widgets (
  id            TEXT PRIMARY KEY,              -- wdg_…
  dataset_id    TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  title         TEXT NOT NULL,
  spec_json     TEXT NOT NULL,                 -- WidgetSpec
  spec_hash     TEXT NOT NULL,                 -- sha1 of spec_json (cache key part)
  prev_spec_json TEXT,                         -- spec before the last PATCH, for POST /widgets/{wid}/undo
  status        TEXT NOT NULL,                 -- ready|outdated|error|building
  error         TEXT,
  run_id        TEXT,                          -- for op.type = ml
  version_built INTEGER NOT NULL,
  score         REAL,                          -- interestingness at build time
  point_json    TEXT,                          -- highlight: {kind, key}
  created_by    TEXT NOT NULL,                 -- builder|user|chat
  order_no      INTEGER NOT NULL,              -- builder order (for card ordering fallback)
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  deleted_at    TEXT
);
CREATE INDEX widgets_dataset ON widgets(dataset_id, deleted_at);

CREATE TABLE layouts (
  dataset_id  TEXT PRIMARY KEY REFERENCES datasets(id) ON DELETE CASCADE,
  layout_json TEXT NOT NULL,                   -- Layout {lg, md, sm}
  updated_at  TEXT NOT NULL
);

CREATE TABLE widget_cache (
  dataset_id  TEXT NOT NULL,
  cache_key   TEXT NOT NULL,                   -- sha1(spec_hash, version, filter_hash)
  data_json   TEXT NOT NULL,                   -- WidgetData
  created_at  TEXT NOT NULL,
  PRIMARY KEY (dataset_id, cache_key)
);
```

As built (`sherlock/widgets/spec.py`, `execute.py`): `spec_hash` is the sha1 of the spec's canonical JSON (sorted keys, no spaces), not of the `spec_json` text as stored. `widget_cache.cache_key` is the sha1 of `<spec_hash>:<version>:<filter_hash>`, where `filter_hash` is the sha1 of the compiled row filter. An in-memory LRU of 500 entries sits in front of the table (TRD §9), and the purge deletes rows older than 24 h (§6).

### 2.10 fact_sheets and relations

```sql
CREATE TABLE fact_sheets (
  id            TEXT PRIMARY KEY,              -- fs_…
  dataset_id    TEXT NOT NULL,
  widget_id     TEXT,                          -- NULL for overview / synthesis sheets
  run_id        TEXT,
  version       INTEGER NOT NULL,
  facts_json    TEXT NOT NULL,                 -- FactSheet.facts
  depends_columns_json TEXT NOT NULL,          -- ["sex","survived"]
  material_hash TEXT NOT NULL,
  created_at    TEXT NOT NULL
);
CREATE INDEX fact_sheets_widget ON fact_sheets(widget_id, version);

CREATE TABLE relations (
  dataset_id TEXT NOT NULL,
  version    INTEGER NOT NULL,
  a_widget   TEXT NOT NULL,
  b_widget   TEXT NOT NULL,
  kind       TEXT NOT NULL,                    -- shared_column|same_target|correlated|dependency
  weight     REAL NOT NULL,
  detail_json TEXT,
  PRIMARY KEY (dataset_id, version, a_widget, b_widget, kind)
);
```

As built: each fact in `facts_json` is `{value, format, label, formatted}` plus `sql`+`cell`, `sql`+`scalar`, or `from`+`formula` (TRD §6.4). `material_hash` is stored as an empty string (cut 6). The overview's sheet has `widget_id` NULL and keys prefixed `w<i>.`. Relations are rewritten for the current version on every stories run; `detail_json` is `{columns}` for shared columns or `{column}` for the target.

### 2.11 cards

```sql
CREATE TABLE cards (
  id              TEXT PRIMARY KEY,            -- crd_…
  dataset_id      TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  kind            TEXT NOT NULL,               -- overview|widget|synthesis|direction|answer (Flow notes live in canvas_json)
  widget_id       TEXT,
  source_card_ids_json TEXT,                   -- synthesis sources
  headline_json   TEXT NOT NULL,               -- CardBody with one paragraph block (chip, label and text runs)
  body_json       TEXT NOT NULL,               -- CardBody
  fact_sheet_id   TEXT,
  status          TEXT NOT NULL,               -- ready|updating|outdated|sources_changed|building|failed
  job_id          TEXT,                        -- direction cards: the job building them
  edited_by_user  INTEGER NOT NULL DEFAULT 0,
  changed_badge   INTEGER NOT NULL DEFAULT 0,
  suggestion_json TEXT,                        -- {headline, body}
  version         INTEGER NOT NULL,            -- data version the text reflects
  narrated_by     TEXT,                        -- model id
  verified_at     TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  deleted_at      TEXT
);
CREATE INDEX cards_dataset ON cards(dataset_id, deleted_at, kind);
CREATE INDEX cards_widget ON cards(widget_id);
```

As built: `narrated_by` is the model ID, or NULL when the card shows the fact-sheet bullets. Chip runs typed by hand have `key: null` and `unverified: true`. `suggestion_json` holds `{headline, body}` for an edited card after a cascade.

### 2.12 canvases

```sql
CREATE TABLE canvases (
  dataset_id  TEXT PRIMARY KEY REFERENCES datasets(id) ON DELETE CASCADE,
  canvas_json TEXT NOT NULL,                   -- JSON Canvas document
  etag        TEXT NOT NULL,                   -- sha1 of canvas_json
  updated_at  TEXT NOT NULL
);
```

Card nodes reference `cards.id`. Nodes of soft-deleted cards stay (hidden) so Undo restores them in place; nodes of hard-deleted cards are pruned on the next canvas read, which bumps the etag.

As built: `canvas_json` is stored with sorted keys and no spaces, and `etag` is the sha1 of that text. A dataset has no row until its first save; until then `GET /canvas` answers the empty document and its etag. Every save that changes the document bumps `datasets.state_rev`. Synthesis cards (`kind = 'synthesis'`) have `source_card_ids_json` and no `fact_sheet_id`; their chips' keys are `<card_id>.<fact key>`. Answer cards added to Flow (`kind = 'answer'`) have a fact sheet with no `widget_id`.

### 2.13 runs

```sql
CREATE TABLE runs (
  id            TEXT PRIMARY KEY,              -- run_…
  dataset_id    TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  widget_id     TEXT,
  version       INTEGER NOT NULL,
  recipe        TEXT NOT NULL,
  method        TEXT NOT NULL,
  scope_json    TEXT NOT NULL,                 -- Scope
  params_json   TEXT NOT NULL,
  cache_key     TEXT NOT NULL,                 -- sha1(version, scope, recipe, method, params)
  status        TEXT NOT NULL,                 -- queued|running|done|failed|cancelled|outdated
  job_id        TEXT,
  model_card_json TEXT,                        -- ModelCard
  fact_sheet_id TEXT,
  features_json TEXT,                          -- columns used (for invalidation)
  target        TEXT,
  artifact_dir  TEXT,                          -- runs/run_…/
  repro_path    TEXT,                          -- runs/run_…/repro.py, written at completion (TRD §6.7)
  sample_json   TEXT,                          -- {seed, stratify_column, n} when the scope was sampled to 50k rows
  libraries_json TEXT,                         -- {"scikit-learn": "1.5.2", ...} versions used, pinned into the notebook
  error         TEXT,
  created_by    TEXT NOT NULL,                 -- builder|user|chat
  created_at    TEXT NOT NULL,
  finished_at   TEXT,
  UNIQUE (dataset_id, cache_key)
);
CREATE INDEX runs_dataset ON runs(dataset_id, status);
```

As built (`sherlock/ml/runner.py`):
- **On request.** A run row is written with `status = queued`, `scope_json` (target filled in, any dashboard filter folded into the predicate, `inherit_global_filters: false`), `params_json` (manifest defaults filled in), `target` and `cache_key`. `job_id` is the `ml_run` job's.
- **Identity.** The `UNIQUE (dataset_id, cache_key)` makes a repeat request return the same row. A failed or cancelled run's row is reset to `queued` and reused.
- **On completion.** The job sets `status = done`, `model_card_json`, `fact_sheet_id`, `features_json` (the features used), `artifact_dir` (`runs/<id>/`), `repro_path`, `sample_json`, `libraries_json` and `finished_at`.
- **Outdated.** The cascade, or the run itself when it finishes on an earlier version, sets `status = outdated`.
- **`widget_id`.** The last widget that asked for the run. `widgets.run_id` is the link a widget shows, and a cached run can back more than one widget.
- **`created_by`.** `builder` for the dashboard's driver widget, `chat` for a run that the chat's `ask_why` starts (`agent/insight.py`), otherwise `user` (a run from `POST /datasets/{id}/runs`, an analysis widget the user adds or changes, and every Re-run, automatic ones included).
- **`fact_sheets.run_id`** is set on the run's own sheet. An analysis widget's sheet is a copy with its `widget_id`.
- **`widgets.spec_json`.** An analysis that replaced a chart keeps the chart's title in `view.options.chart_title`, for Undo.
- **`selections` for "who did it get wrong?"** (`POST /runs/{rid}/wrong-rows`): `row_ids_json` holds the misclassified `_row_id`s, `predicate` is NULL, `label` is "<target>: predicted wrong", and `version` is the current version. Row IDs are stable across versions.

### 2.14 jobs and job_events

```sql
CREATE TABLE jobs (
  id         TEXT PRIMARY KEY,                 -- job_…
  dataset_id TEXT REFERENCES datasets(id) ON DELETE CASCADE,
  user_id    TEXT NOT NULL,
  kind       TEXT NOT NULL,                    -- profile|clean|build_dashboard|stories|ml_run|cascade|undo|export_notebook|purge
  status     TEXT NOT NULL,                    -- queued|running|done|failed|cancelled
  params_json TEXT NOT NULL DEFAULT '{}',
  state_json TEXT,                             -- checkpoint; a clean job keeps its run state here (TRD §7.2: from_version, ended_by, waited_for_model_s, attempted, skipped, hand_edited_skipped)
  progress_json TEXT,                          -- {step, of, label, pct}
  result_json TEXT,
  error      TEXT,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  owner_pid  TEXT,                             -- process that is running it
  heartbeat_at TEXT,                           -- refreshed every 10 s while running; a running job stale for 60 s is re-queued at startup
  tokens_used INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX jobs_queue ON jobs(status, created_at);
CREATE INDEX jobs_dataset ON jobs(dataset_id, created_at DESC);

CREATE TABLE job_events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT, -- the SSE event id
  dataset_id TEXT NOT NULL,
  job_id     TEXT,
  type       TEXT NOT NULL,                     -- SSE event type
  data_json  TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX job_events_dataset ON job_events(dataset_id, id);
```

Retention: `job_events` older than 24 h are deleted by the purge job.

Implementation notes:
- `job_events` holds every SSE event of a dataset (TRD §5), not only job events. An event that doesn't come from a job, such as `version.created` for a step committed through the API, has `job_id` NULL. So every event has an `id` and can be replayed.
- `data_json` always carries `dataset_id`, which the user-level stream needs.
- `jobs.owner_pid` is `<hostname>:<pid>:<ulid>`, unique per process start. At startup, every `running` job is re-queued (one process holds the runner). While running, a sweep every 30 s re-queues any `running` job of another owner whose `heartbeat_at` is older than 60 s.
- `jobs.progress_json` is NULL until the job reports; the API then shows `{step: 0, of: 0, label: "", pct: 0}`.
- As built: no `undo` job is ever queued, since an undo, its replay included, runs inside its request (TRD §7.8); `jobs/runner.py` still lists the kind. A `purge` job has `user_id = 'system'` and `dataset_id` NULL (§6).
- `params_json` of a `clean` job started from a cleaning plan (PRD CLEAN-8a) carries `plan: {id, version, items}`, a frozen copy of the plan's items when Start was pressed (§2.21), so later edits to a plan can't change a running job. A `build_dashboard` job queued by the After upload setting ("I'll clean it myself") rather than a click has `automatic: true`; no `clean` job is queued without a click, since "Open the cleaning plan" only makes a draft (§2.21) (the `Job` response shows it, TRD §4.10).

### 2.15 chat

```sql
CREATE TABLE messages (
  id            TEXT PRIMARY KEY,              -- msg_…
  dataset_id    TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  role          TEXT NOT NULL,                 -- user|assistant|system
  text          TEXT NOT NULL,
  blocks_json   TEXT NOT NULL DEFAULT '[]',    -- AnswerBlock[]
  sources_json  TEXT NOT NULL DEFAULT '[]',
  context_json  TEXT,                          -- ChatContext at send time
  focus_json    TEXT,                          -- saved focus (assistant)
  plan_json     TEXT,
  clarification_json TEXT,
  clarification_of TEXT,                       -- message id this answers
  proposal_id   TEXT,
  route_json    TEXT,                          -- the router output (debug/eval)
  tokens_used   INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL,
  version       INTEGER                        -- the dataset version the message read (migration 006)
);
CREATE INDEX messages_dataset ON messages(dataset_id, created_at);

CREATE TABLE thread_summaries (
  dataset_id  TEXT PRIMARY KEY,
  summary     TEXT NOT NULL,
  up_to_message_id TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE proposals (
  id          TEXT PRIMARY KEY,                -- prp_…
  dataset_id  TEXT NOT NULL,
  message_id  TEXT,
  kind        TEXT NOT NULL,                   -- clean_step|clean_selection|edit_cells|card_edit|computed_column
  base_version INTEGER NOT NULL,               -- version the proposal was computed on; it expires when that is no longer current
  payload_json TEXT NOT NULL,                  -- code / edits / new text, plus impact preview
  status      TEXT NOT NULL,                   -- pending|approved|rejected|expired
  result_step_id TEXT,
  created_at  TEXT NOT NULL,
  resolved_at TEXT
);
```

As built: `messages.plan_json` holds `{ steps: [{ text, status }] }` with the final statuses, and `proposal_id` the proposal the message made. `proposals.payload_json` is `{ summary, edits: [{ row_id, column, value, before }], impact, warnings? }` for `edit_cells` (`warnings`: code's sentences for new numbers outside their column's range, TRD §4.4) and `{ summary, scope: { kind, selection_id }, impact }` for `clean_selection` (approving it opens the cleaning plan with that scope, §2.21); `result_step_id` is the edit step an approved `edit_cells` committed. `thread_summaries` is written by the running summary (TRD §8.1).
- `messages.version` (migration `006_message_version.sql`, plan 2b.4) is `datasets.current_version` when the message was written: the version an answer's queries ran on. The migration fills it for older messages with the newest version created at or before the message (versions only go up; an undo is a new version). The thread's history lines, Add to Flow and the `Message` response read it (TRD §8.1, §4.9).
- Only `edit_cells` and `clean_selection` proposals are written. `card_edit` is not built (cut 2, Implementation Plan §2.0), and `clean_step` and `computed_column` are P1; approving another kind answers `422` (`agent/actions.py`). An approved `edit_cells` commits its step with `created_by = 'user'`, through the same save as the grid (`rows/edits.py`).

### 2.16 selections

```sql
CREATE TABLE selections (
  id          TEXT PRIMARY KEY,                -- sel_…
  dataset_id  TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  version     INTEGER NOT NULL,
  predicate   TEXT,                            -- SQL WHERE fragment (validated)
  row_ids_json TEXT,                           -- explicit ids (lasso, "wrong predictions")
  row_count   INTEGER NOT NULL,
  label       TEXT,
  created_at  TEXT NOT NULL
);
```

Selections referencing a version older than current are re-evaluated (predicates) or re-validated (ids still present) on use.
- As built (plan 2b.4): `widgets.service.selection_rows` counts a selection's usable rows (its predicate or its IDs, quarantined rows left out) on the current version whenever chat's context, a `clean_selection` proposal or a cleaning plan's scope reads it; `row_count` stays the count when it was made.

### 2.17 value_index

```sql
CREATE TABLE value_index (
  dataset_id TEXT NOT NULL,
  column     TEXT NOT NULL,
  value      TEXT NOT NULL,
  count      INTEGER NOT NULL,
  embedding  BLOB,                             -- float32[] or NULL (sqlite-vec virtual table used when available)
  version    INTEGER NOT NULL,
  PRIMARY KEY (dataset_id, column, value)
) WITHOUT ROWID;
```

When `sqlite-vec` is installed, a `vec_values` virtual table mirrors `embedding` for ANN search; otherwise similarity is computed in numpy over the column's rows (≤ 5,000).

As built (`sherlock/profile/service.py`): the profile rewrites a dataset's whole index each time it profiles the current version, since the primary key has no version. It indexes the columns whose role is `dimension` or `target_like`, at most the 10,000 most common values each, as text with their counts. `embedding` is always NULL and there is no `vec_values` table: not built while `MODEL_EMBED` is empty (TRD §3.5), so the chat resolves values exactly, then with rapidfuzz (TRD §8.1).

### 2.18 llm_calls and sandbox_runs

```sql
CREATE TABLE llm_calls (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     TEXT, dataset_id TEXT, job_id TEXT, message_id TEXT,
  role        TEXT NOT NULL,                   -- large|medium|small|embed|web (a Tavily call, TRD §3.6)
  model       TEXT NOT NULL,                   -- a Nemotron ID, or tavily-search|tavily-extract|tavily-map
  purpose     TEXT NOT NULL,                   -- diagnose|propose|critic|curate|narrate|route|sql|compose|…
  prompt_tokens INTEGER, completion_tokens INTEGER,  -- NULL on web rows
  latency_ms  INTEGER,
  ok          INTEGER NOT NULL,
  error       TEXT,
  repaired    INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  cached      INTEGER NOT NULL DEFAULT 0,      -- 1: answered from a cache, no request sent (004)
  results     INTEGER,                         -- web rows: the results (search) or pages (extract, map) returned (005)
  fallback_from TEXT                           -- the role this call stood in for (medium, when Ultra answered in Super's place), else NULL (007)
);
CREATE INDEX llm_calls_user_day ON llm_calls(user_id, created_at);
CREATE INDEX llm_calls_message ON llm_calls(message_id);   -- 004: a chat answer's receipt
CREATE INDEX llm_calls_job ON llm_calls(job_id);           -- 004: a job's receipt
CREATE INDEX llm_calls_created ON llm_calls(created_at);   -- 004: the app-wide daily budget's scan

CREATE TABLE sandbox_runs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  dataset_id  TEXT, job_id TEXT, step_id TEXT,
  code_hash   TEXT NOT NULL,
  rows_in     INTEGER, rows_out INTEGER,
  cpu_ms      INTEGER, wall_ms INTEGER,
  ok          INTEGER NOT NULL,
  error       TEXT,
  created_at  TEXT NOT NULL
);
```

As built: the purposes written are `route`, `plan`, `sql`, `predicate`, `widget`, `update_widget`, `compose`, `stats`, `meaning`, `edits`, `ask_story`, `plan_edits` and `summary` (chat); `diagnose`, `propose` and `critic` (the Cleaner); `curate` (the dashboard builder); `narrate`, `overview` and `synthesis` (stories); and for web retrieval `web_query`, `web_answer`, `meaning_web` and `dictionary` on Nemotron rows and `web_context`, `meaning_web` and `dictionary` on web rows (TRD §3.6, §8.2). No `embed` row is written while `MODEL_EMBED` is empty. A failed call is logged too, with `ok = 0` and its error. The app-wide daily token ceiling sums `llm_calls` from midnight UTC; a user's daily count is kept in `users.tokens_used_today` (TRD §3.5).

Receipts (TRD §4.9, §4.10; migration `004_llm_calls_indexes.sql`):
- `GET /chat/messages/{mid}/calls` reads the rows whose `message_id` is an assistant message's ID, and `GET /jobs/{jid}/calls` the rows whose `job_id` is the job's, oldest first (`ORDER BY id`), through `sherlock/llm/calls.py`. The indexes on `message_id` and `job_id` keep those reads off a full scan; the one on `created_at` serves the app-wide budget's sum since midnight UTC, which runs before every model call.
- **Web rows.** A Tavily call (TRD §3.6) is a row like a model call: `role = 'web'`, `model` the tool (`tavily-search`, `tavily-extract` or `tavily-map`), the purpose of the feature that made it, `latency_ms`, `ok` and `error`, no tokens (both NULL, so neither the token budgets nor the app-wide ceiling count it), `cached = 1` (with latency 0) when the 24 h web cache answered it without a request, and `results` (migration `005_web_cache.sql`), how many results or pages came back. The hourly web limit (`WEB_RATE_LIMIT`) counts a user's web rows with `cached = 0` in the last hour. A call that never went out (no key, `WEB_SEARCH=off`, the limit, no time left) writes no row.
- `cached` is 0 for every Nemotron call: the model client has no cache.
- **`fallback_from`** (migration `007_llm_fallback.sql`) names the role a call stood in for. The model client sends a Super (`medium`) call to Ultra (`large`) when Super's circuit breaker is open or its next retry would pass the call's deadline (TRD §3.5); that row has `role = 'large'`, Ultra's `model`, the original `purpose`, and `fallback_from = 'medium'`. Every other row has NULL. Receipts show it, and `sherlock llm stats` reports it as the fallback rate.
- The rows still aren't purged (BACKLOG): the budgets and the spend figures read them.

### 2.19 exports

```sql
CREATE TABLE exports (
  id          TEXT PRIMARY KEY,                -- exp_…
  dataset_id  TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,                   -- notebook (P1: report_html|report_pdf|canvas)
  version     INTEGER NOT NULL,
  options_json TEXT NOT NULL,                  -- NotebookOptions
  cache_key   TEXT NOT NULL,                   -- sha1(kind, version, datasets.state_rev, options_json)
  status      TEXT NOT NULL,                   -- queued|running|done|failed
  job_id      TEXT,
  path        TEXT,                            -- exports/notebook_<cache_key>.ipynb (relative to the dataset folder)
  bytes       INTEGER,
  counts_json TEXT,                            -- {steps, widgets, runs, cards}
  error       TEXT,
  created_at  TEXT NOT NULL,
  finished_at TEXT,
  UNIQUE (dataset_id, cache_key)
);
CREATE INDEX exports_dataset ON exports(dataset_id, created_at DESC);
```

A new version does not delete older exports (they are still valid for their version); the purge job removes export files older than 24 h and their rows.

As built: `version` is the version the notebook rebuilds (the current one, or the earlier one for `up_to_step`), set when the job finishes. The user's last options are kept in `users.settings_json.notebook`.

### 2.20 schema_migrations

```sql
CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
```

### 2.21 clean_plans

The cleaning plan (PRD CLEAN-8a, CLEAN-8b, TRD §4.4, §7.2): what Clean with AI will try, diagnosed by the code detectors on a version, editable until it starts. Added by migration `002_clean_plans.sql`; `scope_json` by `003_plan_scope.sql`.

```sql
CREATE TABLE clean_plans (
  id         TEXT PRIMARY KEY,                 -- pln_…
  dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  version    INTEGER NOT NULL,                 -- the version the items were diagnosed on
  items_json TEXT NOT NULL,                    -- [PlanItem] (TRD §4.4)
  status     TEXT NOT NULL,                    -- draft|started|discarded
  source     TEXT NOT NULL,                    -- user|after_upload (who opened it)
  job_id     TEXT,                             -- the clean job a started plan ran as
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  scope_json TEXT                              -- {kind: selection|new_rows, selection_id, row_ids, rows}; NULL = the whole dataset (003)
);
CREATE UNIQUE INDEX clean_plans_one_draft ON clean_plans(dataset_id) WHERE status = 'draft';
```

- A dataset has at most one `draft` (the partial unique index). `POST /datasets/{id}/clean/plan` returns it or makes it; Discard sets `discarded`, and so does Clean it myself (`POST /use-as-is`); Start sets `started` and `job_id`, and the job's `params_json` keeps a frozen copy of the items (§2.14). Started and discarded plans are kept as history.
- `version` moves when a draft is merged onto a newer version (`cleaning/plan.py` `merge`): ticks and instructions are kept by issue key, the user's steps while their column exists.
- `items_json` holds Sherlock's fixes and the user's own steps (PRD CLEAN-8b: `detector: "user_request"`, `key: null`, `source: "you"|"chat"`), and each fix's rewritten `instruction`. The clean job's `state_json` adds `plan_outcomes` (item ID → outcome), which the report's `your_steps` reads (TRD §7.2).
- `scope_json` is the rows a plan was opened for, so a reload can't widen it to the whole file: `new_rows` with the saved rows' IDs from the new-rows toast's "Clean them", or `selection` with the selection's ID from approving chat's `clean_selection` (PRD CLEAN-1). `rows` is the count the panel shows. `POST …/clean/plan` with a scope replaces it, a whole-dataset scope clears it, and no scope leaves it. The job's own scope still comes from `POST /clean`, which the panel sends from the scope the user leaves picked.
- `source` is `after_upload` when the profile job made the draft because After upload is "Open the cleaning plan"; the plan screen then says why it opened.
- Deleted with the dataset: the foreign key cascades on hard delete (§6).

### 2.22 web_cache

Tavily responses (TRD §3.6), so the same search, extract or map within 24 h makes no second call. Added by migration `005_web_cache.sql`.

```sql
CREATE TABLE web_cache (
  key           TEXT PRIMARY KEY,              -- sha1 of the kind and the request
  kind          TEXT NOT NULL,                 -- search|extract|map
  request_json  TEXT NOT NULL,                 -- the parameters sent (never a cell value, TRD §3.6)
  response_json TEXT NOT NULL,                 -- Tavily's reply, as received
  created_at    TEXT NOT NULL
);
CREATE INDEX web_cache_created ON web_cache(created_at);
```

- `key` is the SHA-1 of the kind and the request's parameters as sorted JSON. The parameters are fixed in code except the query (or URLs and instructions), the topic and the time range, so the same question asked twice is one key.
- It belongs to no user or dataset: a request holds only the user's words and column names, never data, and the response is public web content. A hit is still logged as an `llm_calls` row with `cached = 1` under the asking user (§2.18).
- A row older than 24 h is ignored when read and deleted by the purge (§6). A failed call isn't cached.
- `created_at` is when Tavily returned it, so a cached answer shows the date it was retrieved, not the date it was read.

### 2.23 column_notes

What a column means, from a data dictionary the user linked (`kind = 'dictionary'`, PRD LOAD-7, TRD §7.1.1) or read from the web when chat explains a column (`kind = 'web'`, TRD §8.2 `ask_meaning`). Added by migration `008_column_notes.sql`.

```sql
CREATE TABLE column_notes (
  dataset_id   TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  column       TEXT NOT NULL,
  kind         TEXT NOT NULL,                  -- dictionary|web
  description  TEXT NOT NULL,                  -- Super's sentence from the source, no digits
  excerpt      TEXT,                           -- the source's own words, verbatim
  source_url   TEXT NOT NULL,
  source_title TEXT,
  retrieved_at TEXT NOT NULL,                  -- when Tavily returned the page
  created_at   TEXT NOT NULL,
  PRIMARY KEY (dataset_id, column, kind)
);
```

- **Metadata, not data** (CLAUDE.md Rule 3): a note describes a column and never changes a value, so it isn't a step and has no version. A note is keyed by the column's name; after a rename the old name's note no longer matches a column and isn't shown.
- **`description`** is written by Super from the excerpt, one sentence with no digits or numbers in words (`ColumnNotes`, TRD §7.1). Codes and their numbers stay in **`excerpt`**, the chunk of the page Tavily returned, shown verbatim beside it (at most 600 characters).
- One note per column and kind: reading a dictionary again replaces the column's `dictionary` note, and a new web meaning replaces its `web` note. Readers show a column's `dictionary` note before its `web` note, and with a dictionary note chat doesn't search the web for the column.
- Deleted with the dataset: the foreign key cascades on hard delete (§6).

---

## 3. DuckDB (in-memory, cached per version)

There is no persistent DuckDB file. Versions are immutable Parquet files, and queries use a cached in-memory connection per (dataset, version), opened on first use:

```sql
-- on first use per (dataset, version); the connection is then cached in the single API process
CREATE TABLE t AS SELECT * FROM read_parquet('/data/users/<user_id>/datasets/<dataset_id>/versions/v7.parquet');  -- absolute path
SET enable_external_access = false;   -- then run the validated SELECT
```

Quarantine lives only in the `_quarantine_reason` column of each version. Predictions live only in `runs/<run_id>/results/predictions.parquet` (`run_id`, `_row_id`, `prediction`, `probability`, `interval_low`, `interval_high`, `low_confidence`, `ood`). Removed by cut 7: no predictions file is written; classification runs keep out-of-fold predictions in `results/oof.json` (§4).

Column conventions inside a version Parquet:
- `_row_id BIGINT NOT NULL` unique, assigned at import (1…n); new rows take `datasets.next_row_id`, so ids are never reused.
- `_quarantine_reason VARCHAR` nullable, created at import (all NULL); rows with a value are excluded from widgets, ML and stories by the compiled `{{rows}}` filter, which is visible in the shown SQL (the row-page API returns them with `quarantined: true`).
- User columns keep their original names; characters outside `[A-Za-z0-9_]` are allowed and always quoted in generated SQL.

Queries from widgets and answerers run on that in-memory connection after external access is turned off, with a 10 s interrupt.

As built (`sherlock/storage.py` `VersionConnections`): at most four connections stay open, the least recently used closed first, and opening a version closes the same dataset's older ones. Each connection has `memory_limit` = `DUCKDB_MEMORY_MB` and two threads, and serves one request at a time. A connection that is evicted while a request holds it closes when that request ends.

---

## 4. Filesystem layout

```
/data/
  sherlock.db                       SQLite
  users/<user_id>/
    datasets/<dataset_id>/
      raw.csv                       the upload, never modified
      .ingest.utf8.csv, .tmp/       transient during ingest (UTF-8 copy, DuckDB spill); deleted when it ends
      versions/
        v1.parquet … vN.parquet     immutable snapshots
      runs/<run_id>/
        model.joblib
        repro.py                    reproduction code (TRD §6.7)
        model_card.json             the ModelCard (as built)
        results/*.parquet           predictions, importance, pdp, coefficients
                                    (as built: results/importance.json and results/partial_dependence.json;
                                    JSON because pyarrow isn't a dependency; no predictions or coefficients, cuts 4 and 7;
                                    results/oof.json for classification: _row_id, actual, predicted, probability,
                                    the out-of-fold predictions behind the confusion matrix, ROC and "who did it get wrong?")
      exports/
        notebook_<cache_key>.ipynb  generated notebooks (ephemeral, 24 h)
        *.csv, *.py                 other generated exports (ephemeral)
  sample/                           the seeded sample artifacts, cloned per user on demand
```

`datasets.folder_bytes` is recomputed after every commit and run; `users.storage_bytes` is the sum. Uploads are refused when the user's total would exceed `USER_STORAGE_MB`.

As built:
- **More files.**
  - `/data/.boots` and `/data/.lockcheck.db` belong to the startup storage check (TRD §11).
  - `/data/.duckdb/<hex>/` is one DuckDB connection's spill folder (TRD §3.2). DuckDB creates it when a query passes the connection's memory cap and removes it when the connection closes; startup removes `/data/.duckdb/` whole.
  - `/data/.clean/<job_id>/` is a clean job's working folder (sample, candidate and commit Parquet files). It is removed when the run reaches its report (`cleaning/loop.py`); a run that is stopped or fails before that leaves it, and the purge doesn't clear it yet.
  - Each dataset folder has `.lock`, the commit lock (§7).
  - A replay works in `versions/.replay_<hex>/` and removes it when it ends (`steps/replay.py`).
- **The sample.** Nothing is written under `/data/sample/`. The seed ships in the image as `api/samples/seed/titanic3/` (`rows.json`, the dataset's rows in every table, and `files/`, its folder without `.lock` or `exports/`), or comes from `SAMPLE_SEED_DIR`. `POST /datasets/sample` clones it into a new dataset folder (TRD §9).
- **Exports.** Only notebooks are written to `exports/`. The CSV export (`GET /datasets/{id}/export.csv`) streams from the version and writes no file, and `repro.py` is downloaded from `runs/<run_id>/`.
- **Sizes.** `folder_bytes` and `storage_bytes` are updated at import, at a sample clone, and at every commit and undo. A finished run's artifacts and exported notebooks are counted at the next purge pass, which measures every folder again (§6). The storage limit is checked only at upload.

---

## 5. Derived and cached state summary

| State | Source of truth | Cached in |
|---|---|---|
| Current data | `versions/vN.parquet` | in-memory DuckDB table `t`, cached per version |
| Data card | computed from a version | `datacards` |
| Widget data | computed from spec + version + filters | `widget_cache` + memory |
| Story text | narrated from a fact sheet | `cards` |
| Fact values | computed from a version | `fact_sheets` |
| Run results | computed | `runs` + `runs/<id>/` |
| Canvas | user document | `canvases` |
| Notebook export | derived from steps, widgets, runs, cards at a version and `state_rev` | `exports` + `exports/*.ipynb` (24 h) |
| Pending edits | client only | browser local storage (`sherlock:edits:<dataset>:<version>`) |
| Cleaning plan (draft) | `clean_plans` | none; a draft on an older version is merged onto the current one when read |
| Web search, extract and map results | Tavily | `web_cache` (24 h, §2.22) |
| Column notes (a data dictionary, the web) | the linked page or the web search, read by Tavily | `column_notes` (kept with the dataset, §2.23) |
| UI state (tab, scroll, panel widths) | client | browser local storage; `datasets.last_tab` server-side |

---

## 6. Retention and purge

A `purge` job runs every 10 minutes:
1. Hard-delete datasets, widgets and cards with `deleted_at` older than 10 minutes (files included). Then each dataset that lost cards has its synthesis cards checked again (`synthesis.check_sources`): one citing a card that's gone becomes `sources_changed`.
2. Delete datasets past `expires_at` (soft-delete first, hard-delete on the next pass).
3. Delete `job_events` older than 24 h, `widget_cache` rows older than 24 h, `web_cache` rows older than 24 h (§2.22), and `exports` rows and files older than 24 h.
4. Delete sandbox temp directories (`/tmp/sherlock-sandbox/`, outside `/data`) older than 1 h.
5. Recompute `users.storage_bytes`.
6. Delete Cleaner work folders (`/data/.clean/<job_id>/`) older than 1 h whose job isn't queued or running. A stopped or crashed clean leaves its folder behind.
7. Delete empty workspaces: users with no dataset at all (soft-deleted ones count) not seen for 24 h. A browser that drops its cookie, or a script that calls the API without one, makes a new user on every request; this keeps them from piling up. Their `llm_calls` rows stay (no foreign key), so the budgets still see them.

As built (`sherlock/jobs/purge.py`):
- Hard-deleting a dataset removes its folder and its rows. The tables with a cascading foreign key go with it (`clean_plans` among them); `lineage`, `user_edited_cells`, `issues`, `widget_cache`, `fact_sheets`, `relations`, `job_events`, `thread_summaries`, `proposals` and `value_index` are cleared explicitly. `llm_calls` and `sandbox_runs` are kept: the daily budgets and the spend figures read them.
- A purged widget takes its card and fact sheets with it, and a run that pointed at it is unlinked. Canvas nodes of purged cards are pruned on the next canvas read (§2.12).
- An export's file is deleted with its row.
- The job reports six progress steps, in this order: deleted CSVs, expiry, events, caches and exports, temp folders (sandbox and `.clean`), empty workspaces, and the storage recount last. Its result counts `clean_dirs`, `users` and `web_cache` beside the others.
- Only `datasets` references `users` with a foreign key (`ON DELETE CASCADE`), so deleting a user with no datasets removes that row alone.
- `storage_bytes` counts every dataset still on disk, soft-deleted ones included, since their files remain until they are purged. Each dataset's `folder_bytes` is measured again first.
- **Schedule.** The job runner's sweep (every 30 s) queues a purge at its first pass after a start, then once every `PURGE_INTERVAL_S` (default 600; `0` turns it off), and never while one is queued or running. No purge is queued when `JOB_WORKERS` is 0. Its `jobs` row has `user_id = 'system'` and no dataset (`jobs/runner.py`).
- **Ages.** Soft deletes and expiry compare against `deleted_at` and `expires_at`; `job_events`, `widget_cache`, `web_cache` and `exports` against `created_at`; sandbox folders against their modification time, under `SANDBOX_TMP` (or `<system temp>/sherlock-sandbox` when it's empty).

---

## 7. Integrity rules enforced in code

- A step's `to_version` equals `from_version + 1` and the dataset's `current_version` after commit; commits are serialized per dataset with a file lock (`<dataset>/.lock`). Every commit passes `base_version` and is rejected (409) when it differs from `current_version`.
- Every lineage row belongs to one step and the version that application of the step produced; replays write fresh rows under the original step ids for the new version.
- A card's `fact_sheet_id` always points at a sheet for the card's `version` (or an older one while `status = outdated`).
- A run with `status = done` has `model_card_json` and an artifact dir; `outdated` keeps them for display.
- `widgets.run_id` is set only for `op.type = ml` widgets and points at a run on the same dataset.
- Canvas card nodes reference existing cards; nodes of hard-deleted cards are pruned on read.
- Every step has non-empty `notebook_code`, and a clean or computed_column step's ends with `df = result`; a commit without it is rejected. Every version has `effective_step_ids_json`. Every run with `status = done` has `repro_path`. This is what guarantees the notebook export can always be produced.
