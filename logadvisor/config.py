"""Configuration loading and defaults."""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

DEFAULT_IGNORE_DIRS: List[str] = [
    ".git", "target", "build", ".idea", ".vscode", "node_modules",
    ".venv", "venv", "logs", "generated", "out", "bin", ".gradle",
]

DEFAULT_CONFIG: Dict[str, Any] = {
    "scan": {
        "ignore_dirs": DEFAULT_IGNORE_DIRS,
        "include_globs": [],          # optional extra include patterns
        "exclude_globs": [],
        "parser": "auto",             # auto | treesitter | regex
    },
    "llm": {
        "enabled": True,
        "provider": "ollama",
        "host": "http://localhost:11434",
        "model": "qwen3-coder:30b",
        "temperature": 0.1,
        "timeout_seconds": 120,
        "max_retries": 1,
        "cache_enabled": True,
        "priority": "high",           # high|medium|low : minimum priority sent to LLM
        "limit": 0,                   # 0 == no limit
    },
    "privacy": {
        "allow_external_llm": False,
        "scan_patient_data": False,
        "mask_secrets": True,
    },
    "database": {
        "path": ".ai-ready-log-advisor/advisor.db",
    },
    "cache": {
        "dir": ".ai-ready-log-advisor/cache",
    },
    "output": {
        "dir": "logging-report",
    },
}

# Hosts considered "local" when privacy.allow_external_llm is False.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal"}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Config:
    data: Dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULT_CONFIG))

    # convenience accessors ---------------------------------------------------
    @property
    def scan(self) -> Dict[str, Any]:
        return self.data["scan"]

    @property
    def llm(self) -> Dict[str, Any]:
        return self.data["llm"]

    @property
    def privacy(self) -> Dict[str, Any]:
        return self.data["privacy"]

    @property
    def database(self) -> Dict[str, Any]:
        return self.data["database"]

    @property
    def cache(self) -> Dict[str, Any]:
        return self.data["cache"]

    @property
    def output(self) -> Dict[str, Any]:
        return self.data["output"]

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        cfg = cls()
        candidates = []
        if path:
            candidates.append(path)
        else:
            candidates += [
                os.path.join(os.getcwd(), "config", "application.yaml"),
                os.path.join(os.getcwd(), "application.yaml"),
            ]
        for c in candidates:
            if c and os.path.isfile(c):
                with open(c, "r", encoding="utf-8") as fh:
                    loaded = yaml.safe_load(fh) or {}
                cfg.data = _deep_merge(cfg.data, loaded)
                break
        return cfg

    def apply_overrides(self, **overrides: Any) -> None:
        """Apply CLI overrides (only non-None values)."""
        m = self.data
        if overrides.get("model"):
            m["llm"]["model"] = overrides["model"]
        if overrides.get("host"):
            m["llm"]["host"] = overrides["host"]
        if overrides.get("no_llm"):
            m["llm"]["enabled"] = False
        if overrides.get("output"):
            m["output"]["dir"] = overrides["output"]
        if overrides.get("database"):
            m["database"]["path"] = overrides["database"]
        if overrides.get("llm_priority"):
            m["llm"]["priority"] = overrides["llm_priority"]
        if overrides.get("llm_limit") is not None:
            m["llm"]["limit"] = overrides["llm_limit"]
        if overrides.get("include"):
            m["scan"]["include_globs"] = list(overrides["include"])
        if overrides.get("exclude"):
            m["scan"]["ignore_dirs"] = m["scan"]["ignore_dirs"] + list(overrides["exclude"])
        if overrides.get("parser"):
            m["scan"]["parser"] = overrides["parser"]

    def validate_llm_endpoint(self) -> None:
        """Enforce privacy.allow_external_llm == False -> local host only."""
        if self.privacy.get("allow_external_llm"):
            return
        from urllib.parse import urlparse

        host = urlparse(self.llm["host"]).hostname or ""
        if host not in LOCAL_HOSTS:
            raise ValueError(
                f"LLM host '{host}' is not local and privacy.allow_external_llm is "
                f"false. Refusing to run LLM analysis. Use --no-llm or a local host."
            )
