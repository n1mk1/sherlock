# Sherlock · Backend Schema

Version 1.1 · 2026-10-24 (migration 001 and the doc-sync test, §1) · Every table, column, file and index. SQLite holds app state; Parquet holds data (queried through in-memory DuckDB); the filesystem holds artifacts.

---

## 1. Conventions

- IDs are strings: a 3–4 letter prefix and a ULID (`ds_01J…`, `ver_`, `stp_`, `wdg_`, `crd_`, `fs_`, `run_`, `job_`, `msg_`, `prp_`, `sel_`, `usr_`). ULIDs sort by creation time.
- Timestamps are ISO-8601 UTC strings (`TEXT`).
- JSON columns are `TEXT` containing JSON, validated by pydantic models on write; the shape is named in the column comment and defined in the [TRD §6](04-TRD.md).
- Soft deletes use `deleted_at`; a purge job removes rows and files 10 minutes after soft delete (datasets, widgets, cards) or at TTL expiry.
- SQLite settings: `PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000; PRAGMA synchronous=NORMAL`.
- Migrations: numbered SQL files in `api/sherlock/db/migrations/`, applied at startup, tracked in `schema_migrations`.
  - `001_initial.sql` creates every table and index in §2 verbatim. `schema_migrations` itself is created by `sherlock/db/migrate.py` before any migration runs.
  - Each migration runs in one transaction.
  - A test (`api/tests/test_db.py`) parses this document and fails if a table or a column, in order, differs from the migrated database. So any change to §2 needs a new migration in the same commit.
- ID prefixes are 2–4 letters (`ds_` is two). ULIDs are 26 Crockford base32 characters, generated in `sherlock/db/util.py`. Request IDs (`req_…`) use the same format but are never stored.

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
                                               -- plus, for ragged files only, width and header_fields (TRD §7.1, 2026-10-25)
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

As built (2026-10-25): a cleaning step from a scoped clean (some rows, or hand-edited cells kept) ends its `notebook_code` with `result = keep_outside_scope(df, result, rows=[…], cells=[…])` before `df = result`, so the notebook and a replay apply the same scope (TRD §7.7–§7.8). An undo step's `replayed_step_ids_json` lists the steps it replayed (D5.5).

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

Flags as written (2026-10-24, TRD §7.9): `quarantined` on a cell that lost its value in a row the same step quarantined (the original text stays in `old_value`); `flagged` on every changed cell of a step with gate `flag`; `invalid` on an edited cell whose value didn't parse as the column's type (the cell is NULL in the version and `new_value` keeps the typed text).

### 2.7 user_edited_cells

Tracks cells the user edited by hand so "Clean with AI" can skip them. Written by `commit_step` for edit batches; rows whose step is undone are deleted.

As built (2026-10-25, from the Day 2 review): when an undo deletes a cell's row, the cell stays protected if an edit batch still in the new version's effective chain also edited it. Its row then points at the latest such batch, found from that batch's lineage. Example: edit `age` → 5, edit `age` → 6, undo the second. The cell shows 5 and stays protected, now under the first batch.

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

As built (2026-10-25, D6.1): each fact in `facts_json` is `{value, format, label, formatted}` plus `sql`+`cell`, `sql`+`scalar`, or `from`+`formula` (TRD §6.4). `material_hash` is stored as an empty string (cut 6). The overview's sheet has `widget_id` NULL and keys prefixed `w<i>.`. Relations are rewritten for the current version on every stories run; `detail_json` is `{columns}` for shared columns or `{column}` for the target.

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

As built (2026-10-25, D6.1–D6.3): `narrated_by` is the model ID, or NULL when the card shows the fact-sheet bullets. Chip runs typed by hand have `key: null` and `unverified: true`. `suggestion_json` holds `{headline, body}` for an edited card after a cascade.

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

As built (2026-10-25, D8.1): `canvas_json` is stored with sorted keys and no spaces, and `etag` is the sha1 of that text. A dataset has no row until its first save; until then `GET /canvas` answers the empty document and its etag. Every save that changes the document bumps `datasets.state_rev`. Synthesis cards (`kind = 'synthesis'`) have `source_card_ids_json` and no `fact_sheet_id`; their chips' keys are `<card_id>.<fact key>`. Answer cards added to Flow (`kind = 'answer'`) have a fact sheet with no `widget_id`.

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

