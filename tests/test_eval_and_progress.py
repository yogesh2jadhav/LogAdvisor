import json

import pytest

from logadvisor.config import Config
from logadvisor.llm.eval_set import EVAL_CASES, _finding_for, check, run_eval
from logadvisor.llm.provider import GenerationResult, LLMProvider
from logadvisor.models import Recommendation


# --- eval-set data sanity ---------------------------------------------
def test_every_eval_case_produces_its_finding():
    """The eval set is only meaningful if the rule engine actually emits a
    finding for each case's category."""
    for case in EVAL_CASES:
        f = _finding_for(case)
        assert f is not None, f"no {case.category} finding for case {case.id}"


# --- checker logic --------------------------------------------------
def _finding_with(reco, category="JOIN"):
    from logadvisor.models import Finding
    fd = Finding(category=category, file="x", class_name="C", method="m", line=1,
                 priority="HIGH", existing_logging=False, logging_quality="MISSING")
    fd.recommendation = reco
    fd.llm_status = "OK"
    return fd


def test_check_passes_a_good_recommendation():
    join = next(c for c in EVAL_CASES if c.id == "join")
    good = Recommendation(recommend=True, priority="HIGH", category="JOIN", reason="r",
                          recommended_fields=["run_id", "left_count", "output_count"],
                          ai_usefulness="HIGH")
    res = check(join, _finding_with(good))
    assert all(v for v in res.values() if v is not None)


def test_check_flags_sensitive_fields_and_wrong_priority():
    join = next(c for c in EVAL_CASES if c.id == "join")
    bad = Recommendation(recommend=True, priority="LOW", category="JOIN", reason="r",
                         recommended_fields=["patient_name", "diagnosis"],
                         ai_usefulness="LOW")
    res = check(join, _finding_with(bad))
    assert res["no_sensitive_fields"] is False
    assert res["priority_band"] is False
    assert res["ai_usefulness"] is False


def test_check_handles_missing_recommendation():
    join = next(c for c in EVAL_CASES if c.id == "join")
    res = check(join, _finding_with(None))
    assert res["structured_output"] is False
    assert res["recommend_flag"] is None


# --- run_eval end to end with a scripted provider --------------------
class ScriptedProvider(LLMProvider):
    name = "scripted"

    def is_available(self):
        return True

    def list_models(self):
        return ["scripted:1b"]

    def has_model(self, m):
        return True

    def generate(self, model, prompt, *, system=None, temperature=0.1, json_format=True):
        # answer well: HIGH priority, safe metadata fields
        low = "select" in prompt.lower() and "groupBy" not in prompt
        payload = {
            "recommend": not low,
            "priority": "LOW" if low else "HIGH",
            "category": "X",
            "reason": "structured metrics help RCA",
            "recommended_fields": ["run_id", "record_count", "duration"],
            "do_not_log": ["patient identifiers"],
            "ai_usefulness": "MEDIUM" if low else "HIGH",
            "ai_use_cases": ["monitoring"],
            "deterministic_recommendation_reasonable": True,
        }
        return GenerationResult(json.dumps(payload), prompt_tokens=10, output_tokens=6, total_ms=5)


def test_run_eval_with_scripted_model(monkeypatch, tmp_path):
    monkeypatch.setattr("logadvisor.llm.ollama_client.OllamaClient",
                        lambda *a, **k: ScriptedProvider())
    cfg = Config()
    cfg.data["cache"]["dir"] = str(tmp_path / "c")
    res = run_eval(cfg, "scripted:1b")
    s = res["summary"]
    assert s["cases"] == len(EVAL_CASES)
    assert s["checks_passed"] > 0
    # the scripted model answers well -> most cases should be clean
    assert s["clean_cases"] >= len(EVAL_CASES) - 1


# --- progress bar ---------------------------------------------------
def test_progress_bar_noop_when_not_tty(capsys):
    from logadvisor.cli import _ProgressBar
    bar = _ProgressBar(enabled=False)
    bar(1, 10, "x")
    bar.finish()
    assert capsys.readouterr().err == ""


def test_progress_bar_draws_when_enabled(capsys):
    from logadvisor.cli import _ProgressBar
    bar = _ProgressBar(enabled=True)
    bar(2, 4, "scanning")
    bar(4, 4, "scanning")
    err = capsys.readouterr().err
    assert "50%" in err and "100%" in err and err.endswith("\n")
