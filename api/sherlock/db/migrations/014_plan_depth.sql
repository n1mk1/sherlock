-- A cleaning plan's depth (Schema §2.21, PRD CLEAN-15): the deepest detector layer it lists, 1–5. Plans made
-- before depth existed listed every layer.
ALTER TABLE clean_plans ADD COLUMN depth INTEGER NOT NULL DEFAULT 5;
