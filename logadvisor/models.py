"""Internal data model for the advisor.

These are plain dataclasses used across static analysis, rules, persistence and
reporting. LLM response schemas live in ``logadvisor/llm/response_parser.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class ProjectInfo:
    project_name: str
    path: str
    language: str = "Java"
    project_type: str = "java-spark"   # "java-spark" | "java"
    frameworks: List[str] = field(default_factory=list)
    build_system: Optional[str] = None
    java_version: Optional[str] = None
    spark_version: Optional[str] = None
    logging_frameworks: List[str] = field(default_factory=list)
    java_files: int = 0
    test_files: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LoggingStatement:
    line: int
    level: str                       # INFO / WARN / ERROR / DEBUG / TRACE
    logger_type: str                 # slf4j / log4j / log4j2 / jul / unknown
    message_pattern: str             # message with literals, values redacted
    structured: bool = False         # uses {} placeholders / key=value pairs
    sensitive: bool = False          # appears to log a sensitive value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SparkOperation:
    operation_type: str              # JOIN / FILTER / GROUP_BY / ... (see rules)
    line: int
    snippet: str
    priority: str = "LOW"            # HIGH / MEDIUM / LOW (deterministic)
    # Spark is lazily evaluated: a transformation only runs when an action
    # forces it. ``materialized_at`` is the line of the action that executes
    # this transformation (None = no action found in this method).
    is_action: bool = False
    lazy: bool = False
    materialized_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExceptionBoundary:
    kind: str                        # TRY_CATCH / THROW / THROWS
    start_line: int
    end_line: int
    has_error_logging: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Method:
    name: str
    class_name: str
    start_line: int
    end_line: int
    return_type: str = "void"
    parameters: List[str] = field(default_factory=list)
    annotations: List[str] = field(default_factory=list)
    spark_operations: List[SparkOperation] = field(default_factory=list)
    logging_statements: List[LoggingStatement] = field(default_factory=list)
    exception_boundaries: List[ExceptionBoundary] = field(default_factory=list)

    @property
    def parameter_count(self) -> int:
        return len(self.parameters)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["parameter_count"] = self.parameter_count
        return d


@dataclass
class CodeFile:
    path: str                        # relative to project root
    file_hash: str
    package: Optional[str] = None
    imports: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    interfaces: List[str] = field(default_factory=list)
    methods: List[Method] = field(default_factory=list)
    line_count: int = 0
    is_test: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Finding:
    category: str                    # JOB_START / DATASET_READ / JOIN / FILTER /
                                     # AGGREGATION / DATASET_WRITE / EXCEPTION / ...
    file: str
    class_name: str
    method: str
    line: int
    priority: str                    # HIGH / MEDIUM / LOW
    existing_logging: bool
    logging_quality: str             # MISSING / WEAK / PARTIAL / GOOD
    required_fields: List[str] = field(default_factory=list)
    rule_id: str = ""
    snippet: str = ""
    # for lazy transformations: the line where a Spark action actually runs it
    execution_line: Optional[int] = None
    status: str = "OPEN"             # OPEN / REVIEWED / ACCEPTED / REJECTED /
                                     # IMPLEMENTED / FALSE_POSITIVE
    # Populated in pass 2.
    llm_status: str = "NOT_RUN"      # NOT_RUN / OK / LLM_ANALYSIS_FAILED / CACHE_HIT
    recommendation: Optional["Recommendation"] = None
    fingerprint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.recommendation is not None:
            d["recommendation"] = self.recommendation.to_dict()
        return d


@dataclass
class Recommendation:
    recommend: bool
    priority: str
    category: str
    reason: str
    recommended_fields: List[str] = field(default_factory=list)
    do_not_log: List[str] = field(default_factory=list)
    ai_usefulness: str = "MEDIUM"
    ai_use_cases: List[str] = field(default_factory=list)
    deterministic_recommendation_reasonable: bool = True
    model: str = ""
    prompt_version: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Scores:
    job_lifecycle: float = 0.0
    input_visibility: float = 0.0
    transformation_visibility: float = 0.0
    join_visibility: float = 0.0
    output_visibility: float = 0.0
    exception_visibility: float = 0.0
    structured_logging: float = 0.0
    run_correlation: float = 0.0
    overall_score: float = 0.0
    # buckets excluded from `overall_score` because they don't apply to this
    # project (e.g. Spark data-flow buckets on a plain-Java project).
    not_applicable: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScanResult:
    project: ProjectInfo
    files: List[CodeFile]
    findings: List[Finding]
    scores: Scores
    llm_enabled: bool = False
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    scan_id: Optional[int] = None
    llm_calls: int = 0
    llm_failures: int = 0
    cache_hits: int = 0
    # per-finding LLM execution records (see llm.llm_analyzer.LLMAnalyzer.runs)
    llm_runs: List[Dict[str, Any]] = field(default_factory=list)

    # ---- aggregate counters used by the report -------------------------------
    @property
    def files_scanned(self) -> int:
        return len(self.files)

    @property
    def methods_scanned(self) -> int:
        return sum(len(f.methods) for f in self.files)

    @property
    def classes_scanned(self) -> int:
        return sum(len(f.classes) for f in self.files)

    @property
    def spark_operations(self) -> int:
        return sum(len(m.spark_operations) for f in self.files for m in f.methods)

    @property
    def existing_logs(self) -> int:
        return sum(len(m.logging_statements) for f in self.files for m in f.methods)

    def by_priority(self, priority: str) -> List[Finding]:
        return [x for x in self.findings if x.priority == priority]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project": self.project.to_dict(),
            "scan_id": self.scan_id,
            "summary": {
                "files_scanned": self.files_scanned,
                "classes_scanned": self.classes_scanned,
                "methods_scanned": self.methods_scanned,
                "spark_operations": self.spark_operations,
                "existing_logs": self.existing_logs,
                "findings_count": len(self.findings),
                "high": len(self.by_priority("HIGH")),
                "medium": len(self.by_priority("MEDIUM")),
                "low": len(self.by_priority("LOW")),
                "llm_calls": self.llm_calls,
                "llm_failures": self.llm_failures,
                "cache_hits": self.cache_hits,
            },
            "llm": {
                "enabled": self.llm_enabled,
                "provider": self.llm_provider,
                "model": self.llm_model,
            },
            "scores": self.scores.to_dict(),
            "findings": [x.to_dict() for x in self.findings],
        }
