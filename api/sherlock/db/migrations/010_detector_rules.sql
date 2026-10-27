-- Checks without code (Schema §2.25, PRD CLEAN-13): a dataset's rules, run by the rule detector.
CREATE TABLE detector_rules (
  id          TEXT PRIMARY KEY,                -- rul_…
  user_id     TEXT NOT NULL,
  dataset_id  TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  source      TEXT NOT NULL,                   -- user|suggested|pack
  status      TEXT NOT NULL,                   -- active|suggested|off
  spec_json   TEXT NOT NULL,                   -- {kind, column, params, action, reason?}
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX detector_rules_dataset ON detector_rules(dataset_id);
