-- A rating's finding, fingerprinted (Schema §2.24, TRD §7.2): an identical finding of the same dataset
-- later (a re-review, an unchanged issue on a newer version) reuses the rating instead of asking again.
ALTER TABLE issue_reviews ADD COLUMN fingerprint TEXT;   -- sha1 of key, detector version, count, examples, role, type
CREATE INDEX issue_reviews_fingerprint ON issue_reviews(dataset_id, fingerprint);
