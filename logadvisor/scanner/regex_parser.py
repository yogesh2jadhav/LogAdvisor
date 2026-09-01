"""Phase 2 - Java source analysis (regex + brace-matching fallback backend).

A pragmatic, dependency-free Java structural parser. It is deliberately *not* a
full grammar: it masks comments and string/char literals, then uses brace
matching to recover packages, imports, type declarations and method bodies with
accurate line numbers. Regex is used only for signatures, never for body
semantics.

This is the fallback backend. When ``tree-sitter`` + ``tree-sitter-java`` are
installed, :mod:`logadvisor.scanner.java_parser` prefers
:mod:`logadvisor.scanner.treesitter_parser` and only drops here on failure.
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import List, Optional, Tuple

from ..models import CodeFile, ExceptionBoundary, Method
from .dataflow import annotate as annotate_dataflow
from .exception_detector import detect_exceptions
from .logging_detector import detect_logging
from .spark_detector import detect_spark_operations

_JAVA_KEYWORDS_BEFORE_METHOD = {
    "if", "for", "while", "switch", "catch", "synchronized", "return", "new",
    "else", "do", "try", "finally", "assert", "throw",
}
_MODIFIERS = {
    "public", "private", "protected", "static", "final", "abstract",
    "synchronized", "native", "default", "strictfp", "transient", "volatile",
}


def _mask_literals_and_comments(src: str) -> str:
    """Replace comment and string/char literal *contents* with spaces, keeping
    length and newlines so offsets/line numbers are preserved."""
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        two = src[i:i + 2]
        if two == "//":
            while i < n and src[i] != "\n":
                out[i] = " "
                i += 1
        elif two == "/*":
            out[i] = out[i + 1] = " "
            i += 2
            while i < n and src[i:i + 2] != "*/":
                if src[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = out[i + 1] = " "
                i += 2
        elif c in "\"'":
            quote = c
            # text blocks """ ... """
            if quote == '"' and src[i:i + 3] == '"""':
                out[i] = out[i + 1] = out[i + 2] = " "
                i += 3
                while i < n and src[i:i + 3] != '"""':
                    if src[i] != "\n":
                        out[i] = " "
                    i += 1
                if i < n:
                    out[i] = out[i + 1] = out[i + 2] = " "
                    i += 3
                continue
            out[i] = " "
            i += 1
            while i < n and src[i] != quote:
                if src[i] == "\\" and i + 1 < n:
                    out[i] = " "
                    i += 1
                if src[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = " "
                i += 1
        else:
            i += 1
    return "".join(out)


def _line_of(src: str, pos: int) -> int:
    return src.count("\n", 0, pos) + 1


def _match_brace(masked: str, open_pos: int) -> int:
    depth = 0
    for i in range(open_pos, len(masked)):
        ch = masked[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(masked) - 1


def _match_paren(masked: str, open_pos: int) -> int:
    depth = 0
    for i in range(open_pos, len(masked)):
        ch = masked[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return len(masked) - 1


_TYPE_DECL_RE = re.compile(r"\b(class|interface|enum|record)\s+([A-Za-z_$][\w$]*)")
_METHOD_HINT_RE = re.compile(r"([A-Za-z_$][\w$]*)\s*\(")
_PARAM_SPLIT_RE = re.compile(r",(?![^<>()]*[>)])")


def _split_params(param_src: str) -> List[str]:
    param_src = param_src.strip()
    if not param_src:
        return []
    parts = _PARAM_SPLIT_RE.split(param_src)
    cleaned = []
    for p in parts:
        p = re.sub(r"\s+", " ", p).strip()
        p = re.sub(r"^(final|@\w+(\([^)]*\))?)\s+", "", p).strip()
        if p:
            cleaned.append(p)
    return cleaned


def _preceding_annotations(masked: str, start: int) -> List[str]:
    head = masked[max(0, start - 400):start]
    return re.findall(r"@([A-Za-z_$][\w$.]*)", head)


def _enclosing_type(type_spans: List[Tuple[int, int, str]], pos: int) -> str:
    best = None
    for s, e, name in type_spans:
        if s <= pos <= e:
            if best is None or (e - s) < (best[1] - best[0]):
                best = (s, e, name)
    return best[2] if best else "<anonymous>"


def parse_java_file(path: str, project_root: str) -> CodeFile:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        src = fh.read()
    masked = _mask_literals_and_comments(src)
    rel = os.path.relpath(path, project_root)
    file_hash = hashlib.sha256(src.encode("utf-8", "replace")).hexdigest()

    is_test = "/src/test/" in rel.replace("\\", "/") or rel.lower().endswith(("test.java", "tests.java"))

    cf = CodeFile(
        path=rel,
        file_hash=file_hash,
        line_count=src.count("\n") + 1,
        is_test=is_test,
    )

    m = re.search(r"^\s*package\s+([\w.]+)\s*;", masked, re.MULTILINE)
    if m:
        cf.package = m.group(1)
    cf.imports = re.findall(r"^\s*import\s+(?:static\s+)?([\w.*]+)\s*;", masked, re.MULTILINE)

    # ---- type declarations (with body spans) ------------------------------
    type_spans: List[Tuple[int, int, str]] = []
    for tm in _TYPE_DECL_RE.finditer(masked):
        kind, name = tm.group(1), tm.group(2)
        brace = masked.find("{", tm.end())
        if brace == -1:
            continue
        end = _match_brace(masked, brace)
        type_spans.append((tm.start(), end, name))
        if kind == "interface":
            cf.interfaces.append(name)
        else:
            cf.classes.append(name)

    # ---- methods --------------------------------------------------------
    seen: set = set()
    for hint in _METHOD_HINT_RE.finditer(masked):
        name = hint.group(1)
        if name in _JAVA_KEYWORDS_BEFORE_METHOD or name in _MODIFIERS:
            continue
        paren_open = masked.index("(", hint.start())
        paren_close = _match_paren(masked, paren_open)
        # after params: optional 'throws ...' then '{' (definition) — skip ';' (abstract)
        after = masked[paren_close + 1:paren_close + 400]
        am = re.match(r"\s*(?:throws\s+([\w.,\s]+?))?\s*\{", after)
        if not am:
            continue
        throws_clause = (am.group(1) or "").strip()
        brace_open = paren_close + 1 + after.index("{", am.start())
        # crude signature sanity: token before name should look like a type/modifier
        before = masked[max(0, hint.start() - 120):hint.start()].strip()
        before_tok = re.findall(r"[A-Za-z_$][\w$<>\[\].,?\s]*$", before)
        if not before_tok or before.endswith("."):
            continue
        if before.endswith("=") or before.endswith("return"):
            continue

        brace_close = _match_brace(masked, brace_open)
        key = (brace_open, brace_close)
        if key in seen:
            continue
        seen.add(key)

        start_line = _line_of(src, hint.start())
        end_line = _line_of(src, brace_close)
        sig_before = re.sub(r"\s+", " ", before).strip()
        ret = "void"
        rm = re.search(r"([\w$][\w$<>\[\],.?\s]*?)\s*$", sig_before)
        if rm:
            ret_candidate = rm.group(1).strip()
            ret_candidate = " ".join(t for t in ret_candidate.split() if t not in _MODIFIERS)
            ret = ret_candidate or "void"
        if name == _enclosing_type(type_spans, hint.start()):
            ret = "<constructor>"

        params = _split_params(src[paren_open + 1:paren_close])
        body = src[brace_open:brace_close + 1]
        method = Method(
            name=name,
            class_name=_enclosing_type(type_spans, hint.start()),
            start_line=start_line,
            end_line=end_line,
            return_type=ret,
            parameters=params,
            annotations=_preceding_annotations(masked, hint.start()),
        )
        masked_body = masked[brace_open:brace_close + 1]
        # the detectors count newlines from the start of masked_body (the '{'),
        # so their base line must be the line of the '{', NOT the method name -
        # these differ whenever the signature spans multiple lines.
        body_line = _line_of(src, brace_open)
        method.spark_operations = detect_spark_operations(body, masked_body, body_line)
        method.logging_statements = detect_logging(body, masked_body, body_line)
        method.exception_boundaries = detect_exceptions(body, masked_body, body_line)

        if throws_clause:
            has_err = any(ls.level in ("ERROR", "WARN") for ls in method.logging_statements) \
                or any(eb.has_error_logging for eb in method.exception_boundaries)
            method.exception_boundaries.append(
                ExceptionBoundary("THROWS", start_line, start_line, has_err)
            )

        annotate_dataflow(method, masked_body, base_line=body_line)
        cf.methods.append(method)

    cf.methods.sort(key=lambda x: x.start_line)
    return cf