As built (2026-10-25, Implementation Plan D7, `sherlock/ml/runner.py`; no migration, migration 001 already had the table):
- **On request.** A run row is written with `status = queued`, `scope_json` (target filled in, any dashboard filter folded into the predicate, `inherit_global_filters: false`), `params_json` (manifest defaults filled in), `target` and `cache_key`. `job_id` is the `ml_run` job's.
- **Identity.** The `UNIQUE (dataset_id, cache_key)` makes a repeat request return the same row. A failed or cancelled run's row is reset to `queued` and reused.
- **On completion.** The job sets `status = done`, `model_card_json`, `fact_sheet_id`, `features_json` (the features used), `artifact_dir` (`runs/<id>/`), `repro_path`, `sample_json`, `libraries_json` and `finished_at`.
- **Outdated.** The cascade, or the run itself when it finishes on an earlier version, sets `status = outdated`.
- **`widget_id`.** The last widget that asked for the run. `widgets.run_id` is the link a widget shows, and a cached run can back more than one widget.
- **`created_by`.** `builder` for the dashboard's driver widget, otherwise `user`.
- **`fact_sheets.run_id`** is set on the run's own sheet. An analysis widget's sheet is a copy with its `widget_id`.
- **`widgets.spec_json`.** An analysis that replaced a chart keeps the chart's title in `view.options.chart_title`, for Undo.
- **`selections` for "who did it get wrong?"** (`POST /runs/{rid}/wrong-rows`, D7.4): `row_ids_json` holds the misclassified `_row_id`s, `predicate` is NULL, `label` is "<target>: predicted wrong", and `version` is the current version. Row IDs are stable across versions.

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

Implementation notes (2026-10-24, Implementation Plan D2.5):
- `job_events` holds every SSE event of a dataset (TRD §5), not only job events. An event that doesn't come from a job, such as `version.created` for a step committed through the API, has `job_id` NULL. So every event has an `id` and can be replayed.
- `data_json` always carries `dataset_id`, which the user-level stream needs.
- `jobs.owner_pid` is `<hostname>:<pid>:<ulid>`, unique per process start. At startup, every `running` job is re-queued (one process holds the runner). While running, a sweep every 30 s re-queues any `running` job of another owner whose `heartbeat_at` is older than 60 s.
- `jobs.progress_json` is NULL until the job reports; the API then shows `{step: 0, of: 0, label: "", pct: 0}`.

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
  created_at    TEXT NOT NULL
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

As built (2026-10-25, D8.5): `messages.plan_json` holds `{ steps: [{ text, status }] }` with the final statuses, and `proposal_id` the proposal the message made. `proposals.payload_json` is `{ summary, edits: [{ row_id, column, value, before }], impact }` for `edit_cells` and `{ summary, scope: { kind, selection_id }, impact }` for `clean_selection`; `result_step_id` is the edit step an approved `edit_cells` committed. `thread_summaries` is written by the running summary (TRD §8.1).

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

### 2.18 llm_calls and sandbox_runs

