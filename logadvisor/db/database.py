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
from ..models import (
    CodeFile, ExceptionBoundary, Finding, LoggingStatement, Method, ProjectInfo,
    Recommendation, ScanResult, Scores, SparkOperation,
)

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
        # file path -> list of (class_name, method_name, start, end, method_db_id)
        method_index: Dict[str, list] = {}
        for cf in result.files:
            fcur = c.execute(
                "INSERT INTO source_files(scan_id, path, file_hash, language, package, line_count, "
                "class_count, method_count) VALUES (?,?,?,?,?,?,?,?)",
                (scan_id, cf.path, cf.file_hash, "Java", cf.package, cf.line_count,
                 len(cf.classes), len(cf.methods)),
            )
            file_ids[cf.path] = fcur.lastrowid
            method_index[cf.path] = []
            for m in cf.methods:
                mcur = c.execute(
                    "INSERT INTO methods(source_file_id, class_name, method_name, start_line, "
                    "end_line, return_type, parameter_count, parameters, annotations) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (fcur.lastrowid, m.class_name, m.name, m.start_line, m.end_line,
                     m.return_type, m.parameter_count, json.dumps(m.parameters),
                     json.dumps(m.annotations)),
                )
                mid = mcur.lastrowid
                method_index[cf.path].append((m.class_name, m.name, m.start_line, m.end_line, mid))
                for op in m.spark_operations:
                    c.execute(
                        "INSERT INTO spark_operations(method_id, operation_type, line, details, priority) "
                        "VALUES (?,?,?,?,?)",
                        (mid, op.operation_type, op.line, op.snippet[:200], op.priority),
                    )
                for lg in m.logging_statements:
                    c.execute(
                        "INSERT INTO existing_logs(method_id, line, level, logger_type, "
                        "message_pattern, structured, sensitive) VALUES (?,?,?,?,?,?,?)",
                        (mid, lg.line, lg.level, lg.logger_type,
                         lg.message_pattern[:300], int(lg.structured), int(lg.sensitive)),
                    )
                for ex in m.exception_boundaries:
                    c.execute(
                        "INSERT INTO exception_boundaries(method_id, kind, start_line, end_line, "
                        "has_error_logging) VALUES (?,?,?,?,?)",
                        (mid, ex.kind, ex.start_line, ex.end_line, int(ex.has_error_logging)),
                    )

        def _method_id_for(f) -> Optional[int]:
            for cls, name, start, end, mid in method_index.get(f.file, []):
                if cls == f.class_name and name == f.method and start <= f.line <= end:
                    return mid
            return None

        finding_ids: Dict[str, int] = {}
        for f in result.findings:
            fid = c.execute(
                "INSERT INTO findings(scan_id, source_file_id, method_id, fingerprint, category, "
                "operation, class_name, method_name, snippet, line, priority, existing_logging, "
                "logging_quality, required_fields, rule_id, llm_status, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (scan_id, file_ids.get(f.file), _method_id_for(f), f.fingerprint, f.category,
                 f.category, f.class_name, f.method, f.snippet, f.line, f.priority,
                 int(f.existing_logging), f.logging_quality, json.dumps(f.required_fields),
                 f.rule_id, f.llm_status, self._carry_status(pid, f.fingerprint)),
            ).lastrowid
            if f.fingerprint:
                finding_ids[f.fingerprint] = fid
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

        # LLM runs: prefer the detailed per-finding records the analyzer produced;
        # fall back to a single status row per finding for --no-llm scans.
        if result.llm_runs:
            for run in result.llm_runs:
                c.execute(
                    "INSERT INTO llm_runs(scan_id, finding_id, provider, model, started_at, "
                    "completed_at, duration_ms, status, input_tokens, output_tokens, cache_hit, "
                    "error_type, prompt_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (scan_id, finding_ids.get(run.get("fingerprint", "")),
                     run.get("provider"), run.get("model"), run.get("started_at"),
                     run.get("completed_at"), run.get("duration_ms", 0), run.get("status"),
                     run.get("input_tokens", 0), run.get("output_tokens", 0),
                     run.get("cache_hit", 0), run.get("error_type"), run.get("prompt_hash")),
                )
        elif result.llm_enabled:
            for f in result.findings:
                c.execute(
                    "INSERT INTO llm_runs(scan_id, finding_id, provider, model, status, cache_hit) "
                    "VALUES (?,?,?,?,?,?)",
                    (scan_id, finding_ids.get(f.fingerprint or ""), result.llm_provider,
                     result.llm_model, f.llm_status, int(f.llm_status == "CACHE_HIT")),
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

    def latest_scan_id(self) -> Optional[int]:
        row = self.conn.execute("SELECT MAX(id) AS id FROM scans").fetchone()
        return row["id"] if row and row["id"] is not None else None

    def llm_run_stats(self, scan_id: int) -> Dict[str, Any]:
        rows = self.conn.execute(
            "SELECT status, cache_hit, duration_ms, input_tokens, output_tokens "
            "FROM llm_runs WHERE scan_id = ?", (scan_id,),
        ).fetchall()
        timed = [r["duration_ms"] for r in rows if not r["cache_hit"] and r["duration_ms"]]
        return {
            "runs": len(rows),
            "ok": sum(1 for r in rows if r["status"] == "OK"),
            "failed": sum(1 for r in rows if r["status"] == "LLM_ANALYSIS_FAILED"),
            "cache_hits": sum(1 for r in rows if r["cache_hit"]),
            "avg_ms": round(sum(timed) / len(timed), 1) if timed else 0.0,
            "input_tokens": sum(r["input_tokens"] or 0 for r in rows),
            "output_tokens": sum(r["output_tokens"] or 0 for r in rows),
        }

    def get_finding(self, finding_id: int) -> Optional[Dict[str, Any]]:
        f = self.conn.execute(
            "SELECT f.*, sf.path AS file_path, s.project_id AS project_id "
            "FROM findings f LEFT JOIN source_files sf ON f.source_file_id = sf.id "
            "JOIN scans s ON f.scan_id = s.id WHERE f.id = ?", (finding_id,),
        ).fetchone()
        if not f:
            return None
        rec = self.conn.execute(
            "SELECT * FROM recommendations WHERE finding_id = ? ORDER BY id DESC LIMIT 1",
            (finding_id,),
        ).fetchone()
        run = self.conn.execute(
            "SELECT * FROM llm_runs WHERE finding_id = ? ORDER BY id DESC LIMIT 1",
            (finding_id,),
        ).fetchone()
        out = dict(f)
        out["recommendation"] = dict(rec) if rec else None
        out["llm_run"] = dict(run) if run else None
        return out

    def load_scan_result(self, scan_id: int) -> Optional[ScanResult]:
        """Rebuild a ScanResult from persisted rows so reports can be regenerated
        without re-scanning the repository."""
        srow = self.conn.execute(
            "SELECT s.*, p.name AS p_name, p.path AS p_path, p.language AS p_lang, "
            "p.java_version, p.spark_version, p.build_system, p.logging_framework "
            "FROM scans s JOIN projects p ON s.project_id = p.id WHERE s.id = ?", (scan_id,),
        ).fetchone()
        if not srow:
            return None

        project = ProjectInfo(
            project_name=srow["p_name"], path=srow["p_path"], language=srow["p_lang"] or "Java",
            frameworks=["Apache Spark"] if srow["spark_version"] else [],
            build_system=srow["build_system"], java_version=srow["java_version"],
            spark_version=srow["spark_version"],
            logging_frameworks=[x.strip() for x in (srow["logging_framework"] or "").split(",") if x.strip()],
        )

        scrow = self.conn.execute("SELECT * FROM scores WHERE scan_id = ?", (scan_id,)).fetchone()
        scores = Scores(**{k: scrow[k] for k in (
            "job_lifecycle", "input_visibility", "transformation_visibility", "join_visibility",
            "output_visibility", "exception_visibility", "structured_logging", "run_correlation",
            "overall_score")}) if scrow else Scores()

        files: List[CodeFile] = []
        for frow in self.conn.execute(
            "SELECT * FROM source_files WHERE scan_id = ? ORDER BY path", (scan_id,)
        ).fetchall():
            cf = CodeFile(path=frow["path"], file_hash=frow["file_hash"],
                          package=frow["package"], line_count=frow["line_count"] or 0,
                          is_test="/src/test/" in frow["path"].replace("\\", "/"))
            for mrow in self.conn.execute(
                "SELECT * FROM methods WHERE source_file_id = ? ORDER BY start_line", (frow["id"],)
            ).fetchall():
                m = Method(
                    name=mrow["method_name"], class_name=mrow["class_name"],
                    start_line=mrow["start_line"], end_line=mrow["end_line"],
                    return_type=mrow["return_type"] or "void",
                    parameters=json.loads(mrow["parameters"] or "[]"),
                    annotations=json.loads(mrow["annotations"] or "[]"),
                )
                m.spark_operations = [
                    SparkOperation(o["operation_type"], o["line"], o["details"] or "", o["priority"])
                    for o in self.conn.execute(
                        "SELECT * FROM spark_operations WHERE method_id = ? ORDER BY line", (mrow["id"],))
                ]
                m.logging_statements = [
                    LoggingStatement(l["line"], l["level"], l["logger_type"] or "unknown",
                                     l["message_pattern"] or "", bool(l["structured"]), bool(l["sensitive"]))
                    for l in self.conn.execute(
                        "SELECT * FROM existing_logs WHERE method_id = ? ORDER BY line", (mrow["id"],))
                ]
                m.exception_boundaries = [
                    ExceptionBoundary(e["kind"], e["start_line"], e["end_line"], bool(e["has_error_logging"]))
                    for e in self.conn.execute(
                        "SELECT * FROM exception_boundaries WHERE method_id = ? ORDER BY start_line", (mrow["id"],))
                ]
                cf.methods.append(m)
                if m.class_name and m.class_name not in cf.classes and not m.class_name.startswith("<"):
                    cf.classes.append(m.class_name)
            files.append(cf)

        findings: List[Finding] = []
        for r in self.conn.execute(
            "SELECT f.*, sf.path AS file_path FROM findings f "
            "LEFT JOIN source_files sf ON f.source_file_id = sf.id "
            "WHERE f.scan_id = ? ORDER BY f.id", (scan_id,)
        ).fetchall():
            fd = Finding(
                category=r["category"], file=r["file_path"] or "", class_name=r["class_name"] or "",
                method=r["method_name"] or "", line=r["line"] or 0, priority=r["priority"],
                existing_logging=bool(r["existing_logging"]), logging_quality=r["logging_quality"] or "MISSING",
                required_fields=json.loads(r["required_fields"] or "[]"), rule_id=r["rule_id"] or "",
                snippet=r["snippet"] or "", status=r["status"] or "OPEN",
                llm_status=r["llm_status"] or "NOT_RUN", fingerprint=r["fingerprint"] or "",
            )
            rec = self.conn.execute(
                "SELECT * FROM recommendations WHERE finding_id = ? ORDER BY id DESC LIMIT 1", (r["id"],)
            ).fetchone()
            if rec:
                fd.recommendation = Recommendation(
                    recommend=bool(rec["recommend"]), priority=rec["priority"] or fd.priority,
                    category=fd.category, reason=rec["reason"] or "",
                    recommended_fields=json.loads(rec["recommended_fields"] or "[]"),
                    do_not_log=json.loads(rec["do_not_log"] or "[]"),
                    ai_usefulness=rec["ai_usefulness"] or "MEDIUM",
                    ai_use_cases=json.loads(rec["ai_use_cases"] or "[]"),
                    model=rec["model"] or "", prompt_version=rec["prompt_version"] or "",
                )
            findings.append(fd)

        stats = self.llm_run_stats(scan_id)
        return ScanResult(
            project=project, files=files, findings=findings, scores=scores,
            llm_enabled=bool(srow["llm_enabled"]), llm_provider=srow["llm_provider"],
            llm_model=srow["llm_model"], scan_id=scan_id,
            llm_calls=stats["ok"] + stats["failed"], llm_failures=stats["failed"],
            cache_hits=stats["cache_hits"],
        )

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
