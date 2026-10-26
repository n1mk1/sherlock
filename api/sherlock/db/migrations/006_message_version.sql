-- The version a chat message read (Schema §2.15, plan 2b.4): an answer's numbers are from this version, so
-- history, Add to Flow and the thread can tell an answer from an older version. Messages written before this
-- migration get the version that was current when they were written (versions only ever go up: an undo is a
-- new version too).
ALTER TABLE messages ADD COLUMN version INTEGER;
UPDATE messages SET version = (
  SELECT max(v.version) FROM versions v WHERE v.dataset_id = messages.dataset_id AND v.created_at <= messages.created_at
);
