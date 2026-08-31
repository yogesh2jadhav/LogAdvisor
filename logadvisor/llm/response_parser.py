"""Validate + repair structured LLM responses."""
from __future__ import annotations

import json
import re
from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

_PRIORITIES = {"HIGH", "MEDIUM", "LOW"}


class LLMRecommendation(BaseModel):
    recommend: bool = True
    priority: str = "MEDIUM"
    category: str = ""
    reason: str = ""
    recommended_fields: List[str] = Field(default_factory=list)
    do_not_log: List[str] = Field(default_factory=list)
    ai_usefulness: str = "MEDIUM"
    ai_use_cases: List[str] = Field(default_factory=list)
    deterministic_recommendation_reasonable: bool = True

    @field_validator("priority", "ai_usefulness", mode="before")
    @classmethod
    def _norm_priority(cls, v):
        if isinstance(v, str) and v.upper() in _PRIORITIES:
            return v.upper()
        return "MEDIUM"

    @field_validator("recommended_fields", "do_not_log", "ai_use_cases", mode="before")
    @classmethod
    def _coerce_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [s.strip() for s in re.split(r"[,\n;]", v) if s.strip()]
        if isinstance(v, list):
            return [str(x) for x in v]
        return []


def _extract_json_blob(text: str) -> Optional[str]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def parse_response(raw: str) -> LLMRecommendation:
    """Raises ValueError if the response cannot be salvaged."""
    blob = _extract_json_blob(raw)
    if not blob:
        raise ValueError("no JSON object found in LLM response")
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        # light repair: strip trailing commas
        repaired = re.sub(r",\s*([}\]])", r"\1", blob)
        data = json.loads(repaired)  # may raise -> caller handles
    if not isinstance(data, dict):
        raise ValueError("LLM JSON is not an object")
    try:
        return LLMRecommendation(**data)
    except ValidationError as exc:  # pragma: no cover - pydantic is permissive here
        raise ValueError(f"schema validation failed: {exc}") from exc
