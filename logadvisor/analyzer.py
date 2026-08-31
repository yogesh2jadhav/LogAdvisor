"""Two-pass orchestration.

Pass 1 (deterministic): discovery -> Java parse -> Spark/log/exception detection
                        -> rule engine -> findings -> score.
Pass 2 (optional, LLM): select important findings -> context -> Ollama -> validate
                        -> recommendation.
"""
from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional

from .config import Config
from .llm.cache import LLMCache
from .llm.llm_analyzer import LLMAnalyzer
from .llm.ollama_client import OllamaClient, OllamaError
from .models import CodeFile, ScanResult
from .rules.rule_engine import RuleEngine
from .scanner.java_parser import parse_java_file
from .scanner.project_scanner import scan_project
from .scoring import compute_scores

Logger = Callable[[str], None]


class AdvisorError(RuntimeError):
    pass


def run_scan(project_path: str, config: Config, *, use_llm: bool,
             log: Optional[Logger] = None) -> ScanResult:
    log = log or (lambda m: None)
    project_path = os.path.abspath(project_path)

    log("scan_start")
    info, java_files = scan_project(project_path, config.scan["ignore_dirs"])
    log(f"discovered {info.java_files} java files ({info.test_files} tests), "
        f"build={info.build_system}, spark={info.spark_version or '?'}")

    files: List[CodeFile] = []
    sources: Dict[str, str] = {}
    for jf in java_files:
        try:
            cf = parse_java_file(jf, project_path)
        except Exception as exc:  # never abort the whole scan for one file
            log(f"  parse failed for {jf}: {exc}")
            continue
        files.append(cf)
        with open(jf, "r", encoding="utf-8", errors="replace") as fh:
            sources[cf.path] = fh.read()

    log(f"parsed {len(files)} files, "
        f"{sum(len(f.methods) for f in files)} methods")

    engine = RuleEngine()
    findings = engine.evaluate(files)
    log(f"findings_created {len(findings)}")

    scores = compute_scores(files, findings)
    log(f"ai_observability_score {scores.overall_score}")

    result = ScanResult(
        project=info, files=files, findings=findings, scores=scores,
        llm_enabled=False, llm_provider="ollama", llm_model=config.llm["model"],
    )

    if use_llm and config.llm["enabled"]:
        config.validate_llm_endpoint()
        client = OllamaClient(config.llm["host"], config.llm["timeout_seconds"])
        if not client.is_available():
            raise AdvisorError(
                "Ollama is not available at "
                f"{config.llm['host']}.\n\nRun the advisor with --no-llm, "
                "or start Ollama and retry."
            )
        if not client.has_model(config.llm["model"]):
            raise AdvisorError(
                f"Model '{config.llm['model']}' not found in Ollama.\n"
                f"Pull it with:  ollama pull {config.llm['model']}\n"
                "or pass --model <available-model> / use --no-llm."
            )
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
        )
        result.llm_enabled = True
        result.llm_calls = analyzer.calls
        result.llm_failures = analyzer.failures
        result.cache_hits = analyzer.cache_hits
        log(f"llm_calls {analyzer.calls} llm_failures {analyzer.failures} "
            f"cache_hits {analyzer.cache_hits}")

    log("scan_end")
    return result
