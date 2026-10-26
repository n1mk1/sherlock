-- The Nemotron fallback (TRD §3.5, Schema §2.18): a call that Ultra answered in Super's place, because
-- Super's circuit breaker was open or its next retry would have passed the deadline, records the role it
-- stood in for. NULL for every other call.
ALTER TABLE llm_calls ADD COLUMN fallback_from TEXT;
