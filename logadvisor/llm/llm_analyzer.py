"""Pass 2 - LLM analysis of high-priority findings.

A failed / invalid LLM response never aborts the scan: the finding keeps its
deterministic recommendation and is marked ``LLM_ANALYSIS_FAILED``.
"""
from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional

from .. import PROMPT_VERSION
from ..models import CodeFile, Finding, Method, ProjectInfo, Recommendation
from ..security import DEFAULT_DO_NOT_LOG, sanitize_recommended_fields
from .cache import LLMCache
from .ollama_client import OllamaClient, OllamaError
from .prompt_builder import SYSTEM_PROMPT, build_prompt
from .response_parser import parse_response

_PRIORITY_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


class LLMAnalyzer:
    def __init__(self, client: OllamaClient, model: str, cache: LLMCache,
                 temperature: float = 0.1, max_retries: int = 1,
                 logger: Optional[Callable[[str], None]] = None):
        self.client = client
        self.model = model
        self.cache = cache
        self.temperature = temperature
        self.max_retries = max_retries
        self.log = logger or (lambda m: None)
        self.calls = 0
        self.failures = 0
        self.cache_hits = 0

    def _select(self, findings: List[Finding], min_priority: str, limit: int) -> List[Finding]:
        floor = _PRIORITY_RANK.get(min_priority.upper(), 2)
        chosen = [f for f in findings if _PRIORITY_RANK[f.priority] >= floor]
        chosen.sort(key=lambda f: (-_PRIORITY_RANK[f.priority], f.file, f.line))
        if limit and limit > 0:
            chosen = chosen[:limit]
        return chosen

    def _method_for(self, cf: CodeFile, finding: Finding) -> Optional[Method]:
        cands = [m for m in cf.methods if m.name == finding.method
                 and m.start_line <= finding.line <= m.end_line]
        return cands[0] if cands else None

    def _fallback_recommendation(self, finding: Finding, status: str, reason: str) -> None:
        finding.llm_status = status
        finding.recommendation = Recommendation(
            recommend=finding.priority in ("HIGH", "MEDIUM"),
            priority=finding.priority,
            category=finding.category,
            reason=f"[deterministic only] {reason}",
            recommended_fields=finding.required_fields,
            do_not_log=list(DEFAULT_DO_NOT_LOG),
            ai_usefulness="HIGH" if finding.priority == "HIGH" else "MEDIUM",
            ai_use_cases=["pipeline_monitoring", "anomaly_detection", "root_cause_analysis"],
            model=self.model,
            prompt_version=PROMPT_VERSION,
        )

    def analyze(self, project: ProjectInfo, files: List[CodeFile], findings: List[Finding],
                sources: Dict[str, str], min_priority: str = "high", limit: int = 0) -> None:
        by_path = {cf.path: cf for cf in files}
        selected = self._select(findings, min_priority, limit)
        self.log(f"LLM analysing {len(selected)} of {len(findings)} findings "
                 f"(min_priority={min_priority}, limit={limit or 'none'})")

        for i, finding in enumerate(selected, 1):
            cf = by_path.get(finding.file)
            source = sources.get(finding.file, "")
            method = self._method_for(cf, finding) if cf else None
            if not (cf and method and source):
                self._fallback_recommendation(finding, "LLM_ANALYSIS_FAILED", "method context unavailable")
                self.failures += 1
                continue

            method_code = "".join(source.splitlines(keepends=True)[method.start_line - 1:method.end_line])
            ckey = LLMCache.key(file_hash=cf.file_hash, method_code=method_code + finding.snippet,
                                rule_id=finding.rule_id, prompt_version=PROMPT_VERSION, model=self.model)

            cached = self.cache.get(ckey)
            if cached is not None:
                self.cache_hits += 1
                self._apply(finding, cached, "CACHE_HIT")
                continue

            prompt = build_prompt(project, cf, method, finding, source)
            rec_dict = self._call_with_retry(prompt)
            if rec_dict is None:
                self._fallback_recommendation(finding, "LLM_ANALYSIS_FAILED", "LLM unavailable or invalid JSON")
                self.failures += 1
                continue

            self.cache.put(ckey, rec_dict)
            self._apply(finding, rec_dict, "OK")
            self.log(f"  [{i}/{len(selected)}] {finding.category} {finding.file}:{finding.line} -> "
                     f"{finding.recommendation.priority}")

    def _call_with_retry(self, prompt: str) -> Optional[dict]:
        attempt = 0
        current = prompt
        while attempt <= self.max_retries:
            attempt += 1
            try:
                self.calls += 1
                raw = self.client.generate(
                    self.model, current, system=SYSTEM_PROMPT,
                    temperature=self.temperature, json_format=True,
                )
                return parse_response(raw).model_dump()
            except (OllamaError, ValueError) as exc:
                self.log(f"  LLM attempt {attempt} failed: {exc}")
                current = (prompt + "\n\nYour previous answer was not valid JSON. "
                           "Reply with ONLY the JSON object described above.")
        return None

    def _apply(self, finding: Finding, rec_dict: dict, status: str) -> None:
        safe, rejected = sanitize_recommended_fields(rec_dict.get("recommended_fields", []))
        do_not_log = list(dict.fromkeys(list(rec_dict.get("do_not_log", [])) + DEFAULT_DO_NOT_LOG + rejected))
        finding.llm_status = status
        finding.recommendation = Recommendation(
            recommend=bool(rec_dict.get("recommend", True)),
            priority=rec_dict.get("priority", finding.priority),
            category=rec_dict.get("category") or finding.category,
            reason=rec_dict.get("reason", ""),
            recommended_fields=safe or finding.required_fields,
            do_not_log=do_not_log,
            ai_usefulness=rec_dict.get("ai_usefulness", "MEDIUM"),
            ai_use_cases=list(rec_dict.get("ai_use_cases", [])),
            deterministic_recommendation_reasonable=bool(
                rec_dict.get("deterministic_recommendation_reasonable", True)),
            model=self.model,
            prompt_version=PROMPT_VERSION,
        )
