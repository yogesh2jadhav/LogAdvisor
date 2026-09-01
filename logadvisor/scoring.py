"""AI-readiness scoring (deterministic - never produced by the LLM).

Category weights (total 100):
    Job lifecycle          15
    Input visibility       15
    Transformation         15
    Join visibility        15
    Output visibility      15
    Exception visibility   10
    Structured logging     10
    Trace/run correlation   5
"""
from __future__ import annotations

import re
from typing import Dict, List

from .models import CodeFile, Finding, Scores

_WEIGHTS = {
    "job_lifecycle": 15,
    "input_visibility": 15,
    "transformation_visibility": 15,
    "join_visibility": 15,
    "output_visibility": 15,
    "exception_visibility": 10,
    "structured_logging": 10,
    "run_correlation": 5,
}

# which finding categories feed which score bucket
_BUCKET = {
    "job_lifecycle": {"JOB_START", "JOB_COMPLETION"},
    "input_visibility": {"DATASET_READ", "PARQUET_READ"},
    "transformation_visibility": {"FILTER", "GROUP_BY", "AGGREGATION", "DEDUPLICATION",
                                  "MAP", "REPARTITION", "SELECT", "WITH_COLUMN", "SORT", "UNION"},
    "join_visibility": {"JOIN"},
    "output_visibility": {"DATASET_WRITE", "PARQUET_WRITE", "EXTERNAL_IO"},
    "exception_visibility": {"EXCEPTION"},
}

# buckets that only make sense for a Spark data pipeline
_SPARK_ONLY_BUCKETS = {
    "job_lifecycle", "input_visibility", "transformation_visibility", "join_visibility",
}

_RUN_ID_RE = re.compile(r"\b(run[_]?id|correlation[_]?id|trace[_]?id|jobId|job_id)\b", re.IGNORECASE)


def _covered(f: Finding) -> bool:
    """A finding's operation is considered 'covered' when it already has at least
    PARTIAL-quality logging."""
    return f.existing_logging and f.logging_quality in ("PARTIAL", "GOOD")


# public alias - used by the report / tree builder
def finding_covered(f: Finding) -> bool:
    return _covered(f)


_RISK_WEIGHT = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


def readiness_for(findings: List[Finding]) -> float:
    """0-100 readiness for an arbitrary set of findings (method or file scope).

    Weighted by priority so an uncovered HIGH hurts more than an uncovered LOW.
    Returns 100.0 when there are no findings (nothing to instrument)."""
    if not findings:
        return 100.0
    total = sum(_RISK_WEIGHT[f.priority] for f in findings)
    got = sum(_RISK_WEIGHT[f.priority] for f in findings if _covered(f))
    return round(100.0 * got / total, 1)


def risk_level(findings: List[Finding]) -> str:
    if any(f.priority == "HIGH" and not _covered(f) for f in findings):
        return "HIGH"
    if any(f.priority == "MEDIUM" and not _covered(f) for f in findings):
        return "MEDIUM"
    return "LOW"


def compute_scores(files: List[CodeFile], findings: List[Finding],
                   project_type: str = "java-spark") -> Scores:
    scores = Scores()
    if project_type == "java":
        scores.not_applicable = sorted(_SPARK_ONLY_BUCKETS)

    for bucket, cats in _BUCKET.items():
        relevant = [f for f in findings if f.category in cats]
        weight = _WEIGHTS[bucket]
        if not relevant:
            # no such operations in the codebase -> not a gap, award full marks
            setattr(scores, bucket, float(weight))
            continue
        ratio = sum(1 for f in relevant if _covered(f)) / len(relevant)
        setattr(scores, bucket, round(weight * ratio, 1))

    # structured logging: fraction of all existing logs that are structured
    all_logs = [s for cf in files for m in cf.methods for s in m.logging_statements]
    if all_logs:
        ratio = sum(1 for s in all_logs if s.structured) / len(all_logs)
        scores.structured_logging = round(_WEIGHTS["structured_logging"] * ratio, 1)
    else:
        scores.structured_logging = 0.0

    # run correlation: any log mentioning a run/correlation id
    if all_logs:
        has_corr = any(_RUN_ID_RE.search(s.message_pattern) for s in all_logs)
        scores.run_correlation = float(_WEIGHTS["run_correlation"]) if has_corr else 0.0
    else:
        scores.run_correlation = 0.0

    applicable = [k for k in _WEIGHTS if k not in scores.not_applicable]
    got = sum(getattr(scores, k) for k in applicable)
    possible = sum(_WEIGHTS[k] for k in applicable)
    scores.overall_score = round(100.0 * got / possible, 1) if possible else 0.0
    return scores
