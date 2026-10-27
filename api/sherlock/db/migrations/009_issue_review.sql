-- Severity levels (Schema §2.8, §2.24; PRD CLEAN-8c, CLEAN-6). `issues` records which version of its
-- detector found it and why the Cleaner skipped it; the report counts by `skip_kind`, not by parsing the reason.
ALTER TABLE issues ADD COLUMN detector_version INTEGER;
ALTER TABLE issues ADD COLUMN skip_kind TEXT;      -- kept_by_design|left_as_is|failed_checks|disagreement|gate|model_error|conflict|unticked|needs_choice

-- A version's ratings, kept apart from `issues`, which a re-profile rewrites. Versions never change, so a
-- rating holds until its detector's version does.
CREATE TABLE issue_reviews (
  dataset_id       TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  version          INTEGER NOT NULL,
  key              TEXT NOT NULL,              -- detector|column, as plan.key
  detector_version INTEGER NOT NULL,
  sev              TEXT NOT NULL,              -- breaks|skews|splits|check|cosmetic
  sev_reason       TEXT,
  sev_source       TEXT NOT NULL,              -- model|default
  likely_real      INTEGER NOT NULL DEFAULT 0,
  created_at       TEXT NOT NULL,
  PRIMARY KEY (dataset_id, version, key)
);
