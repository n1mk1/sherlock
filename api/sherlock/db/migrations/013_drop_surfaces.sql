-- Cuts 10 to 12 (plan §5): the dashboard, the story cards and the Flow canvas are gone, so are their
-- tables (Schema §2.9, §2.11, §2.12). A dataset that was building its dashboard is ready; its surface
-- jobs stop; a remembered Dashboard or Flow tab opens the CSV view.
UPDATE datasets SET status = 'ready' WHERE status = 'building';
UPDATE datasets SET last_tab = 'csv' WHERE last_tab IN ('dashboard', 'flow');
UPDATE jobs SET status = 'cancelled', error = 'Removed by cut 10.', finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
  WHERE kind IN ('build_dashboard', 'stories', 'cascade') AND status IN ('queued', 'running');

DROP TABLE widgets;
DROP TABLE layouts;
DROP TABLE widget_cache;
DROP TABLE relations;
DROP TABLE cards;
DROP TABLE canvases;

-- Fact sheets are kept for ML runs only (Schema §2.10).
DELETE FROM fact_sheets WHERE run_id IS NULL;
DROP INDEX fact_sheets_widget;
ALTER TABLE fact_sheets DROP COLUMN widget_id;
CREATE INDEX fact_sheets_run ON fact_sheets(run_id);
ALTER TABLE runs DROP COLUMN widget_id;
