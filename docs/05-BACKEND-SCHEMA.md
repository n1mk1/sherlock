# Sherlock · Backend Schema

Version 1.3 · 2026-10-25 · Every table, column, file and index. SQLite holds app state; Parquet holds data (queried through in-memory DuckDB); the filesystem holds artifacts.

---

## 1. Conventions

- **IDs** are a 2–4 letter prefix, `_` and a ULID (26 Crockford base32 characters that sort by creation time), made by `new_id` in `sherlock/db/util.py`.
  - Stored prefixes: `usr_`, `ds_`, `stp_`, `iss_`, `wdg_`, `fs_`, `crd_`, `run_`, `job_`, `msg_`, `prp_`, `sel_`, `exp_`, `pln_`.
  - Inside JSON: plan items `pit_` (`clean_plans.items_json`, §2.21); canvas nodes `nd_` and edges `ed_` that the AI adds (`canvas_json`, `canvas/service.py`).
  - Request IDs (`req_…`) use the same format and are never stored. There is no `ver_`: a version is keyed by `(dataset_id, version)` (§2.3).
- **Timestamps** are ISO-8601 UTC `TEXT` with milliseconds (`2026-10-25T09:30:00.000Z`, `now_iso`).
- **JSON columns** are `TEXT` holding JSON, validated by pydantic models on write. The column comment names the shape; [TRD §6](04-TRD.md) defines it.
- **Soft deletes** set `deleted_at`. The purge hard-deletes rows and files 10 minutes later (datasets, widgets, cards); an expired dataset is soft-deleted first (§6).
- **SQLite settings** (`sherlock/db/connection.py`): `PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000; PRAGMA synchronous=NORMAL`.
- **Migrations** are numbered files `NNN_name.sql` in `api/sherlock/db/migrations/`. At startup `migrate()` (`sherlock/db/migrate.py`) creates `schema_migrations`, then applies, in number order, every file not yet recorded, each in one transaction.

  | File | Adds |
  |---|---|
  | `001_initial.sql` | every table and index in §2.1–§2.19 |
  | `002_clean_plans.sql` | `clean_plans` and `clean_plans_one_draft` (§2.21) |
  | `003_plan_scope.sql` | `clean_plans.scope_json` |
  | `004_llm_calls_indexes.sql` | `llm_calls.cached`; indexes `llm_calls_message`, `llm_calls_job`, `llm_calls_created` (§2.18) |
  | `005_web_cache.sql` | `web_cache` and `web_cache_created` (§2.22); `llm_calls.results` |
  | `006_message_version.sql` | `messages.version`, back-filled (§2.15) |
  | `007_llm_fallback.sql` | `llm_calls.fallback_from` (§2.18) |
  | `008_column_notes.sql` | `column_notes` (§2.23) |

  Each schema change gets its own new file. The tables below show columns added by `ALTER TABLE` at the end, in the order SQLite stores them.
- **The doc is tested.** `api/tests/test_db.py` parses every `CREATE TABLE` block here and fails if the tables or any table's columns (in order) differ from the migrated database, so a change to §2 needs a new migration in the same commit. The test checks names only; the blocks also match the migrations' types, defaults, keys and indexes. Comments here may be longer than the SQL's.
- There are no `CHECK` constraints: allowed values (the `a|b|c` comments) are the values code writes. A few are checked on write: `steps.kind` and `created_by` (`KINDS`, `CREATORS` in `steps/commit.py`), `jobs.kind` (`KINDS` in `jobs/runner.py`), `datasets.last_tab` (the request model). A value no code writes is marked where it appears.

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

