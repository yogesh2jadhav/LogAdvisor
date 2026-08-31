"""Markdown advisory report generation."""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from typing import List

from ..models import Finding, ScanResult

_SECTION_ORDER = ["HIGH", "MEDIUM", "LOW"]


def _finding_block(idx: int, f: Finding) -> str:
    rec = f.recommendation
    lines = [
        f"### {idx}. {f.file}:{f.line}",
        "",
        f"- **Operation:** {f.category}",
        f"- **Class / method:** `{f.class_name}.{f.method}`",
        f"- **Priority:** {f.priority}",
        f"- **Current state:** "
        + ("no logging detected" if not f.existing_logging
           else f"logging present ({f.logging_quality})"),
        f"- **Rule:** `{f.rule_id}`",
        f"- **LLM analysis:** {f.llm_status}",
    ]
    fields = rec.recommended_fields if rec else f.required_fields
    lines.append("- **Recommended structured fields:**")
    for x in fields:
        lines.append(f"  - `{x}`")
    if rec and rec.reason:
        lines += ["", f"**Why:** {rec.reason}"]
    if rec and rec.do_not_log:
        lines += ["", "**Do NOT log:**"] + [f"- {x}" for x in rec.do_not_log]
    if rec:
        lines += ["", f"**Future AI value:** {rec.ai_usefulness}"
                  + (f" — {', '.join(rec.ai_use_cases)}" if rec.ai_use_cases else "")]
    lines.append("")
    return "\n".join(lines)


def _score_table(result: ScanResult) -> str:
    s = result.scores
    rows = [
        ("Job lifecycle", s.job_lifecycle, 15),
        ("Input visibility", s.input_visibility, 15),
        ("Transformation visibility", s.transformation_visibility, 15),
        ("Join visibility", s.join_visibility, 15),
        ("Output visibility", s.output_visibility, 15),
        ("Exception visibility", s.exception_visibility, 10),
        ("Structured logging", s.structured_logging, 10),
        ("Trace / run correlation", s.run_correlation, 5),
    ]
    out = ["| Category | Score | Max |", "| --- | ---: | ---: |"]
    for name, val, mx in rows:
        out.append(f"| {name} | {val} | {mx} |")
    out.append(f"| **Overall** | **{s.overall_score}** | **100** |")
    return "\n".join(out)


def _quality_word(f: Finding) -> str:
    return f.logging_quality


