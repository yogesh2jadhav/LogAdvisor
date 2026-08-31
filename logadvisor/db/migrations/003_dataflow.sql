-- Lazy-evaluation analysis + LLM cache index.

ALTER TABLE spark_operations ADD COLUMN is_action INTEGER DEFAULT 0;
ALTER TABLE spark_operations ADD COLUMN lazy INTEGER DEFAULT 0;
ALTER TABLE spark_operations ADD COLUMN materialized_at INTEGER;

ALTER TABLE findings ADD COLUMN execution_line INTEGER;

CREATE TABLE IF NOT EXISTS llm_cache (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id        INTEGER REFERENCES scans(id),
    finding_id     INTEGER REFERENCES findings(id),
    cache_key      TEXT NOT NULL,
    model          TEXT,
    prompt_version TEXT,
    rule_id        TEXT,
    response_path  TEXT,
    hit            INTEGER DEFAULT 0,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_cache_key ON llm_cache(cache_key);
CREATE INDEX IF NOT EXISTS idx_llm_cache_scan ON llm_cache(scan_id);
