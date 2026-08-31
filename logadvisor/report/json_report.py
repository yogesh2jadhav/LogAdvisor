from __future__ import annotations

import json
import os

from ..models import ScanResult
from .tree import build_report_document


def write_json_report(result: ScanResult, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "logging_advisory_report.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(build_report_document(result), fh, indent=2)
    return path
