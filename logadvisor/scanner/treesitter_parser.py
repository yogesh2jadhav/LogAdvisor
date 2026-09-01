"""Phase 2 - Java source analysis (tree-sitter backend).

Preferred over :mod:`logadvisor.scanner.regex_parser` when ``tree-sitter`` and
``tree-sitter-java`` are installed. Produces the same :class:`CodeFile` contract;
the Spark / logging / exception / dataflow detectors run unchanged on the exact
method-body slices tree-sitter identifies.

Install:  pip install "ai-ready-log-advisor[treesitter]"

All slicing is done on the UTF-8 byte buffer (tree-sitter offsets are byte
offsets) and decoded per-slice, so non-ASCII source is handled correctly.
"""
from __future__ import annotations

import functools
import hashlib
import os
from typing import List

from ..models import CodeFile, ExceptionBoundary, Method
from .dataflow import annotate as annotate_dataflow
from .exception_detector import detect_exceptions
from .io_detector import detect_io
from .logging_detector import detect_logging
from .spark_detector import detect_spark_operations, method_has_spark_context

_TYPE_DECL = {
    "class_declaration", "interface_declaration", "enum_declaration",
    "record_declaration", "annotation_type_declaration",
}
_METHOD_DECL = {
    "method_declaration", "constructor_declaration", "compact_constructor_declaration",
}
_LITERAL_NODES = {
    "string_literal", "character_literal", "line_comment", "block_comment", "text_block",
}


@functools.lru_cache(maxsize=1)
def _language():
    import tree_sitter_java
    from tree_sitter import Language

    return Language(tree_sitter_java.language())


@functools.lru_cache(maxsize=1)
def available() -> bool:
    try:
        _language()
        return True
    except Exception:
        return False


def _parser():
    from tree_sitter import Parser

    lang = _language()
    try:
        return Parser(lang)                       # tree-sitter >= 0.22
    except TypeError:                             # pragma: no cover - old API
        p = Parser()
        p.set_language(lang)
        return p


# ---------------------------------------------------------------------------
def _txt(node) -> str:
    return node.text.decode("utf-8", "replace") if node is not None else ""


def _line(node) -> int:
    return node.start_point[0] + 1


def _end_line(node) -> int:
    return node.end_point[0] + 1


def _mask(src_bytes: bytes, root) -> bytes:
    """Blank string/char literal and comment spans (keep newlines)."""
    out = bytearray(src_bytes)
    stack = [root]
    while stack:
        n = stack.pop()
        if n.type in _LITERAL_NODES:
            for i in range(n.start_byte, n.end_byte):
                if out[i] not in (0x0A, 0x0D):
                    out[i] = 0x20
            continue
        stack.extend(n.children)
    return bytes(out)


def _annotations(node) -> List[str]:
    mods = node.child_by_field_name("modifiers")
    if mods is None:
        return []
    out = []
    for c in mods.children:
        if c.type in ("annotation", "marker_annotation"):
            name = c.child_by_field_name("name")
            if name is not None:
                out.append(_txt(name).lstrip("@"))
    return out


def _params(node) -> List[str]:
    plist = node.child_by_field_name("parameters")
    if plist is None:
        return []
    return [
        " ".join(_txt(c).split())
        for c in plist.children
        if c.type in ("formal_parameter", "spread_parameter", "receiver_parameter")
    ]


def _has_throws(node) -> bool:
    return any(c.type == "throws" for c in node.children)


def _add_method(node, src_bytes: bytes, masked: bytes, cf: CodeFile, class_name: str,
                file_has_spark_import: bool = False) -> None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return
    body = node.child_by_field_name("body")

    if node.type == "method_declaration":
        type_node = node.child_by_field_name("type")
        ret = " ".join(_txt(type_node).split()) if type_node is not None else "void"
    else:
        ret = "<constructor>"

    method = Method(
        name=_txt(name_node),
        class_name=class_name or "<anonymous>",
        start_line=_line(node),
        end_line=_end_line(body) if body is not None else _end_line(node),
        return_type=ret,
        parameters=_params(node),
        annotations=_annotations(node),
    )

    if body is not None:
        b0, b1 = body.start_byte, body.end_byte
        body_txt = src_bytes[b0:b1].decode("utf-8", "replace")
        masked_body = masked[b0:b1].decode("utf-8", "replace")
        base_line = _line(body)
        spark_ctx = method_has_spark_context(masked_body, file_has_spark_import)
        method.spark_operations = detect_spark_operations(body_txt, masked_body, base_line, spark_ctx)
        method.spark_operations += detect_io(body_txt, masked_body, base_line)
        method.spark_operations.sort(key=lambda o: o.line)
        method.logging_statements = detect_logging(body_txt, masked_body, base_line)
        method.exception_boundaries = detect_exceptions(body_txt, masked_body, base_line)

    if _has_throws(node):
        has_err = any(ls.level in ("ERROR", "WARN") for ls in method.logging_statements) \
            or any(eb.has_error_logging for eb in method.exception_boundaries)
        method.exception_boundaries.append(
            ExceptionBoundary("THROWS", method.start_line, method.start_line, has_err)
        )

    if body is not None:
        annotate_dataflow(method, masked_body, base_line=base_line)

    cf.methods.append(method)


def _collect(node, src_bytes: bytes, masked: bytes, cf: CodeFile, class_name: str,
             spark_import: bool) -> None:
    if node.type in _TYPE_DECL:
        name_node = node.child_by_field_name("name")
        name = _txt(name_node) if name_node is not None else "<anon>"
        (cf.interfaces if node.type == "interface_declaration" else cf.classes).append(name)
        for c in node.children:
            _collect(c, src_bytes, masked, cf, name, spark_import)
        return
    if node.type in _METHOD_DECL:
        _add_method(node, src_bytes, masked, cf, class_name, spark_import)
        return
    for c in node.children:
        _collect(c, src_bytes, masked, cf, class_name, spark_import)


def parse_java_file(path: str, project_root: str) -> CodeFile:
    with open(path, "rb") as fh:
        src_bytes = fh.read()
    tree = _parser().parse(src_bytes)
    root = tree.root_node
    masked = _mask(src_bytes, root)

    rel = os.path.relpath(path, project_root)
    cf = CodeFile(
        path=rel,
        file_hash=hashlib.sha256(src_bytes).hexdigest(),
        line_count=src_bytes.count(b"\n") + 1,
        is_test="/src/test/" in rel.replace("\\", "/")
        or rel.lower().endswith(("test.java", "tests.java")),
    )

    for c in root.children:
        if c.type == "package_declaration":
            for n in c.children:
                if n.type in ("scoped_identifier", "identifier"):
                    cf.package = _txt(n)
        elif c.type == "import_declaration":
            for n in c.children:
                if n.type in ("scoped_identifier", "identifier"):
                    cf.imports.append(_txt(n))

    spark_import = any("org.apache.spark" in imp for imp in cf.imports)
    _collect(root, src_bytes, masked, cf, "", spark_import)
    cf.methods.sort(key=lambda m: m.start_line)
    return cf
