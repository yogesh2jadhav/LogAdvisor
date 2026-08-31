"""Phases 12-13 - deterministic rule engine / findings engine.

Turns statically-detected Spark operations and exception boundaries into
``Finding`` objects by applying the configurable logging contract in
``logging_rules.yaml``. No LLM involved.
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Dict, List, Optional

import yaml

from ..models import CodeFile, Finding, Method

_DEFAULT_RULES_PATH = os.path.join(os.path.dirname(__file__), "logging_rules.yaml")
_PRIORITY_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


class RuleEngine:
    def __init__(self, rules_path: Optional[str] = None):
        path = rules_path or _DEFAULT_RULES_PATH
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        self.version: str = str(data.get("version", "1"))
        self.proximity: int = int(data.get("proximity_lines", 8))
        self.rules: Dict[str, dict] = data["rules"]
        # spark op -> rule_id
        self._op_index: Dict[str, str] = {}
        for rule_id, spec in self.rules.items():
            for op in spec.get("spark_ops", []):
                self._op_index[op] = rule_id

    # -- helpers ----------------------------------------------------------
    def _nearby_logs(self, method: Method, line: int):
        return [s for s in method.logging_statements if abs(s.line - line) <= self.proximity]

    @staticmethod
    def _quality(logs, required_fields: List[str], snippet: str) -> str:
        if not logs:
            return "MISSING"
        structured = any(s.structured for s in logs)
        if not structured:
            return "WEAK"
        blob = " ".join(s.message_pattern for s in logs).lower()
        hits = sum(1 for f in required_fields if re.sub(r"[^a-z]", "", f.lower()) in re.sub(r"[^a-z]", "", blob))
        if hits >= max(2, len(required_fields) // 2):
            return "GOOD"
        return "PARTIAL"

    @staticmethod
    def _fingerprint(file: str, cls: str, method: str, category: str, rule_id: str, snippet: str) -> str:
        norm = re.sub(r"\s+", "", snippet).lower()
        return hashlib.sha1(
            f"{file}|{cls}|{method}|{category}|{rule_id}|{norm}".encode()
        ).hexdigest()[:16]

    def _finding_from(self, cf: CodeFile, method: Method, category: str, rule_id: str,
                     line: int, det_priority: str, snippet: str) -> Finding:
        spec = self.rules.get(rule_id, {})
        rule_priority = spec.get("priority", "low").upper()
        priority = rule_priority if _PRIORITY_RANK[rule_priority] >= _PRIORITY_RANK.get(det_priority, 0) \
            else det_priority
        logs = self._nearby_logs(method, line)
        required = list(spec.get("fields", []))
        quality = self._quality(logs, required, snippet)
        return Finding(
            category=category,
            file=cf.path,
            class_name=method.class_name,
            method=method.name,
            line=line,
            priority=priority,
            existing_logging=bool(logs),
            logging_quality=quality,
            required_fields=required,
            rule_id=f"{rule_id}@{self.version}",
            snippet=snippet,
            fingerprint=self._fingerprint(cf.path, method.class_name, method.name, category, rule_id, snippet),
        )

    # -- public ---------------------------------------------------------
    def evaluate(self, files: List[CodeFile]) -> List[Finding]:
        findings: List[Finding] = []
        for cf in files:
            if cf.is_test:
                continue
            for method in cf.methods:
                for op in method.spark_operations:
                    rule_id = self._op_index.get(op.operation_type)
                    if not rule_id:
                        continue
                    findings.append(self._finding_from(
                        cf, method, op.operation_type, rule_id, op.line, op.priority, op.snippet
                    ))
                for exc in method.exception_boundaries:
                    if exc.kind != "TRY_CATCH":
                        continue
                    if exc.has_error_logging:
                        continue
                    findings.append(self._finding_from(
                        cf, method, "EXCEPTION", "exception", exc.start_line, "HIGH",
                        f"catch block at line {exc.start_line}",
                    ))
        findings.sort(key=lambda f: (-_PRIORITY_RANK[f.priority], f.file, f.line))
        return findings
