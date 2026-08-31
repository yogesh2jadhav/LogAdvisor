"""LLM provider abstraction.

MVP ships only :class:`~logadvisor.llm.ollama_client.OllamaClient`, but the rest
of the code depends on this interface so other local backends can be added later
without touching the analyzer. Cloud providers are intentionally out of scope.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class GenerationResult:
    text: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_ms: int = 0

    def __str__(self) -> str:  # lets callers treat it like the old str return
        return self.text

    def __bool__(self) -> bool:
        return bool(self.text)


class LLMProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def list_models(self) -> List[str]: ...

    @abstractmethod
    def has_model(self, model: str) -> bool: ...

    @abstractmethod
    def generate(self, model: str, prompt: str, *, system: Optional[str] = None,
                 temperature: float = 0.1, json_format: bool = True) -> GenerationResult: ...
