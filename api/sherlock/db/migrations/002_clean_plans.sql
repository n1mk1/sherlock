-- Cleaning plans (Schema §2.21, PRD CLEAN-8a): what Clean with AI will try, editable before it starts.
CREATE TABLE clean_plans (
  id         TEXT PRIMARY KEY,                 -- pln_…
  dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  version    INTEGER NOT NULL,                 -- the version the items were diagnosed on
  items_json TEXT NOT NULL,                    -- [PlanItem] (TRD §4.4)
  status     TEXT NOT NULL,                    -- draft|started|discarded
  source     TEXT NOT NULL,                    -- user|after_upload (who opened it)
  job_id     TEXT,                             -- the clean job a started plan ran as
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX clean_plans_one_draft ON clean_plans(dataset_id) WHERE status = 'draft';