def write_markdown_report(result: ScanResult, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "logging_advisory_report.md")
    p = result.project
    L: List[str] = []
    A = L.append

    A("# AI-Ready Logging Advisory Report")
    A("")
    A("## Executive Summary")
    A("")
    A(f"- Project: **{p.project_name}**")
    A(f"- Files scanned: {result.files_scanned}")
    A(f"- Methods analyzed: {result.methods_scanned}")
    A(f"- Spark operations detected: {result.spark_operations}")
    A(f"- Existing logging statements: {result.existing_logs}")
    A(f"- Potential logging gaps (findings): {len(result.findings)}")
    A(f"- AI Observability Score: **{result.scores.overall_score}/100**")
    A(f"- LLM analysis: {'enabled (' + str(result.llm_model) + ')' if result.llm_enabled else 'disabled (--no-llm)'}"
      f" — calls={result.llm_calls}, failures={result.llm_failures}, cache_hits={result.cache_hits}")
    A("")

    A("## Project Information")
    A("")
    A(f"- Language: {p.language}")
    A(f"- Frameworks: {', '.join(p.frameworks) or 'n/a'}")
    A(f"- Build system: {p.build_system or 'unknown'}")
    A(f"- Java version: {p.java_version or 'unknown'}")
    A(f"- Spark version: {p.spark_version or 'unknown'}")
    A(f"- Logging frameworks: {', '.join(p.logging_frameworks) or 'unknown'}")
    A("")

    A("## AI Observability Score")
    A("")
    A(_score_table(result))
    A("")
    A("> The score is deterministic. It is **not** produced by the LLM.")
    A("")

    counts = Counter(f.priority for f in result.findings)
    titles = {"HIGH": "Critical / High Priority Recommendations",
              "MEDIUM": "Medium Priority Recommendations",
              "LOW": "Low Priority Recommendations"}
    for prio in _SECTION_ORDER:
        A(f"## {titles[prio]}")
        A("")
        items = result.by_priority(prio)
        if not items:
            A("_None._")
            A("")
            continue
        A(f"_{len(items)} finding(s)._")
        A("")
        for i, f in enumerate(items, 1):
            A(_finding_block(i, f))

    A("## Existing Logging Analysis")
    A("")
    all_logs = [s for cf in result.files for m in cf.methods for s in m.logging_statements]
    qc = Counter(s.level for s in all_logs)
    A(f"- Total statements: {len(all_logs)}")
    A(f"- By level: {dict(qc) or 'n/a'}")
    A(f"- Structured: {sum(1 for s in all_logs if s.structured)} / {len(all_logs)}")
    sens = [(cf.path, s) for cf in result.files for m in cf.methods for s in m.logging_statements if s.sensitive]
    if sens:
        A(f"- ⚠️  Potentially sensitive logging statements: {len(sens)}")
        for pth, s in sens[:25]:
            A(f"  - {pth}:{s.line} — `{s.message_pattern}`")
    A("")

    A("## Spark Pipeline Analysis")
    A("")
    op_counts = Counter(op.operation_type for cf in result.files for m in cf.methods for op in m.spark_operations)
    for op, n in op_counts.most_common():
        A(f"- {op}: {n}")
    A("")

    A("## Parquet Output Analysis")
    A("")
    writes = [f for f in result.findings if f.category in ("DATASET_WRITE", "PARQUET_WRITE")]
    A(f"- Output findings: {len(writes)}")
    for f in writes:
        A(f"  - {f.file}:{f.line} — {f.logging_quality}")
    A("")
    A("> Never log actual data values on output — log counts, paths, durations, status only.")
    A("")

    A("## Exception Handling Analysis")
    A("")
    exc = [f for f in result.findings if f.category == "EXCEPTION"]
    A(f"- Catch blocks without error logging: {len(exc)}")
    for f in exc:
        A(f"  - {f.file}:{f.line} in `{f.class_name}.{f.method}`")
    A("")

    A("## Recommended Logging Contract")
    A("")
    A("See `logadvisor/rules/logging_rules.yaml` (configurable). Key operations:")
    A("")
    A("| Operation | Priority | Required fields |")
    A("| --- | --- | --- |")
    seen = set()
    for f in result.findings:
        if f.category in seen:
            continue
        seen.add(f.category)
        A(f"| {f.category} | {f.priority} | {', '.join(f.required_fields)} |")
    A("")

    A("## AI / RCA Readiness")
    A("")
    A("Structured logs from the operations above enable future local-LLM assisted:")
    A("")
    A("- anomaly detection on record-flow (counts before/after joins, filters)")
    A("- root-cause analysis (which stage / operation failed, with duration)")
    A("- run-over-run comparison (why did output records change vs yesterday)")
    A("")

    A("## Files Requiring Attention")
    A("")
    by_file = defaultdict(list)
    for f in result.findings:
        by_file[f.file].append(f)
    ranked = sorted(by_file.items(),
                    key=lambda kv: -sum({"HIGH": 3, "MEDIUM": 2, "LOW": 1}[x.priority] for x in kv[1]))
    A("| File | HIGH | MEDIUM | LOW | Existing logs |")
    A("| --- | ---: | ---: | ---: | ---: |")
    for fp, fs in ranked[:40]:
        c = Counter(x.priority for x in fs)
        cf = next((x for x in result.files if x.path == fp), None)
        nlogs = sum(len(m.logging_statements) for m in cf.methods) if cf else 0
        A(f"| {fp} | {c['HIGH']} | {c['MEDIUM']} | {c['LOW']} | {nlogs} |")
    A("")

    A("## Method-Level Summary")
    A("")
    A("Highest-risk methods (operations detected vs. observability captured):")
    A("")
    finding_methods = {(f.file, f.class_name, f.method) for f in result.findings}
    ranked_methods = []
    for cf in result.files:
        for m in cf.methods:
            key = (cf.path, m.class_name, m.name)
            if key not in finding_methods:
                continue
            mf = [f for f in result.findings
                  if f.file == cf.path and f.class_name == m.class_name and f.method == m.name]
            weight = sum({"HIGH": 3, "MEDIUM": 2, "LOW": 1}[f.priority] for f in mf)
            ranked_methods.append((weight, cf, m, mf))
    ranked_methods.sort(key=lambda t: -t[0])
    op_types = {"input": {"DATASET_READ", "PARQUET_READ"}, "join": {"JOIN"},
                "filter": {"FILTER"}, "aggregation": {"GROUP_BY", "AGGREGATION"},
                "output": {"DATASET_WRITE", "PARQUET_WRITE"}}
    for weight, cf, m, mf in ranked_methods[:20]:
        present = {op.operation_type for op in m.spark_operations}
        checks = []
        for label, cats in op_types.items():
            if present & cats:
                checks.append(f"✓ {label}")
        checks.append(("✓" if any(s.structured for s in m.logging_statements) else "✗") + " structured logging")
        checks.append(("✓" if m.logging_statements else "✗") + " logging")
        A(f"### `{m.class_name}.{m.name}()` — {cf.path}:{m.start_line}")
        A("")
        A(f"- Risk weight: {weight}  ·  findings: "
          + ", ".join(f"{f.category}@{f.line}" for f in mf))
        A(f"- {'  '.join(checks)}")
        A("")

    A("## Appendix")
    A("")
    A(f"- Scanner version: see `logadvisor.SCANNER_VERSION`")
    A(f"- Rule version: {result.findings[0].rule_id.split('@')[-1] if result.findings else 'n/a'}")
    A(f"- Scan id: {result.scan_id}")
    A("")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    return path
