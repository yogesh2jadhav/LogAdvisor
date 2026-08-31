"""Self-contained HTML viewer for the advisory report.

Writes a single file with the enriched report JSON embedded. No network, no
external assets - it opens straight from disk.
"""
from __future__ import annotations

import json
import os

from ..models import ScanResult
from .tree import build_report_document

_TEMPLATE = os.path.join(os.path.dirname(__file__), "viewer.html")


def write_html_report(result: ScanResult, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    with open(_TEMPLATE, "r", encoding="utf-8") as fh:
        template = fh.read()

    doc = build_report_document(result)
    payload = json.dumps(doc).replace("<", "\\u003c").replace("\u2028", " ").replace("\u2029", " ")
    html = template.replace("/*__REPORT_DATA__*/null", payload)

    path = os.path.join(out_dir, "logging_advisory_report.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return path
