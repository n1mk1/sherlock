-- A cleaning plan's scope (Schema §2.21, PRD CLEAN-8a): the rows a plan was opened for, from the new-rows
-- toast or chat's "clean these rows". NULL is the whole dataset.
ALTER TABLE clean_plans ADD COLUMN scope_json TEXT;
