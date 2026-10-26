-- Receipts (Schema §2.18, TRD §4.9, §4.10): "How I worked it out" reads a chat message's or a job's
-- calls, and the app-wide budget sums the calls since midnight UTC before every model call.
-- `cached` is 1 for a call answered from a cache with no request sent (the web client's rows,
-- role 'web'); every Nemotron call is 0.
ALTER TABLE llm_calls ADD COLUMN cached INTEGER NOT NULL DEFAULT 0;
CREATE INDEX llm_calls_message ON llm_calls(message_id);
CREATE INDEX llm_calls_job ON llm_calls(job_id);
CREATE INDEX llm_calls_created ON llm_calls(created_at);
