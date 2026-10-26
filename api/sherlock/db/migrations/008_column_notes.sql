-- Column notes (Schema §2.23, PRD LOAD-7, TRD §7.1): what a column means, from a data dictionary the user
-- linked or from the web (column meaning). Metadata about the columns, never data: no step, no version.
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
