-- Web retrieval (TRD §3.6, Schema §2.22): Tavily responses cached for 24 h. Each Tavily call is an llm_calls
-- row with role 'web' (no tokens, so no token budget counts it) and `cached` (004); `results` is how many
-- results or pages came back.
CREATE TABLE web_cache (
  key           TEXT PRIMARY KEY,              -- sha1 of the kind and the request
  kind          TEXT NOT NULL,                 -- search|extract|map
  request_json  TEXT NOT NULL,                 -- the parameters sent (never a cell value, TRD §3.6)
  response_json TEXT NOT NULL,                 -- Tavily's reply, as received
  created_at    TEXT NOT NULL
);
CREATE INDEX web_cache_created ON web_cache(created_at);
ALTER TABLE llm_calls ADD COLUMN results INTEGER;
