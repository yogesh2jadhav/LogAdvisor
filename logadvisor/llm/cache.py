"""File-based LLM response cache.

Key = sha256(file_hash + method code hash + rule_id + prompt_version + model).
Stored as ``cache/<hash>.json``. Changing model / prompt / rule invalidates it.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Optional


class LLMCache:
    def __init__(self, cache_dir: str, enabled: bool = True):
        self.dir = cache_dir
        self.enabled = enabled
        if enabled:
            os.makedirs(cache_dir, exist_ok=True)

    @staticmethod
    def key(*, file_hash: str, method_code: str, rule_id: str,
            prompt_version: str, model: str) -> str:
        h = hashlib.sha256()
        h.update(file_hash.encode())
        h.update(hashlib.sha256(method_code.encode("utf-8", "replace")).hexdigest().encode())
        h.update(rule_id.encode())
        h.update(prompt_version.encode())
        h.update(model.encode())
        return h.hexdigest()

    def _path(self, key: str) -> str:
        return os.path.join(self.dir, f"{key}.json")

    def get(self, key: str) -> Optional[dict]:
        if not self.enabled:
            return None
        p = self._path(key)
        if not os.path.isfile(p):
            return None
        try:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def put(self, key: str, value: dict) -> None:
        if not self.enabled:
            return
        try:
            with open(self._path(key), "w", encoding="utf-8") as fh:
                json.dump(value, fh, indent=2)
        except OSError:
            pass
