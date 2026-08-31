"""Model benchmarking (Plan 49.8 / milestone 16).

Runs pass 1 once, then replays the LLM pass for each candidate model against a
copy of the findings and reports timing / reliability metrics. Recommendation
*quality* is left to manual review - this measures the mechanical properties.
"""
from __future__ import annotations

import copy
import time
from typing import Callable, Dict, List, Optional

from ..analyzer import run_pass1
from ..config import Config
from ..llm.cache import LLMCache
from ..llm.llm_analyzer import LLMAnalyzer
from ..llm.ollama_client import OllamaClient

Logger = Callable[[str], None]


def run_benchmark(project_path: str, config: Config, models: List[str], *,
                  min_priority: str = "high", limit: int = 0,
                  log: Optional[Logger] = None) -> List[Dict]:
    log = log or (lambda m: None)
    config.validate_llm_endpoint()
    p1 = run_pass1(project_path, config, log)
    client = OllamaClient(config.llm["host"], config.llm["timeout_seconds"])
    available = set(client.list_models()) if client.is_available() else set()

    rows: List[Dict] = []
    for model in models:
        model = model.strip()
        if not model:
            continue
        if not (model in available or any(m.split(":")[0] == model.split(":")[0] for m in available)):
            rows.append({"model": model, "available": False})
            log(f"  {model}: not available - skipped")
            continue

        findings = copy.deepcopy(p1.findings)
        cache = LLMCache(config.cache["dir"], enabled=False)   # bypass cache for fair timing
        analyzer = LLMAnalyzer(client, model, cache,
                               temperature=config.llm["temperature"],
                               max_retries=config.llm["max_retries"], logger=log)
        t0 = time.monotonic()
        analyzer.analyze(p1.project, p1.files, findings, p1.sources,
                         min_priority=min_priority, limit=limit)
        wall = time.monotonic() - t0

        timed = [r["duration_ms"] for r in analyzer.runs if r.get("status") == "OK" and r.get("duration_ms")]
        ok = sum(1 for r in analyzer.runs if r.get("status") == "OK")
        failed = sum(1 for r in analyzer.runs if r.get("status") == "LLM_ANALYSIS_FAILED")
        recs = sum(1 for f in findings if f.recommendation and f.recommendation.recommend)
        rows.append({
            "model": model,
            "available": True,
            "analysed": len(analyzer.runs),
            "llm_calls": analyzer.calls,
            "ok": ok,
            "failed": failed,
            "structured_output_rate": round(ok / (ok + failed), 3) if (ok + failed) else 0.0,
            "avg_response_ms": round(sum(timed) / len(timed), 1) if timed else 0.0,
            "total_analysis_s": round(wall, 1),
            "input_tokens": sum(r.get("input_tokens", 0) for r in analyzer.runs),
            "output_tokens": sum(r.get("output_tokens", 0) for r in analyzer.runs),
            "recommendation_count": recs,
        })
        log(f"  {model}: ok={ok} failed={failed} avg={rows[-1]['avg_response_ms']}ms "
            f"total={rows[-1]['total_analysis_s']}s")
    return rows
