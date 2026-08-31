"""Build the enriched, UI-friendly report document from a ScanResult.

Shape (schema_version 1):

    {
      "schema_version": "1",
      "generated_at": "...",
      "project": {...}, "summary": {...}, "scores": {...}, "llm": {...},
      "rules": { "<rule>": {priority, fields}, ... },
      "files": [                       # full code tree (findings + structure)
        { path, file_hash, line_count, is_test, ai_readiness, risk,
          counts: {HIGH,MEDIUM,LOW},
          classes: [ { name, methods: [ {
              name, class_name, start_line, end_line, return_type,
              parameter_count, risk, ai_readiness,
              detected: { input, join, filter, aggregation, output,
                          structured_logging, exception_context, run_correlation },
              spark_operations: [ {type, line, priority} ],
              existing_logs:    [ {level, line, structured, sensitive} ],
              finding_ids: [int, ...]
          } ] } ] } ],
      "findings": [ { id, ...flat finding..., recommendation: {...} } ]
    }

The flat ``findings`` array is kept for tables; the tree references findings by
``id`` so the two never drift.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, List

from .. import __version__
from ..models import CodeFile, Finding, Method, ScanResult
from ..rules.rule_engine import RuleEngine
from ..scoring import readiness_for, risk_level

SCHEMA_VERSION = "1"

_INPUT = {"DATASET_READ", "PARQUET_READ"}
_OUTPUT = {"DATASET_WRITE", "PARQUET_WRITE"}
_AGG = {"GROUP_BY", "AGGREGATION"}
_RUN_ID_RE = re.compile(r"\b(run[_]?id|correlation[_]?id|trace[_]?id|job[_]?id)\b", re.IGNORECASE)


def _method_owns(method: Method, f: Finding, cf: CodeFile) -> bool:
    return (
        f.file == cf.path
        and f.method == method.name
        and f.class_name == method.class_name
        and method.start_line <= f.line <= method.end_line
    )


def _detected(method: Method) -> Dict[str, bool]:
    op_types = {op.operation_type for op in method.spark_operations}
    logs = method.logging_statements
    excs = method.exception_boundaries
    return {
        "input": bool(op_types & _INPUT),
        "join": "JOIN" in op_types,
        "filter": "FILTER" in op_types,
        "aggregation": bool(op_types & _AGG),
        "output": bool(op_types & _OUTPUT),
        "structured_logging": any(s.structured for s in logs),
        "exception_context": bool(excs) and all(e.has_error_logging for e in excs),
        "run_correlation": any(_RUN_ID_RE.search(s.message_pattern) for s in logs),
    }


def build_report_document(result: ScanResult) -> dict:
    # 1. assign stable ids to the (already priority-sorted) findings
    id_by_obj: Dict[int, int] = {}
    flat_findings: List[dict] = []
    for i, f in enumerate(result.findings, start=1):
        id_by_obj[id(f)] = i
        d = f.to_dict()
        d["id"] = i
        flat_findings.append(d)

    # 2. rules contract
    try:
        engine = RuleEngine()
        rules = {
            name: {"priority": spec.get("priority", "low").upper(),
                   "fields": list(spec.get("fields", [])),
                   "spark_ops": list(spec.get("spark_ops", []))}
            for name, spec in engine.rules.items()
        }
    except Exception:  # noqa: BLE001 - rules file is optional at read time
        rules = {}

    # 3. file / class / method tree
    files_out: List[dict] = []
    for cf in result.files:
        file_findings = [f for f in result.findings if f.file == cf.path]
        classes: Dict[str, List[dict]] = {}
        for method in cf.methods:
            m_findings = [f for f in file_findings if _method_owns(method, f, cf)]
            classes.setdefault(method.class_name, []).append({
                "name": method.name,
                "class_name": method.class_name,
                "start_line": method.start_line,
                "end_line": method.end_line,
                "return_type": method.return_type,
                "parameter_count": method.parameter_count,
                "risk": risk_level(m_findings),
                "ai_readiness": readiness_for(m_findings),
                "detected": _detected(method),
                "spark_operations": [
                    {"type": op.operation_type, "line": op.line, "priority": op.priority,
                     "lazy": op.lazy, "is_action": op.is_action,
                     "materialized_at": op.materialized_at}
                    for op in method.spark_operations
                ],
                "existing_logs": [
                    {"level": s.level, "line": s.line,
                     "structured": s.structured, "sensitive": s.sensitive}
                    for s in method.logging_statements
                ],
                "finding_ids": sorted(id_by_obj[id(f)] for f in m_findings),
            })

        counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for f in file_findings:
            counts[f.priority] += 1

        files_out.append({
            "path": cf.path,
            "file_hash": cf.file_hash,
            "package": cf.package,
            "line_count": cf.line_count,
            "is_test": cf.is_test,
            "ai_readiness": readiness_for(file_findings),
            "risk": risk_level(file_findings),
            "counts": counts,
            "existing_log_count": sum(len(m.logging_statements) for m in cf.methods),
            "classes": [
                {"name": cname, "methods": sorted(ms, key=lambda x: x["start_line"])}
                for cname, ms in sorted(classes.items())
            ],
        })

    # files with findings first, then by risk, then by path
    _risk_ord = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    files_out.sort(key=lambda fo: (
        0 if (fo["counts"]["HIGH"] or fo["counts"]["MEDIUM"] or fo["counts"]["LOW"]) else 1,
        _risk_ord[fo["risk"]], fo["path"],
    ))

    doc = result.to_dict()  # project / scan_id / summary / llm / scores / findings
    try:
        from ..scanner.java_parser import active_backend
        parser_backend = active_backend()
    except Exception:
        parser_backend = "unknown"

    doc.update({
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "advisor_version": __version__,
        "parser_backend": parser_backend,
        "rules": rules,
        "files": files_out,
        "findings": flat_findings,
    })
    return doc
