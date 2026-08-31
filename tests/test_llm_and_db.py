import os

from conftest import FIXTURE_PROJECT
from logadvisor.analyzer import run_scan
from logadvisor.config import Config
from logadvisor.db.database import Database
from logadvisor.llm.response_parser import parse_response
from logadvisor.report import write_json_report, write_markdown_report
from logadvisor.security import mask_secrets, sanitize_recommended_fields


def test_response_parser_repairs_and_validates():
    raw = 'noise before {"recommend": true, "priority": "high", "recommended_fields": "a, b, c",} tail'
    rec = parse_response(raw)
    assert rec.recommend is True
    assert rec.priority == "HIGH"
    assert rec.recommended_fields == ["a", "b", "c"]


def test_response_parser_rejects_garbage():
    import pytest

    with pytest.raises(ValueError):
        parse_response("not json at all")


def test_mask_secrets():
    assert "MASKED" in mask_secrets('String password = "hunter2";')
    assert "MASKED" in mask_secrets('api_key: sk-abcdef123456')


def test_sanitize_rejects_phi_fields():
    safe, rejected = sanitize_recommended_fields(["run_id", "patient_name", "left_count", "diagnosis"])
    assert safe == ["run_id", "left_count"]
    assert set(rejected) == {"patient_name", "diagnosis"}


def test_full_scan_no_llm_writes_reports_and_db(tmp_path):
    cfg = Config()
    cfg.data["database"]["path"] = str(tmp_path / "advisor.db")
    cfg.data["output"]["dir"] = str(tmp_path / "report")

    result = run_scan(FIXTURE_PROJECT, cfg, use_llm=False)
    assert result.llm_enabled is False
    assert len(result.findings) > 0

    db = Database(cfg.database["path"])
    scan_id = db.save_scan(result)
    assert scan_id == 1
    hist = db.history()
    assert hist[0]["id"] == 1
    rows = db.list_findings(scan_id)
    assert len(rows) == len(result.findings)
    assert db.set_finding_status(rows[0]["id"], "ACCEPTED")

    # carry-forward: a second scan keeps the ACCEPTED status for same fingerprint
    result2 = run_scan(FIXTURE_PROJECT, cfg, use_llm=False)
    db.save_scan(result2)
    rows2 = db.list_findings(2)
    accepted = [r for r in rows2 if r["status"] == "ACCEPTED"]
    assert len(accepted) == 1
    db.close()

    md = write_markdown_report(result, cfg.output["dir"])
    js = write_json_report(result, cfg.output["dir"])
    assert os.path.isfile(md) and os.path.isfile(js)
    assert "AI Observability Score" in open(md).read()


def test_external_llm_endpoint_refused():
    import pytest

    cfg = Config()
    cfg.data["llm"]["host"] = "http://api.openai.com"
    with pytest.raises(ValueError):
        cfg.validate_llm_endpoint()
