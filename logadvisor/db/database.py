"""SQLite persistence layer.

Local developer data only. The database is created / migrated automatically and
stores code-analysis metadata: never patient data, never full source code.
"""
from __future__ import annotations

import glob
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .. import RULE_VERSION, SCANNER_VERSION
from ..models import ScanResult

_MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    # -- migrations -----------------------------------------------------
    def _migrate(self) -> None:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {r["name"] for r in self.conn.execute("SELECT name FROM schema_migrations")}
        for sql_file in sorted(glob.glob(os.path.join(_MIGRATIONS_DIR, "*.sql"))):
            name = os.path.basename(sql_file)
            if name in applied:
                continue
            with open(sql_file, "r", encoding="utf-8") as fh:
                self.conn.executescript(fh.read())
            self.conn.execute(
                "INSERT INTO schema_migrations(name, applied_at) VALUES (?, ?)",
                (name, _now()),
            )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- persistence --------------------------------------------------
    def _upsert_project(self, result: ScanResult) -> int:
        p = result.project
        cur = self.conn.execute("SELECT id FROM projects WHERE path = ?", (p.path,))
        row = cur.fetchone()
        now = _now()
        lf = ", ".join(p.logging_frameworks)
        if row:
            pid = row["id"]
            self.conn.execute(
                "UPDATE projects SET name=?, language=?, java_version=?, spark_version=?, "
                "build_system=?, logging_framework=?, updated_at=? WHERE id=?",
                (p.project_name, p.language, p.java_version, p.spark_version,
                 p.build_system, lf, now, pid),
            )
            return pid
        cur = self.conn.execute(
            "INSERT INTO projects(name, path, language, java_version, spark_version, "
            "build_system, logging_framework, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (p.project_name, p.path, p.language, p.java_version, p.spark_version,
             p.build_system, lf, now, now),
        )
        return cur.lastrowid

    def save_scan(self, result: ScanResult) -> int:
        c = self.conn
        pid = self._upsert_project(result)
        started = _now()
        cur = c.execute(
            "INSERT INTO scans(project_id, started_at, completed_at, status, files_scanned, "
            "classes_scanned, methods_scanned, spark_operations, existing_logs, findings_count, "
            "llm_enabled, llm_provider, llm_model, ai_observability_score, rule_version, scanner_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, started, _now(), "COMPLETED", result.files_scanned, result.classes_scanned,
             result.methods_scanned, result.spark_operations, result.existing_logs,
             len(result.findings), int(result.llm_enabled), result.llm_provider, result.llm_model,
             result.scores.overall_score, RULE_VERSION, SCANNER_VERSION),
        )
        scan_id = cur.lastrowid
        result.scan_id = scan_id

        s = result.scores
        c.execute(
            "INSERT INTO scores(scan_id, job_lifecycle, input_visibility, transformation_visibility, "
            "join_visibility, output_visibility, exception_visibility, structured_logging, "
            "run_correlation, overall_score) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (scan_id, s.job_lifecycle, s.input_visibility, s.transformation_visibility,
             s.join_visibility, s.output_visibility, s.exception_visibility, s.structured_logging,
             s.run_correlation, s.overall_score),
        )

        file_ids: Dict[str, int] = {}
        method_ids: Dict[int, int] = {}
        for cf in result.files:
            fcur = c.execute(
                "INSERT INTO source_files(scan_id, path, file_hash, language, line_count, "
                "class_count, method_count) VALUES (?,?,?,?,?,?,?)",
                (scan_id, cf.path, cf.file_hash, "Java", cf.line_count,
                 len(cf.classes), len(cf.methods)),
            )
            file_ids[cf.path] = fcur.lastrowid
            for m in cf.methods:
                mcur = c.execute(
                    "INSERT INTO methods(source_file_id, class_name, method_name, start_line, "
                    "end_line, return_type, parameter_count) VALUES (?,?,?,?,?,?,?)",
                    (fcur.lastrowid, m.class_name, m.name, m.start_line, m.end_line,
                     m.return_type, m.parameter_count),
                )
                method_ids[id(m)] = mcur.lastrowid
                for op in m.spark_operations:
                    c.execute(
                        "INSERT INTO spark_operations(method_id, operation_type, line, details, priority) "
                        "VALUES (?,?,?,?,?)",
                        (mcur.lastrowid, op.operation_type, op.line, op.snippet[:200], op.priority),
                    )
                for lg in m.logging_statements:
                    c.execute(
                        "INSERT INTO existing_logs(method_id, line, level, logger_type, "
                        "message_pattern, structured, sensitive) VALUES (?,?,?,?,?,?,?)",
                        (mcur.lastrowid, lg.line, lg.level, lg.logger_type,
                         lg.message_pattern[:300], int(lg.structured), int(lg.sensitive)),
                    )

        for f in result.findings:
            fid = c.execute(
                "INSERT INTO findings(scan_id, source_file_id, method_id, fingerprint, category, "
                "operation, line, priority, existing_logging, logging_quality, required_fields, "
                "rule_id, llm_status, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (scan_id, file_ids.get(f.file), None, f.fingerprint, f.category, f.category,
                 f.line, f.priority, int(f.existing_logging), f.logging_quality,
                 json.dumps(f.required_fields), f.rule_id, f.llm_status,
                 self._carry_status(pid, f.fingerprint)),
            ).lastrowid
            if f.recommendation is not None:
                r = f.recommendation
                c.execute(
                    "INSERT INTO recommendations(finding_id, recommend, priority, reason, "
                    "recommended_fields, do_not_log, ai_usefulness, ai_use_cases, model, "
                    "prompt_version, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (fid, int(r.recommend), r.priority, r.reason,
                     json.dumps(r.recommended_fields), json.dumps(r.do_not_log),
                     r.ai_usefulness, json.dumps(r.ai_use_cases), r.model,
                     r.prompt_version, _now()),
                )
            c.execute(
                "INSERT INTO llm_runs(scan_id, finding_id, provider, model, status, cache_hit) "
                "VALUES (?,?,?,?,?,?)",
                (scan_id, fid, result.llm_provider, result.llm_model, f.llm_status,
                 int(f.llm_status == "CACHE_HIT")),
            )
        c.commit()
        return scan_id

    def _carry_status(self, project_id: int, fingerprint: str) -> str:
        """If a prior scan of this project marked the same finding
        ACCEPTED/REJECTED/FALSE_POSITIVE, carry that forward."""
        if not fingerprint:
            return "OPEN"
        row = self.conn.execute(
            "SELECT f.status FROM findings f JOIN scans s ON f.scan_id = s.id "
            "WHERE s.project_id = ? AND f.fingerprint = ? "
            "AND f.status IN ('ACCEPTED','REJECTED','FALSE_POSITIVE') "
            "ORDER BY f.id DESC LIMIT 1",
            (project_id, fingerprint),
        ).fetchone()
        return row["status"] if row else "OPEN"

    # -- queries -----------------------------------------------------
    def history(self, limit: int = 50) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT s.id, s.started_at, s.ai_observability_score AS score, s.findings_count, "
            "s.llm_model, p.name AS project FROM scans s JOIN projects p ON s.project_id = p.id "
            "ORDER BY s.id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def scan_row(self, scan_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()

    def priority_counts(self, scan_id: int) -> Dict[str, int]:
        rows = self.conn.execute(
            "SELECT priority, COUNT(*) c FROM findings WHERE scan_id = ? GROUP BY priority",
            (scan_id,),
        ).fetchall()
        return {r["priority"]: r["c"] for r in rows}

    def set_finding_status(self, finding_id: int, status: str) -> bool:
        cur = self.conn.execute(
            "UPDATE findings SET status = ? WHERE id = ?", (status, finding_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_findings(self, scan_id: Optional[int] = None, priority: Optional[str] = None):
        q = ("SELECT f.*, sf.path AS file_path FROM findings f "
             "LEFT JOIN source_files sf ON f.source_file_id = sf.id WHERE 1=1")
        args: List[Any] = []
        if scan_id is None:
            q += " AND f.scan_id = (SELECT MAX(id) FROM scans)"
        else:
            q += " AND f.scan_id = ?"
            args.append(scan_id)
        if priority:
            q += " AND f.priority = ?"
            args.append(priority.upper())
        q += " ORDER BY CASE f.priority WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, f.id"
        return self.conn.execute(q, args).fetchall()
