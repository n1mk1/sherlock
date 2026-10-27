-- A check of yours for every dataset (Schema §2.25, PRD CLEAN-13): dataset_id NULL. SQLite can't drop a
-- NOT NULL, so the table is rebuilt; a rule now goes with its user too.
CREATE TABLE detector_rules_new (
  id          TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  dataset_id  TEXT REFERENCES datasets(id) ON DELETE CASCADE,   -- NULL: the user's check for every dataset
  source      TEXT NOT NULL,
  status      TEXT NOT NULL,
  spec_json   TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
INSERT INTO detector_rules_new SELECT id, user_id, dataset_id, source, status, spec_json, created_at, updated_at
  FROM detector_rules ORDER BY rowid;
DROP TABLE detector_rules;
ALTER TABLE detector_rules_new RENAME TO detector_rules;
CREATE INDEX detector_rules_dataset ON detector_rules(dataset_id);
CREATE INDEX detector_rules_user ON detector_rules(user_id);