```sql
CREATE TABLE llm_calls (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     TEXT, dataset_id TEXT, job_id TEXT, message_id TEXT,
  role        TEXT NOT NULL,                   -- large|medium|small|embed
  model       TEXT NOT NULL,
  purpose     TEXT NOT NULL,                   -- diagnose|propose|critic|curate|narrate|route|sql|compose|…
  prompt_tokens INTEGER, completion_tokens INTEGER,
  latency_ms  INTEGER,
  ok          INTEGER NOT NULL,
  error       TEXT,
  repaired    INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL
);
CREATE INDEX llm_calls_user_day ON llm_calls(user_id, created_at);

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

As built (2026-10-25, D5.6): `version` is the version the notebook rebuilds (the current one, or the earlier one for `up_to_step`), set when the job finishes. The user's last options are kept in `users.settings_json.notebook`.

### 2.20 schema_migrations

```sql
CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
```

---

## 3. DuckDB (in-memory, cached per version)

There is no persistent DuckDB file. Versions are immutable Parquet files, and queries use a cached in-memory connection per (dataset, version), opened on first use:

```sql
-- on first use per (dataset, version); the connection is then cached in the single API process
CREATE TABLE t AS SELECT * FROM read_parquet('/data/users/<user_id>/datasets/<dataset_id>/versions/v7.parquet');  -- absolute path
SET enable_external_access = false;   -- then run the validated SELECT
```

Quarantine lives only in the `_quarantine_reason` column of each version. Predictions live only in `runs/<run_id>/results/predictions.parquet` (`run_id`, `_row_id`, `prediction`, `probability`, `interval_low`, `interval_high`, `low_confidence`, `ood`).

Column conventions inside a version Parquet:
- `_row_id BIGINT NOT NULL` unique, assigned at import (1…n); new rows take `datasets.next_row_id`, so ids are never reused.
- `_quarantine_reason VARCHAR` nullable, created at import (all NULL); rows with a value are excluded from widgets, ML and stories by the compiled `{{rows}}` filter, which is visible in the shown SQL (the row-page API returns them with `quarantined: true`).
- User columns keep their original names; characters outside `[A-Za-z0-9_]` are allowed and always quoted in generated SQL.

Queries from widgets and answerers run on that in-memory connection after external access is turned off, with a 10 s interrupt.

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
        model_card.json             the ModelCard (as built, D7)
        results/*.parquet           predictions, importance, pdp, coefficients
                                    (as built, D7: results/importance.json and results/partial_dependence.json;
                                    JSON because pyarrow isn't a dependency; no predictions or coefficients, cuts 4 and 7;
                                    results/oof.json for classification: _row_id, actual, predicted, probability,
                                    the out-of-fold predictions behind the confusion matrix, ROC and "who did it get wrong?")
      exports/
        notebook_<cache_key>.ipynb  generated notebooks (ephemeral, 24 h)
        *.csv, *.py                 other generated exports (ephemeral)
  sample/                           the seeded sample artifacts, cloned per user on demand
```

`datasets.folder_bytes` is recomputed after every commit and run; `users.storage_bytes` is the sum. Uploads are refused when the user's total would exceed `USER_STORAGE_MB`.

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
| UI state (tab, scroll, panel widths) | client | browser local storage; `datasets.last_tab` server-side |

---

## 6. Retention and purge

A `purge` job runs every 10 minutes:
1. Hard-delete datasets, widgets and cards with `deleted_at` older than 10 minutes (files included).
2. Delete datasets past `expires_at` (soft-delete first, hard-delete on the next pass).
3. Delete `job_events` older than 24 h, `widget_cache` rows older than 24 h, and `exports` rows and files older than 24 h.
4. Delete sandbox temp directories (`/tmp/sherlock-sandbox/`, outside `/data`) older than 1 h.
5. Recompute `users.storage_bytes`.

---

## 7. Integrity rules enforced in code

- A step's `to_version` equals `from_version + 1` and the dataset's `current_version` after commit; commits are serialized per dataset with a file lock (`<dataset>/.lock`). Every commit passes `base_version` and is rejected (409) when it differs from `current_version`.
- Every lineage row belongs to one step and the version that application of the step produced; replays write fresh rows under the original step ids for the new version.
- A card's `fact_sheet_id` always points at a sheet for the card's `version` (or an older one while `status = outdated`).
- A run with `status = done` has `model_card_json` and an artifact dir; `outdated` keeps them for display.
- `widgets.run_id` is set only for `op.type = ml` widgets and points at a run on the same dataset.
- Canvas card nodes reference existing cards; nodes of hard-deleted cards are pruned on read.
- Every step has non-empty `notebook_code`, and a clean or computed_column step's ends with `df = result`; a commit without it is rejected. Every version has `effective_step_ids_json`. Every run with `status = done` has `repro_path`. This is what guarantees the notebook export can always be produced.
