"""Phase 9 - exception boundary detection.

Detects try/catch blocks and throw statements inside a method body and records
whether the catch block already performs error-level logging.
"""
from __future__ import annotations

import re
from typing import List

from ..models import ExceptionBoundary

_CATCH_RE = re.compile(r"\bcatch\s*\(([^)]*)\)\s*\{")
_THROW_RE = re.compile(r"\bthrow\s+new\b|\bthrow\s+\w+\s*;")
_ERROR_LOG_RE = re.compile(
    r"\b(?:log|logger|LOG|LOGGER)\s*\.\s*(?:error|warn|fatal|severe)\s*\(",
    re.IGNORECASE,
)


def _match_brace(s: str, open_pos: int) -> int:
    depth = 0
    for i in range(open_pos, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(s) - 1


def detect_exceptions(body: str, masked_body: str, start_line: int) -> List[ExceptionBoundary]:
    out: List[ExceptionBoundary] = []

    for m in _CATCH_RE.finditer(masked_body):
        brace_open = masked_body.index("{", m.end() - 1)
        brace_close = _match_brace(masked_body, brace_open)
        block = body[brace_open:brace_close + 1]
        start = start_line + masked_body.count("\n", 0, m.start())
        end = start_line + masked_body.count("\n", 0, brace_close)
        has_log = bool(_ERROR_LOG_RE.search(block)) or "printStackTrace" in block
        out.append(ExceptionBoundary("TRY_CATCH", start, end, has_log))

    for m in _THROW_RE.finditer(masked_body):
        line = start_line + masked_body.count("\n", 0, m.start())
        # look at preceding ~200 chars for an error log
        ctx = body[max(0, m.start() - 200):m.start()]
        out.append(ExceptionBoundary("THROW", line, line, bool(_ERROR_LOG_RE.search(ctx))))

    out.sort(key=lambda e: e.start_line)
    return out
