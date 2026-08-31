-- Persist enough structure to regenerate reports from the DB (report --scan),
-- link findings to their method, and record real LLM execution metrics.

ALTER TABLE source_files ADD COLUMN package TEXT;

ALTER TABLE methods ADD COLUMN parameters TEXT;    -- JSON array of param declarations
ALTER TABLE methods ADD COLUMN annotations TEXT;   -- JSON array

ALTER TABLE findings ADD COLUMN class_name TEXT;
ALTER TABLE findings ADD COLUMN method_name TEXT;
ALTER TABLE findings ADD COLUMN snippet TEXT;

ALTER TABLE llm_runs ADD COLUMN input_tokens INTEGER DEFAULT 0;
ALTER TABLE llm_runs ADD COLUMN output_tokens INTEGER DEFAULT 0;

CREATE TABLE IF NOT EXISTS exception_boundaries (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    method_id         INTEGER NOT NULL REFERENCES methods(id),
    kind              TEXT,
    start_line        INTEGER,
    end_line          INTEGER,
    has_error_logging INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_exception_boundaries_method_id ON exception_boundaries(method_id);
