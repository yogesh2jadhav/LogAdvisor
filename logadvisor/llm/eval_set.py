"""LLM recommendation-quality evaluation (Plan section 34).

A fixed set of representative Java + Spark snippets with *expected structural
characteristics* (not exact wording). The runner sends each through the real
pipeline (parse -> rule engine -> LLM) and scores the recommendation against:

  * did it return valid structured output?
  * recommend flag as expected
  * priority within the expected band
  * AI-usefulness within the expected set
  * no PHI/PII terms in the recommended fields

Run it with ``java-log-advisor eval --model <model>``.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..config import Config
from ..models import Finding
from ..rules.rule_engine import RuleEngine
from ..scanner.java_parser import parse_java_file
from ..security import find_sensitive_terms

_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


@dataclass
class EvalCase:
    id: str
    category: str                     # finding category to evaluate
    java: str
    recommend: bool = True
    min_priority: str = "LOW"
    max_priority: str = "HIGH"
    ai_usefulness_in: List[str] = field(default_factory=lambda: ["LOW", "MEDIUM", "HIGH"])


def _cls(body: str) -> str:
    return ("package eval;\nimport org.apache.spark.sql.*;\n"
            "class Sample {\n" + body + "\n}\n")


EVAL_CASES: List[EvalCase] = [
    EvalCase(
        "join", "JOIN", _cls("""
        Dataset<Row> run(Dataset<Row> left, Dataset<Row> right) {
            Dataset<Row> j = left.join(right, left.col("k").equalTo(right.col("k")), "inner");
            j.write().parquet("/out");
            return j;
        }"""),
        min_priority="HIGH", ai_usefulness_in=["HIGH"],
    ),
    EvalCase(
        "filter", "FILTER", _cls("""
        Dataset<Row> run(Dataset<Row> in) {
            Dataset<Row> f = in.filter(in.col("status").equalTo("ACTIVE"));
            f.write().parquet("/out");
            return f;
        }"""),
        min_priority="MEDIUM", ai_usefulness_in=["MEDIUM", "HIGH"],
    ),
    EvalCase(
        "aggregation", "AGGREGATION", _cls("""
        Dataset<Row> run(Dataset<Row> in) {
            Dataset<Row> g = in.groupBy("dept").agg(functions.count("id").alias("n"));
            g.write().parquet("/out");
            return g;
        }"""),
        min_priority="HIGH", ai_usefulness_in=["HIGH"],
    ),
    EvalCase(
        "parquet_write", "PARQUET_WRITE", _cls("""
        void run(Dataset<Row> result) {
            result.write().mode("overwrite").parquet("/data/out");
        }"""),
        min_priority="HIGH", ai_usefulness_in=["HIGH"],
    ),
    EvalCase(
        "spark_read", "PARQUET_READ", _cls("""
        Dataset<Row> run(SparkSession spark) {
            return spark.read().parquet("/data/in");
        }"""),
        min_priority="MEDIUM", ai_usefulness_in=["MEDIUM", "HIGH"],
    ),
    EvalCase(
        "exception", "EXCEPTION", _cls("""
        void run(Dataset<Row> in) {
            try { in.write().parquet("/out"); }
            catch (Exception e) { in.count(); }
        }"""),
        min_priority="HIGH", ai_usefulness_in=["MEDIUM", "HIGH"],
    ),
    EvalCase(
        "simple_select", "SELECT", _cls("""
        Dataset<Row> run(Dataset<Row> in) {
            Dataset<Row> s = in.select("a", "b");
            s.write().parquet("/out");
            return s;
        }"""),
        recommend=False, max_priority="LOW", ai_usefulness_in=["LOW", "MEDIUM"],
    ),
]


def _finding_for(case: EvalCase) -> Optional[Finding]:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Sample.java"
        p.write_text(case.java)
        cf = parse_java_file(str(p), d)
    findings = RuleEngine().evaluate([cf])
    return next((f for f in findings if f.category == case.category), None)


def check(case: EvalCase, finding: Optional[Finding]) -> Dict[str, Optional[bool]]:
    out: Dict[str, Optional[bool]] = {
        "finding_detected": finding is not None,
        "structured_output": None,
        "recommend_flag": None,
        "priority_band": None,
        "ai_usefulness": None,
        "no_sensitive_fields": None,
    }
    if finding is None:
        return out
    rec = finding.recommendation
    out["structured_output"] = rec is not None and finding.llm_status in ("OK", "CACHE_HIT")
    if rec is None:
        return out
    out["recommend_flag"] = (rec.recommend == case.recommend)
    out["priority_band"] = (
        _RANK[case.min_priority] <= _RANK.get(rec.priority, 1) <= _RANK[case.max_priority]
    )
    out["ai_usefulness"] = rec.ai_usefulness in case.ai_usefulness_in
    # PHI/PII screen on the recommended field names (word-boundary, curated list;
    # 'filter_name' / 'processing_name' must not trip it).
    out["no_sensitive_fields"] = not find_sensitive_terms(" ".join(rec.recommended_fields))
    return out


def run_eval(config: Config, model: str, *, temperature: float = 0.0,
             log: Optional[Callable[[str], None]] = None) -> Dict:
    """Evaluate ``model`` over EVAL_CASES. Returns per-case + aggregate results."""
    from .cache import LLMCache
    from .llm_analyzer import LLMAnalyzer
    from .ollama_client import OllamaClient
    from ..models import ProjectInfo

    log = log or (lambda m: None)
    config.validate_llm_endpoint()
    client = OllamaClient(config.llm["host"], config.llm["timeout_seconds"])
    if not client.is_available():
        raise RuntimeError(f"Ollama not available at {config.llm['host']}")
    if not client.has_model(model):
        raise RuntimeError(f"Model '{model}' not pulled (ollama pull {model})")

    project = ProjectInfo(project_name="eval", path=".", frameworks=["Apache Spark"])
    cache = LLMCache(config.cache["dir"], enabled=False)
    results = []
    for case in EVAL_CASES:
        finding = _finding_for(case)
        if finding is not None:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "Sample.java"
                p.write_text(case.java)
                cf = parse_java_file(str(p), d)
                analyzer = LLMAnalyzer(client, model, cache, temperature=temperature)
                analyzer.analyze(project, [cf], [finding], {cf.path: case.java},
                                 min_priority="low", limit=1)
        checks = check(case, finding)
        passed = [k for k, v in checks.items() if v is True]
        failed = [k for k, v in checks.items() if v is False]
        results.append({"id": case.id, "category": case.category,
                        "checks": checks, "passed": passed, "failed": failed})
        log(f"  {case.id:<14} pass={len(passed)} fail={len(failed)} "
            f"{'FAILED: ' + ', '.join(failed) if failed else 'ok'}")

    total_checks = sum(len([v for v in r["checks"].values() if v is not None]) for r in results)
    total_pass = sum(len(r["passed"]) for r in results)
    return {
        "model": model,
        "cases": results,
        "summary": {
            "cases": len(results),
            "checks_run": total_checks,
            "checks_passed": total_pass,
            "pass_rate": round(total_pass / total_checks, 3) if total_checks else 0.0,
            "clean_cases": sum(1 for r in results if not r["failed"]),
        },
    }