- `last_seen_at` is refreshed at most once a minute (`db/users.py`).
- A user with no datasets not seen for 24 h is deleted by the purge (§6).
- `settings_json.notebook` keeps the user's last notebook options, without `up_to_step` (`routers/exports.py`).

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
  state_rev        INTEGER NOT NULL DEFAULT 0,  -- bumped on any step, widget, card, run, layout or canvas write (export cache key)
  created_at       TEXT NOT NULL,
  deleted_at       TEXT
);
CREATE INDEX datasets_user ON datasets(user_id, deleted_at, last_opened_at DESC);
CREATE INDEX datasets_expiry ON datasets(expires_at);
```

`import_options_json` is `ResolvedOptions` (`ingest/options.py`), stored without nulls.

### 2.3 versions

```sql
CREATE TABLE versions (
  dataset_id   TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  version      INTEGER NOT NULL,               -- 1 = raw import
  parquet_path TEXT NOT NULL,                  -- relative to the dataset folder; an undo version points at an earlier version's file (TRD §7.8)
  row_count    INTEGER NOT NULL,
  column_count INTEGER NOT NULL,
  columns_json TEXT NOT NULL,                  -- [{name, type}] in order, after the step, _row_id and _quarantine_reason included (column_count leaves them out)
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
  gate           TEXT,                         -- commit|flag|user; NULL for undo (a skipped issue makes no step, so skip is never stored)
  flag_reason    TEXT,
  decisions_json TEXT NOT NULL DEFAULT '[]',
  verifiers_json TEXT NOT NULL DEFAULT '{}',
  replayed_step_ids_json TEXT,                 -- for undo with replay: the steps it replayed
  undone_step_id TEXT,                         -- for kind=undo: which step was undone
  created_by     TEXT NOT NULL,                -- system|cleaner|user|chat (system = the automatic typing step)
  job_id         TEXT,
  created_at     TEXT NOT NULL,
  UNIQUE (dataset_id, no)
);
CREATE INDEX steps_dataset ON steps(dataset_id, no DESC);
```

A step from a scoped clean (some rows, or hand-edited cells kept) ends its `notebook_code` with `result = keep_outside_scope(df, result, rows=[…], cells=[…])` before `df = result`, so the notebook and a replay apply the same scope (TRD §7.7–§7.8).

Who writes which kind: the typing step is `clean` by `system` (`profile/typing.py`, gate `commit`); the Cleaner's are `clean` by `cleaner` (gate `commit` or `flag`); grid saves and approved chat edits are `edit` by `user` (gate `user`, `rows/edits.py`); undos are `undo` by `user` (`steps/undo.py`). No code makes `ml_column` or `computed_column` steps, and no step has `created_by = 'chat'` (not built yet).

### 2.6 lineage

One row per changed cell, per step, per version that the step's application produced (a replay adds rows). Append-only, indexed by cell.

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

- Row-level events use `column = '_row'` and `new_value` ∈ `added|deleted|quarantined|restored` (`steps/diff.py`); a `quarantined` event also has flag `quarantined`.
- Flags (TRD §7.9):
  - `quarantined`: a cell that lost its value in a row the same step quarantined; the original text stays in `old_value`.
  - `flagged`: every changed cell (not `_row` events) of a step with gate `flag` that has no other flag.
  - `predicted`: not built yet (no `ml_column` step is made).
  - `invalid`: an edited cell whose value didn't parse as the column's type. The cell is NULL in the version; `new_value` keeps the typed text.

### 2.7 user_edited_cells

Cells the user edited by hand, so Clean with AI skips them.

```sql
CREATE TABLE user_edited_cells (
  dataset_id TEXT NOT NULL,
  row_id     INTEGER NOT NULL,
  column     TEXT NOT NULL,
  step_id    TEXT NOT NULL,
  PRIMARY KEY (dataset_id, row_id, column)
) WITHOUT ROWID;
```

- Written by `commit_step` for edit batches (`steps/commit.py`), and by an undo's replay for each edit batch it replays; `_row` events are not cells.
- Undoing a step deletes its rows (`steps/undo.py`). A cell stays protected if an edit batch still in the new version's effective chain also edited it; its row then points at the latest such batch, found from that batch's lineage. Example: edit `age` → 5, edit `age` → 6, undo the second: the cell shows 5 and stays protected under the first batch.

### 2.8 issues

Detected issues per version: the DataCard's `issues`, normalized for querying and for tracking what the Cleaner handled. Written by the profile (`profile/service.py`), which replaces a version's rows each time it profiles it. The Cleaner sets `outcome` (`fixed` or `flagged` with `handled_by_step_id`, or `skipped` with `skip_reason`, `cleaning/loop.py`).

```sql
CREATE TABLE issues (
  id         TEXT PRIMARY KEY,                 -- iss_…
  dataset_id TEXT NOT NULL,
  version    INTEGER NOT NULL,
  detector   TEXT NOT NULL,
  column     TEXT,
  count      INTEGER NOT NULL,
  severity   REAL NOT NULL,
  details_json TEXT NOT NULL,                  -- examples, proposal, plus the detector's own details
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
  spec_hash     TEXT NOT NULL,                 -- sha1 of the spec's canonical JSON (cache key part)
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

- `spec_hash` is the sha1 of the spec's canonical JSON (sorted keys, no spaces), not of the stored `spec_json` text (`widgets/spec.py`).
- `widget_cache.cache_key` is the sha1 of `<spec_hash>:<version>:<filter_hash>`; `filter_hash` is the sha1 of the compiled row filter (`widgets/execute.py`).
- An in-memory LRU of 500 entries (`LRU_SIZE`) sits in front of `widget_cache` (TRD §9). The purge deletes rows older than 24 h (§6).
- An analysis widget that replaced a chart keeps the chart's title in `spec_json` `view.options.chart_title`, for Undo. A chart whose change also retitled it keeps the old title in `view.options.undo_title` (`widgets/service.py`).
- `prev_spec_json`: changing an analysis's settings keeps the chart it replaced there, so Undo goes back to the chart. Undo swaps the two specs, so a second Undo puts it back.
- `run_id` is written only by `ml.link` (`ml/runner.py`), for `op.type = ml` specs; the widget's `status` then follows the run's. It is kept when the widget goes back to a chart, so Undo can return to the run.

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

- Each fact in `facts_json` is `{value, format, label, formatted}` plus `sql`+`cell`, `sql`+`scalar`, or `from`+`formula` (TRD §6.4).
- `material_hash` is always written as `''` (cut 6).
- The overview's sheet and an answer card's sheet (§2.12) have `widget_id` NULL; the overview's keys are prefixed `w<i>.`.
- A run's own sheet has `run_id` set and the `widget_id` of the widget that asked for the run (§2.13). An analysis widget's sheet is a copy with its `widget_id`. A web answer's card has an empty sheet (`{}`, no columns).
- Relations are rewritten for the current version on every stories run (`stories/service.py`). `detail_json` is `{columns}` for `shared_column` and `{column}` for `same_target`.
- Only `shared_column` (weight 0.5) and `same_target` (0.3) are written; a pair is kept when its weights sum to 0.4 or more, at most four pairs per widget. `correlated` and `dependency` are not built yet.

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

- `narrated_by` is the model ID, or NULL when the card shows the fact-sheet bullets (and on answer cards, which keep chat's text).
- No code writes `direction` cards (cut 3), so `job_id` is always NULL and `building` and `failed` are never written. Widget cards go `updating` while re-told; widget, overview and answer cards go `outdated` when their numbers moved (or an analysis's run failed); synthesis cards go `sources_changed` (`stories/service.py`, `stories/synthesis.py`).
- Chip runs typed by hand have `key: null` and `unverified: true`.
- `suggestion_json` holds `{headline, body}` for a user-edited card that was told again. That write moves `fact_sheet_id` to the new sheet but keeps `version` (and the user's text) where it was; editing a card sets `version` to its sheet's.
- Synthesis cards (`kind = 'synthesis'`) have `source_card_ids_json` and no `fact_sheet_id`; their chips' keys are `<card_id>.<fact key>`.
- Answer cards added to Flow (`kind = 'answer'`) have a fact sheet with no `widget_id` (`agent/flow.py`). One that cites story cards lists them in `source_card_ids_json`.

### 2.12 canvases

```sql
CREATE TABLE canvases (
  dataset_id  TEXT PRIMARY KEY REFERENCES datasets(id) ON DELETE CASCADE,
  canvas_json TEXT NOT NULL,                   -- JSON Canvas document
  etag        TEXT NOT NULL,                   -- sha1 of canvas_json
  updated_at  TEXT NOT NULL
);
```

- `canvas_json` is stored with sorted keys and no spaces; `etag` is the sha1 of that text (`canvas/service.py`).
- A dataset has no row until its first save; until then `GET /canvas` answers the empty document and its etag.
- Every save that changes the document bumps `datasets.state_rev` and emits `canvas.updated`.
- Card nodes reference `cards.id` (`sherlock.card_id`). Nodes of soft-deleted cards stay, hidden, so Undo restores them in place.
- Nodes (and their edges) whose card is hard-deleted are pruned when the purge removes the card, which bumps `state_rev` and emits `canvas.updated`; any canvas read that finds such a node also prunes it and writes a new etag.
- Every write is checked (`canvas.validate`, else `422`): at most 400 nodes and 800 edges, a card node names one of this dataset's cards and appears once, an edge joins two different nodes, edge `sherlock` is `{made_by: user|ai, kind: summarized_in|next|contrasts|custom}`. A saved card node of a card that's gone for good is dropped, not refused.

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

Lifecycle (`sherlock/ml/runner.py`):
- **On request.** The row is written with `status = queued`, `scope_json` (target filled in, any dashboard filter folded into the predicate, `inherit_global_filters: false`), `params_json` (manifest defaults filled in), `target`, `cache_key`, and the `ml_run` job's `job_id`.
- **Identity.** `UNIQUE (dataset_id, cache_key)` makes a repeat request return the same row. A failed or cancelled run's row is reset to `queued` (error, model card and `finished_at` cleared) and reused.
- **Running.** The job sets `status = running` when it starts.
- **On completion.** The job sets `status = done`, `model_card_json`, `fact_sheet_id`, `features_json`, `artifact_dir` (`runs/<id>/`), `repro_path`, `sample_json` (NULL when not sampled), `libraries_json` (pandas, numpy, duckdb, scikit-learn) and `finished_at`.
- **On failure.** The job's failure hook sets `failed` with the error, or `cancelled` with "Cancelled.", and `finished_at`.
- **Outdated.** The cascade sets `status = outdated` on `done` runs of earlier versions that read a changed column (`outdate`), and so does the run itself when it finishes on an earlier version.

Links:
- `widget_id` is the last widget that asked for the run. `widgets.run_id` is the link a widget shows; one cached run can back several widgets. The purge unlinks a run from a purged widget.
- `created_by`: `builder` for the dashboard's driver widget; `chat` for a run that chat's `ask_why` starts (`agent/insight.py`); otherwise `user` (`POST /datasets/{id}/runs`, an analysis widget the user adds or changes, and every Re-run, automatic ones included).
- "Who did it get wrong?" (`POST /runs/{rid}/wrong-rows`) writes a `selections` row (§2.16): `row_ids_json` the misclassified `_row_id`s from `results/oof.json`, `predicate` NULL, `label` "<target>: predicted wrong", `version` the current version. Row IDs are stable across versions.

### 2.14 jobs and job_events

```sql
CREATE TABLE jobs (
  id         TEXT PRIMARY KEY,                 -- job_…
  dataset_id TEXT REFERENCES datasets(id) ON DELETE CASCADE,
  user_id    TEXT NOT NULL,
  kind       TEXT NOT NULL,                    -- profile|clean|build_dashboard|stories|ml_run|cascade|undo|export_notebook|purge
  status     TEXT NOT NULL,                    -- queued|running|done|failed|cancelled
  params_json TEXT NOT NULL DEFAULT '{}',
  state_json TEXT,                             -- checkpoint; a clean job keeps its RunState here (TRD §7.2)
  progress_json TEXT,                          -- {step, of, label, pct}
  result_json TEXT,
  error      TEXT,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  owner_pid  TEXT,                             -- process that is running it: <hostname>:<pid>:<ulid>
  heartbeat_at TEXT,                           -- refreshed every 10 s while running; another owner's job stale for 60 s is re-queued
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

`jobs` (`sherlock/jobs/runner.py`, `KINDS`):
- **Recovery.** `owner_pid` is unique per process start. At startup, a `running` job of another owner with `cancel_requested = 1` is marked `cancelled`; every other `running` job is re-queued, and a `profiling` dataset with no live `profile` job gets one. While running, a sweep every 30 s re-queues any `running` job of another owner whose `heartbeat_at` is older than 60 s.
- **One at a time.** `cascade`, `stories` and `build_dashboard` (`SERIAL_KINDS`) run one at a time per dataset: the claim skips a queued one while another runs for its dataset.
- `tokens_used` sums the job's model tokens; the job's budget reads it (TRD §3.5).
- `progress_json` is NULL until the job reports; the API then shows `{step: 0, of: 0, label: "", pct: 0}`.
- **`undo`** is a listed kind, but no `undo` job is queued: an undo, its replay included, runs inside its request (TRD §7.8).
- **`purge`** jobs have `user_id = 'system'` and `dataset_id` NULL (§6).
- **`clean`** started from a cleaning plan (PRD CLEAN-8a): `params_json.plan` is `{id, version, items}`, a frozen copy of the plan's items when Start was pressed (§2.21), so later edits can't change a running job. `state_json` is the Cleaner's `RunState` (`cleaning/loop.py`): `from_version`, `ended_by`, `plan_id`, `max_steps`, `max_seconds`, `waited_for_model_s`, `attempted`, `handled`, `skipped`, `hand_edited_skipped` (at most 500), `step_ids` and `plan_outcomes` (plan item ID → `{outcome, reason?, step_id?, step_no?}`, which the report's `your_steps` reads, TRD §7.2).
- **`build_dashboard`** queued by the profile because After upload is "I'll clean it myself" has `params_json.automatic: true` (the `Job` response shows it, TRD §4.10). No `clean` job is queued without a click: "Open the cleaning plan" only makes a draft (§2.21).

`job_events`:
- Holds every SSE event of a dataset (TRD §5), not only job events, so every event has an `id` and can be replayed. An event that doesn't come from a job (such as `version.created` for a step committed through the API) has `job_id` NULL.
- `data_json` always carries `dataset_id`, which the user-level stream needs (`jobs/events.py`). A job with no dataset (the purge) writes no events.
- The purge deletes rows older than 24 h (§6).

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
  plan_json     TEXT,                          -- {steps: [{text, status}]} with the final statuses
  clarification_json TEXT,
  clarification_of TEXT,                       -- message id this answers
  proposal_id   TEXT,                          -- the proposal this message made
  route_json    TEXT,                          -- the router output (debug/eval)
  tokens_used   INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL,
  version       INTEGER                        -- the dataset version the message read (006)
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

- **`messages.version`** is `datasets.current_version` when the message was written: the version an answer's queries ran on. Migration 006 back-filled older messages with the newest version created at or before the message (versions only go up; an undo is a new version). The thread's history lines, Add to Flow and the `Message` response read it (TRD §8.1, §4.9).
- **`messages.role`** is `user` or `assistant` (`agent/loop.py` `_save`); no code writes `system` messages.
- **`thread_summaries`** is written by the running summary (TRD §8.1, `agent/loop.py`).
- **Proposal kinds built:** only `edit_cells` and `clean_selection` are written (`agent/actions.py`). `card_edit` is not built (cut 2, Implementation Plan §2.0); `clean_step` and `computed_column` are P1. Approving any other kind answers `422`.
- **`edit_cells` payload:** `{summary, edits: [{row_id, column, value, before}], impact, warnings?}`; `warnings` are code's sentences for new numbers outside their column's range (TRD §4.4). Approving commits an edit step with `created_by = 'user'` through the grid's save (`rows/edits.py`); `result_step_id` is that step.
- **`clean_selection` payload:** `{summary, scope: {kind: selection|all, selection_id}, impact: {cells_changed: 0, rows_affected}}`. Selected cells with no saved selection become a `selections` row labelled "Selected in CSV". Approving opens the cleaning plan with that scope (§2.21).
- **Status.** Approve and reject set `approved` or `rejected` and `resolved_at`; approving one whose `base_version` is no longer current sets `expired` and answers `409` (`agent/actions.py`).

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

- `row_count` stays the count on the version the selection was made on.
- Reads recount on the current version: `widgets.service.selection_rows` counts the usable rows (the predicate's or the IDs still present, quarantined rows left out) whenever chat's context, a `clean_selection` proposal or a cleaning plan's scope reads a selection.

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

- The profile rewrites a dataset's whole index each time it profiles the current version, since the key has no version (`profile/service.py`).
- It indexes columns whose role is in `VALUE_INDEX_ROLES` (`dimension`, `target_like`), at most `MAX_INDEXED_VALUES` (10,000) most common values each, as text with their counts.
- **Embeddings are not built** while `MODEL_EMBED` is empty (TRD §3.5): `embedding` is always NULL and there is no `vec_values` table; chat resolves values exactly, then with rapidfuzz (TRD §8.1). Designed: a `vec_values` virtual table mirroring `embedding` when `sqlite-vec` is installed, else numpy similarity over the column's rows (≤ 5,000).

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

**Purposes written** (the `purpose=` arguments in code):

| Feature | Purposes |
|---|---|
| Chat | `route`, `plan`, `sql`, `sql_check`, `predicate`, `widget`, `update_widget`, `compose`, `stats`, `meaning`, `edits`, `ask_story`, `plan_edits`, `summary` |
| Cleaner | `diagnose`, `propose`, `critic` |
| Dashboard builder | `curate` |
| Stories | `narrate`, `overview`, `synthesis` |
| Web retrieval (TRD §3.6, §8.2) | Nemotron rows: `web_query`, `web_answer`, `meaning_web`, `dictionary`; web rows: `web_context`, `meaning_web`, `dictionary` |

**Model rows:**
- A failed call is logged too, with `ok = 0` and its error. No `embed` row is written while `MODEL_EMBED` is empty.
- Budgets (TRD §3.5): the app-wide daily token ceiling sums `llm_calls` since midnight UTC before every model call (index `llm_calls_created`); a user's daily count is kept in `users.tokens_used_today` (with `tokens_day`), a job's in `jobs.tokens_used` (`llm/client.py`).
- `error` keeps at most 500 characters.
- `cached` is always 0: the model client has no cache.
- **`fallback_from`:** the model client sends a Super (`medium`) call to Ultra (`large`) when Super's circuit breaker is open or its next retry would pass the call's deadline (TRD §3.5). That row has `role = 'large'`, Ultra's `model`, the original `purpose` and `fallback_from = 'medium'`; every other row has NULL. Receipts show it, and `sherlock llm stats` reports the fallback rate (`llm/calls.py`).

**Web rows** (`web/client.py`):
- A Tavily call is a row with `role = 'web'`, `model` the tool (`tavily-search`, `tavily-extract`, `tavily-map`), the calling feature's purpose, `latency_ms`, `ok`, `error` (at most 500 characters) and `results`.
- Both token columns are NULL, so no token budget counts it.
- A hit in the 24 h `web_cache` (§2.22) writes `cached = 1` and latency 0.
- The hourly limit (`WEB_RATE_LIMIT`, default 20; 0 = no cap) counts a user's web rows with `cached = 0` in the last hour.
- A call that never goes out (web off, no key, the limit, no time left) writes no row. A call that times out or fails writes a row with `ok = 0`.

**Receipts** (TRD §4.9, §4.10): `GET /chat/messages/{mid}/calls` reads the rows with that `message_id`, and `GET /jobs/{jid}/calls` the rows with that `job_id`, oldest first (`ORDER BY id`, at most 500 listed; the totals count every row), through `sherlock/llm/calls.py`. Indexes `llm_calls_message` and `llm_calls_job` keep those reads off a full scan.

**Retention:** neither table is purged; the budgets and the spend figures read `llm_calls`.

`sandbox_runs` gets one row per sandboxed code run (`sandbox/runner.py`): `code_hash` is the code's sha256, and `step_id` and `cpu_ms` are always NULL.

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
  counts_json TEXT,                            -- {steps, widgets, runs, cards, notes}
  error       TEXT,
  created_at  TEXT NOT NULL,
  finished_at TEXT,
  UNIQUE (dataset_id, cache_key)
);
CREATE INDEX exports_dataset ON exports(dataset_id, created_at DESC);
```

- `cache_key` is the sha1 of `notebook:<current_version>:<state_rev>:<options as sorted JSON>` (`notebook/exporter.py`). A request whose key has a `done` row with its file present returns it as cached; one with a `queued` or `running` row returns that row; a `failed` row, or one whose file was purged, is deleted and made again (`routers/exports.py`).
- `version` is written as the current version, then set by the job to the version the notebook rebuilds (the earlier one for `up_to_step`) when it finishes (`jobs/export.py`). The job sets `running`, then `done` with `path`, `bytes` and `counts_json`, or `failed` with its error.
- A new version doesn't delete older exports; they stay valid for their version. The purge removes rows older than 24 h and their files (§6).

### 2.20 schema_migrations

```sql
CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
```

Created by `migrate()` before any migration runs (§1); one row per applied file.

### 2.21 clean_plans

The cleaning plan (PRD CLEAN-8a, CLEAN-8b, TRD §4.4, §7.2): what Clean with AI will try, diagnosed by the code detectors on a version, editable until it starts.

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

- **One draft.** The partial unique index allows at most one `draft` per dataset. `POST /datasets/{id}/clean/plan` returns it or makes it.
- **Status.** Discard and Clean it myself (`POST /use-as-is`) set `discarded`. Start sets `started` and `job_id`, and the job's `params_json` keeps a frozen copy of the items (§2.14). Started and discarded plans are kept as history.
- **`version`** moves when a draft is merged onto a newer version before it's shown or started (`cleaning/plan.py` `merge`): ticks and instructions are kept by issue key, and the user's steps while their column exists.
- **`items_json`** holds Sherlock's fixes (`source: "sherlock"`, each with its rewritten `instruction`) and the user's own steps (PRD CLEAN-8b: `detector: "user_request"`, `key: null`, `source: "you"|"chat"`). The clean job's `state_json.plan_outcomes` records each item's outcome (§2.14).
- **`scope_json`** is the rows a plan was opened for, so a reload can't widen it to the whole file: `new_rows` with the saved rows' IDs (from the new-rows toast's "Clean them"), or `selection` with the selection's ID (from approving chat's `clean_selection`, PRD CLEAN-1). `rows` is the count the panel shows. `POST …/clean/plan` with a scope replaces it, a whole-dataset scope clears it, and no scope leaves it. The job's own scope comes from `POST /clean`, which the panel sends from the scope the user leaves picked.
- **`source`** is `after_upload` when the profile job made the draft because After upload is "Open the cleaning plan"; the plan screen then says why it opened.
- Deleted with the dataset by the foreign key cascade (§6).

### 2.22 web_cache

Tavily responses (TRD §3.6), so the same search, extract or map within 24 h makes no second call.

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

- `key` is the sha1 of `<kind>\n<parameters as sorted JSON>` (`web/client.py` `cache_key`). Only the query (or URLs and instructions), the topic and the time range vary; the rest is fixed in code, so the same question asked twice is one key.
- It belongs to no user or dataset: a request holds only the user's words and column names, never data, and the response is public web content. A hit is still logged as an `llm_calls` row with `cached = 1` under the asking user (§2.18).
- A row older than 24 h is ignored when read and deleted by the purge (§6). A failed call isn't cached; a repeat success overwrites the row.
- `created_at` is when Tavily returned the reply, so a cached answer shows the date it was retrieved.

### 2.23 column_notes

What a column means: from a data dictionary the user linked (`kind = 'dictionary'`, PRD LOAD-7, TRD §7.1.1), or read from the web when chat explains a column (`kind = 'web'`, TRD §8.2 `ask_meaning`).

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

- **Metadata, not data** (CLAUDE.md Rule 3): a note never changes a value, so it isn't a step and has no version. It is keyed by column name; after a rename the old name's note matches no column and isn't shown.
- **`description`** of a `dictionary` note is one sentence Super writes from the excerpt, with no digits or numbers in words (`ColumnNotes`, TRD §7.1); a `web` note's is the text of chat's web meaning answer (`remember_meaning`). Codes and their numbers stay in **`excerpt`**, the chunk of the page Tavily returned (for `web`, the first cited result's snippet), shown verbatim beside it (at most 600 characters, `SNIPPET_CHARS` in `agent/web.py`).
- **One note per column and kind.** Reading a dictionary again replaces the column's `dictionary` note; a new web meaning replaces its `web` note. Readers show the `dictionary` note first, and with one chat doesn't search the web for that column.
- Deleted with the dataset by the foreign key cascade (§6).

---

## 3. DuckDB (in-memory, cached per version)

There is no persistent DuckDB file. Versions are immutable Parquet files; queries use a cached in-memory connection per (dataset, version), opened on first use:

```sql
-- on first use per (dataset, version); the connection is then cached in the single API process
CREATE TABLE t AS SELECT * FROM read_parquet('/data/users/<user_id>/datasets/<dataset_id>/versions/v7.parquet');  -- absolute path
SET enable_external_access = false;   -- then run the validated SELECT
```

**Connections** (`sherlock/storage.py` `VersionConnections`, `new_duckdb`):
- At most four stay open (`MAX_CACHED_CONNECTIONS`), least recently used closed first. Opening a version closes the same dataset's older versions.
- Each has `memory_limit` = `DUCKDB_MEMORY_MB` (default 1024), `threads = 2`, and its own spill folder under `/data/.duckdb/` (§4).
- Each serves one request at a time. A connection evicted while a request holds or waits for it closes when the last such request ends.
- Widget and answer queries run with external access off and a 10 s interrupt (`TIMEOUT_S` in `widgets/execute.py`).

**Where state lives:**
- Quarantine lives only in each version's `_quarantine_reason` column.
- No predictions Parquet is written (cut 7). Classification runs keep out-of-fold predictions in `runs/<run_id>/results/oof.json` (§4). The planned `results/predictions.parquet` (`run_id`, `_row_id`, `prediction`, `probability`, `interval_low`, `interval_high`, `low_confidence`, `ood`) is not built.

**Columns inside a version Parquet:**
- `_row_id BIGINT NOT NULL`, unique, assigned at import (1…n). New rows take `datasets.next_row_id`, so IDs are never reused.
- `_quarantine_reason VARCHAR`, nullable, created at import: NULL except on rows with more fields than the header, which are quarantined there (their extra values in `col_N` columns, `ingest/importer.py`). Rows with a value are excluded from widgets, ML and stories by the compiled `{{rows}}` filter, which shows in the displayed SQL. The row-page API returns them with `quarantined: true`.
- User columns keep their original names. Characters outside `[A-Za-z0-9_]` are allowed and always quoted in generated SQL.

---

## 4. Filesystem layout

Under `DATA_DIR` (`/data` in the image). Paths in the database are relative to the dataset folder (`storage.dataset_dir`).

```
/data/
  sherlock.db                       SQLite
  .boots, .lockcheck.db             the startup storage check (storage_check.py, TRD §11)
  .duckdb/<hex>/                    one DuckDB connection's spill folder (TRD §3.2)
  .clean/<job_id>/                  a clean job's working folder (sample, candidate and commit Parquet)
  users/<user_id>/
    datasets/<dataset_id>/
      .lock                         the commit lock (§7)
      raw.csv                       the upload, never modified
      .ingest.utf8.csv, .tmp/       transient during ingest (UTF-8 copy, DuckDB spill); deleted when it ends
      versions/
        v1.parquet … vN.parquet     immutable snapshots
        .replay_<hex>/              a replay's working folder, removed when it ends (steps/replay.py)
      runs/<run_id>/
        model.joblib
        repro.py                    reproduction code (TRD §6.7)
        model_card.json             the ModelCard
        results/
          importance.json           permutation importance
          partial_dependence.json
          oof.json                  classification only: _row_id, actual, predicted, probability (two classes)
      exports/
        notebook_<cache_key>.ipynb  generated notebooks (24 h)
```

- **Transient folders.** DuckDB creates a `.duckdb/<hex>/` folder when a query passes the memory cap and removes it when the connection closes; startup removes `/data/.duckdb/` whole. A `.clean/<job_id>/` folder is removed when the run reaches its report (`cleaning/loop.py`); a stopped or failed run leaves it for the purge (§6).
- **Run results** are JSON. There is no predictions or coefficients file (cuts 7 and 4). `oof.json` holds the out-of-fold predictions behind the confusion matrix, the ROC curve and "who did it get wrong?".
- **Exports.** Only notebooks are written. The CSV export (`GET /datasets/{id}/export.csv`) streams from the version and writes no file; `repro.py` downloads from `runs/<run_id>/`.
- **The sample.** Nothing is written under `/data/sample/`. The seed ships in the image as `api/samples/seed/titanic3/`: `rows.json` (the dataset's rows in every table it uses) and `files/` (its folder without `.lock` or `exports/`). `SAMPLE_SEED_DIR` points elsewhere, or `off` disables it (then the sample is imported and built the slow way). `POST /datasets/sample` clones the seed into a new dataset folder with fresh IDs (`sample_seed.py`, TRD §9).
- **Sizes.** `datasets.folder_bytes` and `users.storage_bytes` are updated at import, at a sample clone, and at every commit and undo. A finished run's artifacts and exported notebooks are counted at the next purge pass, which measures every folder again (§6).
- **Limit.** An upload is refused (`413`) when the user's stored bytes plus the new dataset folder (the upload and `v1.parquet`) would exceed `USER_STORAGE_MB` (default 500). The limit is checked only at upload (`ingest/importer.py`).
- Sandbox temp directories live outside `/data`, under `SANDBOX_TMP` or `<system temp>/sherlock-sandbox` (§6).

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

The `purge` job (`sherlock/jobs/purge.py`) runs these six steps, in this order, each a progress step:

1. **Deleted CSVs, widgets and cards.** Hard-delete datasets, widgets and cards whose `deleted_at` is more than 10 minutes old (`GRACE_S`), a dataset's folder included.
   - A purged widget takes its card and its fact sheets with it, and any run pointing at it is unlinked (`runs.widget_id = NULL`).
   - Each dataset that lost cards has its synthesis cards checked again (`synthesis.check_sources`): one citing a card that's gone becomes `sources_changed`. Its canvas is pruned of the gone cards' nodes; if that changed it, `state_rev` is bumped and `canvas.updated` emitted (§2.12).
2. **Expiry.** Soft-delete datasets past `expires_at` (`created_at + DATASET_TTL_DAYS`, default 7). They are hard-deleted by step 1 of the first pass after their 10-minute grace.
3. **Events, caches and exports.** Delete `job_events`, `widget_cache` and `web_cache` rows older than 24 h, and `exports` rows older than 24 h with their files.
4. **Temp folders.** Delete sandbox temp directories older than 1 h, and Cleaner work folders (`/data/.clean/<job_id>/`) older than 1 h whose `clean` job isn't queued or running.
5. **Empty workspaces.** Delete users with no dataset at all (soft-deleted ones count) whose `last_seen_at` is more than 24 h old. A browser that drops its cookie, or a script without one, makes a new user on every request; this keeps them from piling up.
6. **Storage recount.** Measure every dataset's `folder_bytes` again, then set each user's `storage_bytes` to the sum. Soft-deleted datasets count, since their files remain until purged.

**Hard-deleting a dataset** (`hard_delete_dataset`) drops its cached DuckDB connections, removes its folder, then deletes its rows:
- Cleared explicitly (`LOOSE_TABLES`, no cascading key): `lineage`, `user_edited_cells`, `issues`, `widget_cache`, `fact_sheets`, `relations`, `job_events`, `thread_summaries`, `proposals`, `value_index`.
- Then the `datasets` row; the cascading foreign keys remove `versions` (and `datacards`), `steps`, `widgets`, `layouts`, `cards`, `canvases`, `runs`, `jobs`, `messages`, `selections`, `exports`, `clean_plans` and `column_notes`.
- Kept: `llm_calls` and `sandbox_runs`, which the daily budgets and spend figures read (§2.18). `web_cache` belongs to no dataset.
- Only `datasets` references `users`, so deleting a user with no datasets removes that row alone.

**Ages.** Soft deletes and expiry compare against `deleted_at` and `expires_at`; `job_events`, `widget_cache`, `web_cache` and `exports` against `created_at`; sandbox and `.clean` folders against their modification time. Sandbox folders live under `SANDBOX_TMP`, or `<system temp>/sherlock-sandbox` when it's empty (`sandbox/runner.py` `sandbox_root`).

**Schedule** (`jobs/runner.py`). The runner's sweep (every 30 s) queues a purge at its first pass after a start, then once every `PURGE_INTERVAL_S` (default 600; `0` turns it off), and never while one is queued or running. No purge is queued when `JOB_WORKERS` is 0. The job's row has `user_id = 'system'` and no dataset, so it shows in no one's job list.

**Result.** The job's `result_json` counts `datasets`, `expired`, `widgets`, `cards`, `events`, `cache`, `web_cache`, `exports`, `sandbox_dirs`, `clean_dirs` and `users`.

---

## 7. Integrity rules enforced in code

- A step's `to_version` equals `from_version + 1` and the dataset's `current_version` after commit. Commits and undos are serialized per dataset with a thread lock plus a file lock (`<dataset>/.lock`, `storage.dataset_lock`, 30 s timeout). Every commit and undo passes `base_version` and is rejected (409) when it differs from `current_version` (`steps/commit.py`, `steps/undo.py`).
- `commit_step` rejects a new version file without a unique, non-null `_row_id` or without `_quarantine_reason` (`check_version_file`), a `clean`, `ml_column` or `computed_column` step that adds or removes rows (quarantine instead), and new rows whose `_row_id` is below `next_row_id`. Nothing is written when it rejects.
- Every lineage row belongs to one step and the version that application of the step produced; replays write fresh rows under the original step IDs for the new version.
- A card's `fact_sheet_id` points at a sheet of the card's `version`: the two are written together (`stories/service.py`). A card on an older version than the current one stays that way until it is told again or marked `outdated`. The exception is a user-edited card told again: its sheet moves to the new version while its `version` stays with the user's text (§2.11). Synthesis cards have no sheet.
- A run with `status = done` has `model_card_json` and `artifact_dir` (written in one update with `repro_path`, `ml/runner.py`); `outdated` keeps them for display. Resetting a failed or cancelled run clears `model_card_json`.
- `widgets.run_id` is written only by `ml.link`, with a run of the same dataset, for an `op.type = ml` spec. It stays when the widget goes back to a chart (§2.9).
- Canvas card nodes reference this dataset's cards: every write is checked (`canvas.validate`, `422`), and nodes of hard-deleted cards are pruned (§2.12).
- Every step has non-empty `notebook_code`, and a clean or computed_column step's ends with `df = result`; a commit without it is rejected (`validate_notebook_code`). Every version has `effective_step_ids_json`. Every run with `status = done` has `repro_path`. Together these guarantee the notebook export can always be produced.
