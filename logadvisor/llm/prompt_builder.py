"""Builds the per-finding LLM context. Never sends the whole repository."""
from __future__ import annotations

from typing import List

from .. import PROMPT_VERSION
from ..models import CodeFile, Finding, Method, ProjectInfo
from ..security import mask_secrets

SYSTEM_PROMPT = (
    "You are a senior data-platform engineer reviewing a Java + Apache Spark "
    "codebase for observability gaps. You advise where STRUCTURED logging should "
    "be added so the pipeline becomes AI-ready for monitoring, anomaly detection "
    "and root-cause analysis.\n"
    "Rules:\n"
    "- Do NOT invent runtime facts. Use 'potentially', 'recommended', 'could help'.\n"
    "- Never recommend logging PHI/PII: patient identifiers, names, demographics, "
    "diagnoses, medications, clinical notes, full request/response bodies, "
    "credentials, tokens or secrets. Recommend metadata (counts, durations, "
    "types, identifiers-of-fields) instead.\n"
    "- Reply with a SINGLE JSON object and nothing else."
)

_SCHEMA_HINT = """Return JSON with exactly these keys:
{
  "recommend": bool,
  "priority": "HIGH" | "MEDIUM" | "LOW",
  "category": string,
  "reason": string,
  "recommended_fields": [string],
  "do_not_log": [string],
  "ai_usefulness": "HIGH" | "MEDIUM" | "LOW",
  "ai_use_cases": [string],
  "deterministic_recommendation_reasonable": bool
}"""


def _snippet_for(method: Method, source_lines: List[str], focus_line: int, ctx: int = 12) -> str:
    lo = max(method.start_line, focus_line - ctx)
    hi = min(method.end_line, focus_line + ctx)
    out = []
    for ln in range(lo, hi + 1):
        if 1 <= ln <= len(source_lines):
            out.append(f"{ln:5d}| {source_lines[ln - 1]}")
    return mask_secrets("\n".join(out))


def build_prompt(project: ProjectInfo, cf: CodeFile, method: Method, finding: Finding,
                 source_text: str) -> str:
    lines = source_text.splitlines()
    detected = sorted({op.operation_type for op in method.spark_operations})
    existing = [
        f"- {s.level} at line {s.line}"
        f"{' (structured)' if s.structured else ' (unstructured)'}"
        f"{' [SENSITIVE?]' if s.sensitive else ''}"
        for s in method.logging_statements
    ] or ["- none in this method"]

    return f"""Project: {project.project_name}
Technology: {project.language}{(' + ' + ', '.join(project.frameworks)) if project.frameworks else ' (no Spark)'}
Logging framework(s): {', '.join(project.logging_frameworks) or 'unknown'}

File: {cf.path}
Class: {method.class_name}
Method: {method.name}({', '.join(method.parameters)}) -> {method.return_type}
Lines: {method.start_line}-{method.end_line}

Deterministic finding:
  category: {finding.category}
  operation line: {finding.line}
  deterministic priority: {finding.priority}
  existing logging near operation: {finding.existing_logging}
  logging quality: {finding.logging_quality}
  execution boundary: {(
      f"line {finding.execution_line} - this transformation is lazy and only "
      f"runs when the Spark action there executes; recommend logging its "
      f"metrics at that action"
  ) if finding.execution_line and finding.execution_line != finding.line else (
      "no Spark action found in this method - the transformation may be "
      "materialized elsewhere" if finding.execution_line is None and finding.category
      not in ("EXCEPTION", "JOB_START", "JOB_COMPLETION") else "runs where defined"
  )}

Detected operations in method: {', '.join(detected) or 'none'}

Existing logging in method:
{chr(10).join(existing)}

Applicable logging rule ({finding.rule_id}) suggests fields:
  {', '.join(finding.required_fields)}

Relevant code (secrets masked):
```java
{_snippet_for(method, lines, finding.line)}
```

Answer these questions, then emit the JSON:
1. Is this candidate logging point important? Why?
2. What structured fields should be logged?
3. What must NOT be logged?
4. Expected AI / RCA usefulness and use-cases?
5. Is the deterministic recommendation reasonable?

{_SCHEMA_HINT}
prompt_version={PROMPT_VERSION}
"""
