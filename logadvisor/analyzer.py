"""Two-pass orchestration.

Pass 1 (deterministic): discovery -> Java parse -> Spark/log/exception detection
                        -> rule engine -> findings -> score.
Pass 2 (optional, LLM): select important findings -> context -> Ollama -> validate
                        -> recommendation.
"""
from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional

from dataclasses import dataclass

from .config import Config
from .llm.cache import LLMCache
from .llm.llm_analyzer import LLMAnalyzer
from .llm.ollama_client import OllamaClient, OllamaError
from .models import CodeFile, Finding, ProjectInfo, ScanResult, Scores
from .rules.rule_engine import RuleEngine
from .scanner.java_parser import parse_java_file
from .scanner.project_scanner import scan_project
from .scoring import compute_scores

Logger = Callable[[str], None]
Progress = Callable[[int, int, str], None]


def _noop_progress(done: int, total: int, label: str = "") -> None:
    pass


class AdvisorError(RuntimeError):
    pass


@dataclass
class Pass1:
    project: ProjectInfo
    files: List[CodeFile]
    sources: Dict[str, str]
    findings: List[Finding]
    scores: Scores


def run_pass1(project_path: str, config: Config, log: Optional[Logger] = None,
              progress: Optional[Progress] = None) -> Pass1:
    """Deterministic analysis only - no LLM, no persistence."""
    log = log or (lambda m: None)
    progress = progress or _noop_progress
    project_path = os.path.abspath(project_path)

    from .scanner import java_parser as _jp

    _jp.set_backend(config.scan.get("parser", "auto"))
    log("scan_start")
    info, java_files = scan_project(project_path, config.scan["ignore_dirs"])
    log(f"discovered {info.java_files} java files ({info.test_files} tests), "
        f"build={info.build_system}, spark={info.spark_version or '?'}, "
        f"parser={_jp.active_backend()}")

    files: List[CodeFile] = []
    sources: Dict[str, str] = {}
    total = len(java_files)
    for i, jf in enumerate(java_files, 1):
        try:
            cf = parse_java_file(jf, project_path)
        except Exception as exc:  # never abort the whole scan for one file
            log(f"  parse failed for {jf}: {exc}")
            continue
        files.append(cf)
        with open(jf, "r", encoding="utf-8", errors="replace") as fh:
            sources[cf.path] = fh.read()
        progress(i, total, "scanning")

    log(f"parsed {len(files)} files, {sum(len(f.methods) for f in files)} methods")

    findings = RuleEngine().evaluate(files)
    log(f"findings_created {len(findings)}")
    scores = compute_scores(files, findings)
    log(f"ai_observability_score {scores.overall_score}")
    return Pass1(info, files, sources, findings, scores)


def check_ollama(config: Config) -> OllamaClient:
    """Validate the endpoint + model, returning a ready client or raising."""
    config.validate_llm_endpoint()
    client = OllamaClient(config.llm["host"], config.llm["timeout_seconds"])
    if not client.is_available():
        raise AdvisorError(
            f"Ollama is not available at {config.llm['host']}.\n\n"
            "Run the advisor with --no-llm, or start Ollama and retry."
        )
    if not client.has_model(config.llm["model"]):
        raise AdvisorError(
            f"Model '{config.llm['model']}' not found in Ollama.\n"
            f"Pull it with:  ollama pull {config.llm['model']}\n"
            "or pass --model <available-model> / use --no-llm."
        )
    return client


def run_scan(project_path: str, config: Config, *, use_llm: bool,
             log: Optional[Logger] = None,
             progress: Optional[Progress] = None) -> ScanResult:
    log = log or (lambda m: None)
    progress = progress or _noop_progress
    p1 = run_pass1(project_path, config, log, progress)
    info, files, sources, findings, scores = (
        p1.project, p1.files, p1.sources, p1.findings, p1.scores)

    result = ScanResult(
        project=info, files=files, findings=findings, scores=scores,
        llm_enabled=False, llm_provider="ollama", llm_model=config.llm["model"],
    )

    if use_llm and config.llm["enabled"]:
        client = check_ollama(config)
        cache = LLMCache(config.cache["dir"], config.llm["cache_enabled"])
        analyzer = LLMAnalyzer(
            client, config.llm["model"], cache,
            temperature=config.llm["temperature"],
            max_retries=config.llm["max_retries"],
            logger=log,
        )
        analyzer.analyze(
            info, files, findings, sources,
            min_priority=config.llm["priority"], limit=config.llm["limit"],
            progress=progress,
        )
        result.llm_enabled = True
        result.llm_calls = analyzer.calls
        result.llm_failures = analyzer.failures
        result.cache_hits = analyzer.cache_hits
        result.llm_runs = analyzer.runs
        log(f"llm_calls {analyzer.calls} llm_failures {analyzer.failures} "
            f"cache_hits {analyzer.cache_hits}")

    log("scan_end")
    return result
