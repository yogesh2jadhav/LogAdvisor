"""Java parser dispatcher.

Prefers the tree-sitter backend when available, falls back to the dependency-free
regex/brace parser. Both return the same :class:`~logadvisor.models.CodeFile`.

Backend selection (first match wins):
  1. explicit override via ``set_backend(...)`` or ``$LOGADVISOR_PARSER``
     (``treesitter`` | ``regex`` | ``auto``)
  2. tree-sitter if importable
  3. regex fallback
"""
from __future__ import annotations

import os
from typing import Optional

from ..models import CodeFile
from . import regex_parser, treesitter_parser

_VALID = {"auto", "treesitter", "regex"}
_preferred = os.environ.get("LOGADVISOR_PARSER", "auto").strip().lower()
if _preferred not in _VALID:
    _preferred = "auto"


def set_backend(name: str) -> None:
    """'auto' | 'treesitter' | 'regex'. Invalid values fall back to 'auto'."""
    global _preferred
    _preferred = name.strip().lower() if name and name.strip().lower() in _VALID else "auto"


def active_backend() -> str:
    """The backend that would be used right now."""
    if _preferred == "regex":
        return "regex"
    if _preferred == "treesitter":
        return "treesitter" if treesitter_parser.available() else "regex"
    return "treesitter" if treesitter_parser.available() else "regex"


def parse_java_file(path: str, project_root: str) -> CodeFile:
    backend = active_backend()
    if backend == "treesitter":
        try:
            return treesitter_parser.parse_java_file(path, project_root)
        except Exception:
            if _preferred == "treesitter":
                raise
            # fall through to regex on any tree-sitter failure in auto mode
    return regex_parser.parse_java_file(path, project_root)
