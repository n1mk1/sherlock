-- Migration 001: every table and index in docs/05-BACKEND-SCHEMA.md §2 (copied verbatim).
-- schema_migrations is created by sherlock.db.migrate before any migration runs.

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

CREATE TABLE versions (
  dataset_id   TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  version      INTEGER NOT NULL,               -- 1 = raw import
  parquet_path TEXT NOT NULL,                  -- relative to the dataset folder
  row_count    INTEGER NOT NULL,
  column_count INTEGER NOT NULL,
  columns_json TEXT NOT NULL,                  -- [{name, type}] in order, after the step
  step_id      TEXT,                           -- the step that produced it (NULL for v1)
  effective_step_ids_json TEXT NOT NULL DEFAULT '[]', -- ordered ids of the steps whose effects make up this version (undone steps removed)
  created_at   TEXT NOT NULL,
  PRIMARY KEY (dataset_id, version)
);

CREATE TABLE datacards (
  dataset_id TEXT NOT NULL,
  version    INTEGER NOT NULL,
  card_json  TEXT NOT NULL,                    -- DataCard
  created_at TEXT NOT NULL,
  PRIMARY KEY (dataset_id, version),
  FOREIGN KEY (dataset_id, version) REFERENCES versions(dataset_id, version) ON DELETE CASCADE
);

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

CREATE TABLE user_edited_cells (
  dataset_id TEXT NOT NULL,
  row_id     INTEGER NOT NULL,
  column     TEXT NOT NULL,
  step_id    TEXT NOT NULL,
  PRIMARY KEY (dataset_id, row_id, column)
) WITHOUT ROWID;

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

CREATE TABLE canvases (
  dataset_id  TEXT PRIMARY KEY REFERENCES datasets(id) ON DELETE CASCADE,
  canvas_json TEXT NOT NULL,                   -- JSON Canvas document
  etag        TEXT NOT NULL,                   -- sha1 of canvas_json
  updated_at  TEXT NOT NULL
);

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

CREATE TABLE jobs (
  id         TEXT PRIMARY KEY,                 -- job_…
  dataset_id TEXT REFERENCES datasets(id) ON DELETE CASCADE,
  user_id    TEXT NOT NULL,
  kind       TEXT NOT NULL,                    -- profile|clean|build_dashboard|stories|ml_run|cascade|undo|export_notebook|purge
  status     TEXT NOT NULL,                    -- queued|running|done|failed|cancelled
  params_json TEXT NOT NULL DEFAULT '{}',
  state_json TEXT,                             -- checkpoint
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

CREATE TABLE value_index (
  dataset_id TEXT NOT NULL,
  column     TEXT NOT NULL,
  value      TEXT NOT NULL,
  count      INTEGER NOT NULL,
  embedding  BLOB,                             -- float32[] or NULL (sqlite-vec virtual table used when available)
  version    INTEGER NOT NULL,
  PRIMARY KEY (dataset_id, column, value)
) WITHOUT ROWID;

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
