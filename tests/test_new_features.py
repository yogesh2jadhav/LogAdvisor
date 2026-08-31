import json

import pytest

from conftest import FIXTURE_PROJECT
from logadvisor.analyzer import run_pass1, run_scan
from logadvisor.config import Config
from logadvisor.db.database import Database
from logadvisor.llm.cache import LLMCache
from logadvisor.llm.llm_analyzer import LLMAnalyzer
from logadvisor.llm.provider import GenerationResult, LLMProvider
from logadvisor.models import ScanResult
from logadvisor.report import build_report_document, write_html_report


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, models=("fake:1b",)):
        self._models = list(models)
        self.calls = 0

    def is_available(self):
        return True

    def list_models(self):
        return list(self._models)

    def has_model(self, m):
        return m in self._models

    def generate(self, model, prompt, *, system=None, temperature=0.1, json_format=True):
        self.calls += 1
        payload = {
            "recommend": True, "priority": "HIGH", "category": "X",
            "reason": "fake reason", "recommended_fields": ["run_id", "record_count"],
            "do_not_log": ["patient_id"], "ai_usefulness": "HIGH",
            "ai_use_cases": ["monitoring"], "deterministic_recommendation_reasonable": True,
        }
        return GenerationResult(json.dumps(payload), prompt_tokens=12, output_tokens=7, total_ms=33)


def _cfg(tmp_path):
    cfg = Config()
    cfg.data["database"]["path"] = str(tmp_path / "advisor.db")
    cfg.data["cache"]["dir"] = str(tmp_path / "cache")
    cfg.data["output"]["dir"] = str(tmp_path / "report")
    return cfg


# --------------------------------------------------------------------------
def test_load_scan_result_roundtrip(tmp_path):
    cfg = _cfg(tmp_path)
    original = run_scan(FIXTURE_PROJECT, cfg, use_llm=False)
    db = Database(cfg.database["path"])
    scan_id = db.save_scan(original)

    loaded = db.load_scan_result(scan_id)
    db.close()

    assert loaded is not None
    assert loaded.project.project_name == original.project.project_name
    assert loaded.project.spark_version == original.project.spark_version
    assert len(loaded.findings) == len(original.findings)
    assert {f.category for f in loaded.findings} == {f.category for f in original.findings}
    assert loaded.scores.overall_score == original.scores.overall_score
    assert loaded.methods_scanned == original.methods_scanned
    # exception boundaries survived the round-trip
    excs = [e for cf in loaded.files for m in cf.methods for e in m.exception_boundaries]
    assert any(e.kind == "TRY_CATCH" for e in excs)


def test_report_regenerates_from_db(tmp_path):
    cfg = _cfg(tmp_path)
    db = Database(cfg.database["path"])
    scan_id = db.save_scan(run_scan(FIXTURE_PROJECT, cfg, use_llm=False))
    loaded = db.load_scan_result(scan_id)
    db.close()

    doc = build_report_document(loaded)
    assert doc["schema_version"] == "1"
    assert doc["files"] and doc["summary"]["findings_count"] == len(loaded.findings)
    html = write_html_report(loaded, str(tmp_path / "regen"))
    assert "window.__REPORT__ = " in open(html).read()


def test_get_finding(tmp_path):
    cfg = _cfg(tmp_path)
    db = Database(cfg.database["path"])
    scan_id = db.save_scan(run_scan(FIXTURE_PROJECT, cfg, use_llm=False))
    rows = db.list_findings(scan_id)
    detail = db.get_finding(rows[0]["id"])
    db.close()
    assert detail["class_name"]
    assert detail["method_name"]
    assert json.loads(detail["required_fields"])
    assert detail["recommendation"] is None       # --no-llm
    assert detail["file_path"].endswith(".java")


def test_llm_runs_persisted(tmp_path):
    cfg = _cfg(tmp_path)
    p1 = run_pass1(FIXTURE_PROJECT, cfg)
    result = ScanResult(project=p1.project, files=p1.files, findings=p1.findings,
                        scores=p1.scores, llm_enabled=True, llm_provider="fake",
                        llm_model="fake:1b")
    analyzer = LLMAnalyzer(FakeProvider(), "fake:1b",
                           LLMCache(str(tmp_path / "c"), enabled=False))
    analyzer.analyze(p1.project, p1.files, p1.findings, p1.sources,
                     min_priority="high", limit=3)
    result.llm_runs = analyzer.runs
    assert analyzer.runs and all(r["status"] == "OK" for r in analyzer.runs)

    db = Database(cfg.database["path"])
    scan_id = db.save_scan(result)
    stats = db.llm_run_stats(scan_id)
    db.close()
    assert stats["ok"] == len(analyzer.runs)
    assert stats["output_tokens"] == 7 * len(analyzer.runs)
    assert stats["avg_ms"] > 0


def test_do_not_log_is_deduped_and_capped(tmp_path):
    p1 = run_pass1(FIXTURE_PROJECT, _cfg(tmp_path))
    analyzer = LLMAnalyzer(FakeProvider(), "fake:1b", LLMCache(str(tmp_path / "c"), enabled=False))
    analyzer.analyze(p1.project, p1.files, p1.findings, p1.sources, min_priority="high", limit=1)
    rec = next(f.recommendation for f in p1.findings if f.recommendation and f.llm_status == "OK")
    lowered = [x.lower() for x in rec.do_not_log]
    assert len(rec.do_not_log) <= 8
    assert len(lowered) == len(set(lowered))


def test_benchmark_with_fake_provider(tmp_path, monkeypatch):
    import logadvisor.llm.benchmark as bm

    monkeypatch.setattr(bm, "OllamaClient", lambda *a, **k: FakeProvider(models=["fake:1b"]))
    rows = bm.run_benchmark(FIXTURE_PROJECT, _cfg(tmp_path),
                            ["fake:1b", "missing:9b"], min_priority="high", limit=2)
    by_model = {r["model"]: r for r in rows}
    assert by_model["fake:1b"]["available"] is True
    assert by_model["fake:1b"]["ok"] == 2
    assert by_model["fake:1b"]["structured_output_rate"] == 1.0
    assert by_model["missing:9b"]["available"] is False


def test_provider_abstraction():
    from logadvisor.llm.ollama_client import OllamaClient
    assert issubclass(OllamaClient, LLMProvider)
