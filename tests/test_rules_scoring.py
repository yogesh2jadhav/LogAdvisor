import os

from conftest import FIXTURE_PROJECT
from logadvisor.config import DEFAULT_IGNORE_DIRS
from logadvisor.rules.rule_engine import RuleEngine
from logadvisor.scanner.java_parser import parse_java_file
from logadvisor.scanner.project_scanner import scan_project
from logadvisor.scoring import compute_scores


def _analyze():
    info, files = scan_project(FIXTURE_PROJECT, DEFAULT_IGNORE_DIRS)
    parsed = [parse_java_file(p, FIXTURE_PROJECT) for p in files]
    findings = RuleEngine().evaluate(parsed)
    return info, parsed, findings


def test_findings_generated():
    _, _, findings = _analyze()
    cats = {f.category for f in findings}
    assert "JOIN" in cats
    assert "PARQUET_WRITE" in cats
    assert "EXCEPTION" in cats
    join = next(f for f in findings if f.category == "JOIN")
    assert join.priority == "HIGH"
    assert "left_count" in join.required_fields
    # the only nearby log is an unstructured INFO -> weak/missing coverage
    assert join.logging_quality in ("MISSING", "WEAK")
    assert join.fingerprint


def test_test_sources_excluded():
    _, _, findings = _analyze()
    assert all("/src/test/" not in f.file.replace("\\", "/") for f in findings)


def test_exception_finding_only_when_unlogged():
    _, _, findings = _analyze()
    exc = [f for f in findings if f.category == "EXCEPTION"]
    # PatientProcessor has 1 unlogged catch; AggregationJob's catch logs error.
    files = {f.file for f in exc}
    assert any("PatientProcessor" in x for x in files)
    assert not any("AggregationJob" in x for x in files)


def test_score_is_deterministic_and_bounded():
    _, parsed, findings = _analyze()
    s1 = compute_scores(parsed, findings)
    s2 = compute_scores(parsed, findings)
    assert s1.to_dict() == s2.to_dict()
    assert 0 <= s1.overall_score <= 100
    # lots of missing logging -> not a perfect score
    assert s1.overall_score < 100
