"""Phases 10-11 - existing logging detection and structured-logging classification."""
from __future__ import annotations

import re
from typing import List

from ..models import LoggingStatement
from ..security import looks_like_sensitive_log

_LOGGER_CALL_RE = re.compile(
    r"\b(?:log|logger|LOG|LOGGER|[a-zA-Z_]*[lL]og(?:ger)?)\s*\.\s*"
    r"(info|warn|warning|error|debug|trace|fatal|severe|fine|finer|finest)\s*\(",
    re.MULTILINE,
)

_LEVEL_MAP = {
    "info": "INFO", "warn": "WARN", "warning": "WARN", "error": "ERROR",
    "fatal": "ERROR", "severe": "ERROR", "debug": "DEBUG", "fine": "DEBUG",
    "finer": "DEBUG", "finest": "TRACE", "trace": "TRACE",
}


def _match_paren(s: str, open_pos: int) -> int:
    depth = 0
    for i in range(open_pos, len(s)):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return len(s) - 1


def _logger_type(call_text: str) -> str:
    t = call_text.lower()
    if "log4j" in t:
        return "log4j2"
    return "unknown"


def detect_logging(body: str, masked_body: str, start_line: int) -> List[LoggingStatement]:
    stmts: List[LoggingStatement] = []
    lines = body.splitlines()
    for m in _LOGGER_CALL_RE.finditer(masked_body):
        level = _LEVEL_MAP.get(m.group(1).lower(), "INFO")
        paren_open = masked_body.index("(", m.end() - 1)
        paren_close = _match_paren(masked_body, paren_open)
        rel_line = masked_body.count("\n", 0, m.start())
        abs_line = start_line + rel_line

        raw_args = body[paren_open + 1:paren_close]
        # first argument = message (string literal or format string)
        msg_match = re.match(r'\s*("(?:[^"\\]|\\.)*")', raw_args)
        message = msg_match.group(1) if msg_match else raw_args.strip().split(",")[0]
        rest = raw_args[msg_match.end():] if msg_match else ""

        structured = ("{}" in message) or bool(re.search(r'\w+\s*=\s*(\{\}|"|\+)', message)) \
            or bool(re.search(r"\b\w+Id\b|\brunId\b|\bkv\(|\bStructuredArguments\b", raw_args))
        sensitive = looks_like_sensitive_log(message, rest)

        stmts.append(LoggingStatement(
            line=abs_line,
            level=level,
            logger_type="unknown",
            message_pattern=re.sub(r'"(?:[^"\\]|\\.)*"',
                                   lambda mm: mm.group(0) if len(mm.group(0)) < 80 else '"..."',
                                   message)[:200],
            structured=structured,
            sensitive=sensitive,
        ))
    stmts.sort(key=lambda s: s.line)
    return stmts
