-- AI-Ready Logging Advisor - initial schema.
-- Stores code-analysis metadata ONLY. Never patient data, never source dumps.

CREATE TABLE IF NOT EXISTS projects (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    path              TEXT NOT NULL UNIQUE,
    language          TEXT,
    java_version      TEXT,
    spark_version     TEXT,
    build_system      TEXT,
    logging_framework TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scans (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id            INTEGER NOT NULL REFERENCES projects(id),
    started_at            TEXT NOT NULL,
    completed_at          TEXT,
    status                TEXT NOT NULL,
    files_scanned         INTEGER DEFAULT 0,
    classes_scanned       INTEGER DEFAULT 0,
    methods_scanned       INTEGER DEFAULT 0,
    spark_operations      INTEGER DEFAULT 0,
    existing_logs         INTEGER DEFAULT 0,
    findings_count        INTEGER DEFAULT 0,
    llm_enabled           INTEGER DEFAULT 0,
    llm_provider          TEXT,
    llm_model             TEXT,
    ai_observability_score REAL,
    rule_version          TEXT,
    scanner_version       TEXT
);
CREATE INDEX IF NOT EXISTS idx_scans_project_id ON scans(project_id);

CREATE TABLE IF NOT EXISTS source_files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id      INTEGER NOT NULL REFERENCES scans(id),
    path         TEXT NOT NULL,
    file_hash    TEXT NOT NULL,
    language     TEXT,
    line_count   INTEGER,
    class_count  INTEGER,
    method_count INTEGER
);
CREATE INDEX IF NOT EXISTS idx_source_files_scan_id ON source_files(scan_id);

CREATE TABLE IF NOT EXISTS methods (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file_id  INTEGER NOT NULL REFERENCES source_files(id),
    class_name      TEXT,
    method_name     TEXT,
    start_line      INTEGER,
    end_line        INTEGER,
    return_type     TEXT,
    parameter_count INTEGER
);
CREATE INDEX IF NOT EXISTS idx_methods_source_file_id ON methods(source_file_id);

CREATE TABLE IF NOT EXISTS spark_operations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    method_id      INTEGER NOT NULL REFERENCES methods(id),
    operation_type TEXT,
    line           INTEGER,
    details        TEXT,
    priority       TEXT
);
CREATE INDEX IF NOT EXISTS idx_spark_operations_method_id ON spark_operations(method_id);

CREATE TABLE IF NOT EXISTS existing_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    method_id       INTEGER NOT NULL REFERENCES methods(id),
    line            INTEGER,
    level           TEXT,
    logger_type     TEXT,
    message_pattern TEXT,
    structured      INTEGER DEFAULT 0,
    sensitive       INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_existing_logs_method_id ON existing_logs(method_id);

CREATE TABLE IF NOT EXISTS findings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id         INTEGER NOT NULL REFERENCES scans(id),
    source_file_id  INTEGER REFERENCES source_files(id),
    method_id       INTEGER REFERENCES methods(id),
    fingerprint     TEXT,
    category        TEXT,
    operation       TEXT,
    line            INTEGER,
    priority        TEXT,
    existing_logging INTEGER DEFAULT 0,
    logging_quality TEXT,
    required_fields TEXT,
    rule_id         TEXT,
    llm_status      TEXT,
    status          TEXT DEFAULT 'OPEN'
);
CREATE INDEX IF NOT EXISTS idx_findings_scan_id ON findings(scan_id);
CREATE INDEX IF NOT EXISTS idx_findings_priority ON findings(priority);
CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status);
CREATE INDEX IF NOT EXISTS idx_findings_source_file_id ON findings(source_file_id);
CREATE INDEX IF NOT EXISTS idx_findings_fingerprint ON findings(fingerprint);

CREATE TABLE IF NOT EXISTS recommendations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id        INTEGER NOT NULL REFERENCES findings(id),
    recommend         INTEGER DEFAULT 1,
    priority          TEXT,
    reason            TEXT,
    recommended_fields TEXT,
    do_not_log        TEXT,
    ai_usefulness     TEXT,
    ai_use_cases      TEXT,
    model             TEXT,
    prompt_version    TEXT,
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recommendations_finding_id ON recommendations(finding_id);

CREATE TABLE IF NOT EXISTS llm_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id       INTEGER NOT NULL REFERENCES scans(id),
    finding_id    INTEGER REFERENCES findings(id),
    provider      TEXT,
    model         TEXT,
    started_at    TEXT,
    completed_at  TEXT,
    duration_ms   INTEGER,
    status        TEXT,
    cache_hit     INTEGER DEFAULT 0,
    error_type    TEXT,
    prompt_hash   TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_runs_scan_id ON llm_runs(scan_id);

CREATE TABLE IF NOT EXISTS scores (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id                   INTEGER NOT NULL REFERENCES scans(id),
    job_lifecycle             REAL,
    input_visibility          REAL,
    transformation_visibility REAL,
    join_visibility           REAL,
    output_visibility         REAL,
    exception_visibility      REAL,
    structured_logging        REAL,
    run_correlation           REAL,
    overall_score             REAL
);
CREATE INDEX IF NOT EXISTS idx_scores_scan_id ON scores(scan_id);
