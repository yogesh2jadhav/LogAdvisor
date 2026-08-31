"""Lightweight lazy-evaluation / execution-boundary analysis (Plan sections 5 & 10).

Spark transformations are lazy - ``filter`` / ``join`` / ``select`` build a plan
but nothing runs until an *action* (``write`` / ``count`` / ``collect`` / ``save``
/ ``show`` / ``foreach`` / ``take`` / ``first``) forces it.

Given a method body this pass builds a per-statement variable-assignment graph,
finds the action statements, and walks upstream to mark which transformation is
executed where. The advisor then recommends logging the transformation's metrics
*at the execution boundary*, not at the (lazy) definition site.

This is statement/identifier level, not a real SSA dataflow - good enough to tell
"defined here, runs at line N" from "defined but never materialised in this
method".
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from ..models import Method, SparkOperation

# Zero-arg actions: ``.count()`` is a Dataset action; ``functions.count(col)`` is
# not - so require empty parens for the ambiguous names.
_ACTION_RE = re.compile(
    r"\.\s*(?:count|collect|collectAsList|toLocalIterator|isEmpty|first|head)\s*\(\s*\)"
    r"|\.\s*(?:foreach|foreachPartition|take|show|saveAsTextFile|saveAsTable|save)\s*\(",
)
_WRITE_RE = re.compile(r"\.\s*write\s*\(\s*\)")
_ACTION_TYPES = {"SPARK_ACTION", "DATASET_WRITE", "PARQUET_WRITE"}
_READ_TYPES = {"DATASET_READ", "PARQUET_READ"}

_ASSIGN_RE = re.compile(
    r"^\s*(?:final\s+)?(?:[A-Za-z_$][\w$.]*(?:\s*<[^;=]*?>)?(?:\s*\[\s*\])?\s+)?"
    r"([A-Za-z_$][\w$]*)\s*=\s*(.+)$",
    re.DOTALL,
)
_IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")


class _Stmt:
    __slots__ = ("line", "lhs", "refs", "has_action", "text")

    def __init__(self, line: int, lhs: Optional[str], refs: Set[str],
                 has_action: bool, text: str):
        self.line = line
        self.lhs = lhs
        self.refs = refs
        self.has_action = has_action
        self.text = text


def _split_statements(masked: str, base_line: int) -> List[_Stmt]:
    # ``masked`` includes the method's outer braces, so brace depth 1 == method
    # body level. We only split there: a try/if/for block (and any action inside
    # it) stays a single statement whose refs still connect to the upstream vars.
    stmts: List[_Stmt] = []
    depth_paren = depth_brace = 0
    start = 0
    for i, ch in enumerate(masked):
        if ch == "(":
            depth_paren += 1
        elif ch == ")":
            depth_paren -= 1
        elif ch == "{":
            depth_brace += 1
        elif ch == "}":
            depth_brace -= 1
        elif ch == ";" and depth_paren <= 0 and depth_brace <= 1:
            _emit(stmts, masked, base_line, start, i)
            start = i + 1
    _emit(stmts, masked, base_line, start, len(masked))
    return stmts


def _emit(stmts: List["_Stmt"], masked: str, base_line: int, start: int, end: int) -> None:
    seg = masked[start:end]
    stripped = seg.lstrip(" \t\r\n{}")
    if not stripped.strip():
        return
    offset = start + (len(seg) - len(stripped))
    line = base_line + masked.count("\n", 0, offset)
    stmts.append(_mk_stmt(stripped, line))


def _mk_stmt(seg: str, line: int) -> _Stmt:
    seg = seg.strip().lstrip("{}").strip()
    has_action = bool(_ACTION_RE.search(seg) or _WRITE_RE.search(seg))
    m = _ASSIGN_RE.match(seg.strip())
    lhs = m.group(1) if m else None
    rhs = m.group(2) if m else seg
    refs = set(_IDENT_RE.findall(rhs))
    return _Stmt(line, lhs, refs, has_action, seg.strip())


def annotate(method: Method, masked_body: str, base_line: Optional[int] = None) -> None:
    """Populate ``is_action`` / ``lazy`` / ``materialized_at`` on the method's
    Spark operations, in place.

    ``base_line`` is the source line of the first character of ``masked_body``
    (i.e. the method body's opening brace). Defaults to ``method.start_line``
    for callers where the signature and brace share a line.
    """
    if not method.spark_operations:
        return

    stmts = _split_statements(masked_body, base_line if base_line is not None else method.start_line)
    params = {p.split()[-1].strip("[]") for p in method.parameters if p.split()}

    # var -> line where it was (last) assigned
    assign_line: Dict[str, int] = {}
    # line -> set of upstream lines that feed the value produced on that line
    for st in stmts:
        if st.lhs:
            assign_line[st.lhs] = st.line

    def upstream_lines(st: _Stmt, seen: Optional[Set[int]] = None) -> Set[int]:
        seen = seen or set()
        if st.line in seen:
            return seen
        seen.add(st.line)
        for ref in st.refs:
            if ref in assign_line and assign_line[ref] != st.line:
                src = next((s for s in stmts if s.line == assign_line[ref]), None)
                if src:
                    upstream_lines(src, seen)
        return seen

    # every line that a Spark action materialises
    materialisation: Dict[int, int] = {}   # source line -> earliest action line
    for st in stmts:
        if not st.has_action:
            continue
        for ln in upstream_lines(st):
            if ln not in materialisation or st.line < materialisation[ln]:
                materialisation[ln] = st.line

    for op in method.spark_operations:
        if op.operation_type in _ACTION_TYPES:
            op.is_action = True
            op.lazy = False
            op.materialized_at = op.line
            continue
        if op.operation_type in _READ_TYPES:
            continue
        # find the statement this transformation sits on
        host = min((s for s in stmts if s.line <= op.line),
                   key=lambda s: op.line - s.line, default=None)
        if host is None:
            continue
        op.lazy = True
        if host.has_action:
            op.materialized_at = host.line
        else:
            op.materialized_at = materialisation.get(host.line)
