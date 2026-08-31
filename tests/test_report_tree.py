import json
import os

from conftest import FIXTURE_PROJECT
from logadvisor.analyzer import run_scan
from logadvisor.config import Config
from logadvisor.report import build_report_document, write_html_report, write_json_report


def _doc(tmp_path):
    cfg = Config()
    cfg.data["database"]["path"] = str(tmp_path / "a.db")
    result = run_scan(FIXTURE_PROJECT, cfg, use_llm=False)
    return result, build_report_document(result)


def test_document_shape(tmp_path):
    result, doc = _doc(tmp_path)
    assert doc["schema_version"] == "1"
    assert "files" in doc and "rules" in doc
    assert doc["summary"]["findings_count"] == len(result.findings)

    # every finding has a stable id, ids are unique and dense
    ids = [f["id"] for f in doc["findings"]]
    assert ids == list(range(1, len(ids) + 1))

    # tree references only real finding ids
    ref = {i for f in doc["files"] for c in f["classes"]
           for m in c["methods"] for i in m["finding_ids"]}
    assert ref <= set(ids)


def test_tree_has_structure_and_rollups(tmp_path):
    _, doc = _doc(tmp_path)
    pp = next(f for f in doc["files"] if f["path"].endswith("PatientProcessor.java"))
    assert 0 <= pp["ai_readiness"] <= 100
    assert pp["risk"] in ("HIGH", "MEDIUM", "LOW")
    m = next(mm for c in pp["classes"] for mm in c["methods"] if mm["name"] == "processPatients")
    d = m["detected"]
    assert d["join"] is True and d["filter"] is True and d["output"] is True
    assert d["structured_logging"] is False
    assert len(m["spark_operations"]) > 0
    assert len(m["finding_ids"]) > 0


def test_rules_contract_present(tmp_path):
    _, doc = _doc(tmp_path)
    assert "join" in doc["rules"]
    assert "left_count" in doc["rules"]["join"]["fields"]


def test_covered_method_has_no_findings_but_still_listed(tmp_path):
    _, doc = _doc(tmp_path)
    agg = next(f for f in doc["files"] if f["path"].endswith("AggregationJob.java"))
    summarize = next(m for c in agg["classes"] for m in c["methods"] if m["name"] == "summarize")
    # the catch block logs error -> no EXCEPTION finding, method still in the tree
    assert "EXCEPTION" not in {
        doc["findings"][i - 1]["category"] for i in summarize["finding_ids"]
    }


def test_html_is_self_contained(tmp_path):
    result, _ = _doc(tmp_path)
    path = write_html_report(result, str(tmp_path / "report"))
    html = open(path, encoding="utf-8").read()
    assert "<title>AI-Ready Logging Advisory Report</title>" in html
    assert "window.__REPORT__ = " in html
    assert "/*__REPORT_DATA__*/null" not in html          # placeholder replaced
    assert "http://" not in html and "https://" not in html  # no external assets
    # embedded payload is valid JSON
    start = html.index("window.__REPORT__ = ") + len("window.__REPORT__ = ")
    end = html.index(";</script>", start)
    json.loads(html[start:end].replace("\\u003c", "<"))


def test_json_report_uses_enriched_document(tmp_path):
    result, _ = _doc(tmp_path)
    path = write_json_report(result, str(tmp_path / "r"))
    data = json.load(open(path))
    assert data["schema_version"] == "1"
    assert isinstance(data["files"], list) and data["files"]
