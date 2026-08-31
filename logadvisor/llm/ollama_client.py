"""Minimal Ollama HTTP client (stdlib only, local-first).

Only the pieces the advisor needs: ``/api/tags`` for availability checks and
``/api/generate`` (non-streaming, ``format=json``) for structured output.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .provider import GenerationResult, LLMProvider


class OllamaError(RuntimeError):
    pass


class OllamaClient(LLMProvider):
    name = "ollama"

    def __init__(self, host: str = "http://localhost:11434", timeout: int = 120):
        self.host = host.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self.host}{path}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise OllamaError(f"GET {url} failed: {exc}") from exc

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.host}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise OllamaError(f"POST {url} -> HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise OllamaError(f"POST {url} failed: {exc}") from exc

    # -- public API ----------------------------------------------------------
    def is_available(self) -> bool:
        try:
            self._get("/api/tags")
            return True
        except OllamaError:
            return False

    def list_models(self) -> List[str]:
        data = self._get("/api/tags")
        return [m.get("name", "") for m in data.get("models", [])]

    def has_model(self, model: str) -> bool:
        names = self.list_models()
        if model in names:
            return True
        # tolerate missing ":latest" suffix
        base = model.split(":")[0]
        return any(n == model or n.split(":")[0] == base for n in names)

    def generate(self, model: str, prompt: str, *, system: Optional[str] = None,
                 temperature: float = 0.1, json_format: bool = True) -> GenerationResult:
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system
        if json_format:
            payload["format"] = "json"
        started = time.monotonic()
        data = self._post("/api/generate", payload)
        wall_ms = int((time.monotonic() - started) * 1000)
        total_ms = int(data.get("total_duration", 0) / 1_000_000) or wall_ms
        return GenerationResult(
            text=data.get("response", ""),
            prompt_tokens=int(data.get("prompt_eval_count", 0) or 0),
            output_tokens=int(data.get("eval_count", 0) or 0),
            total_ms=total_ms,
        )
