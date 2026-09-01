"""External-I/O boundary detection.

Applies to any Java project (Spark or not): a call that crosses a process
boundary - database, HTTP, filesystem, message broker - is a place where an
operation can fail slowly or return unexpected volume, and is worth a structured
log. Emitted as ``SparkOperation`` records with ``operation_type == "EXTERNAL_IO"``
(the ``spark_operations`` list is really "instrumentation points"); the detail
string names the concrete API.

Patterns are deliberately narrow - concrete constructor / factory / template
calls, not generic verb names - so this stays low-noise.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from ..models import SparkOperation

_PATTERNS: List[Tuple[str, str]] = [
    # --- JDBC / SQL ------------------------------------------------------
    ("jdbc", r"\bDriverManager\s*\.\s*getConnection\s*\("),
    ("jdbc", r"\b\w*[dD]ataSource\s*\.\s*getConnection\s*\("),
    ("jdbc", r"\.\s*(?:executeQuery|executeUpdate|executeBatch)\s*\("),
    ("jdbc", r"\b(?:JdbcTemplate|NamedParameterJdbcTemplate|EntityManager)\b\s*\.\s*\w+\s*\("),
    # --- HTTP ---------------------------------------------------------
    ("http", r"\bHttpClient\s*\.\s*newHttpClient\s*\("),
    ("http", r"\b\w*[hH]ttpClient\s*\.\s*(?:send|sendAsync)\s*\("),
    ("http", r"\b(?:RestTemplate|WebClient|OkHttpClient|CloseableHttpClient)\b"),
    ("http", r"\bHttpClients\s*\.\s*(?:createDefault|custom)\s*\("),
    ("http", r"\bnew\s+(?:[\w.]+\.)?URL\s*\([^;]*?\)\s*\.\s*openConnection\s*\("),
    # --- filesystem -------------------------------------------------
    ("file", r"\bnew\s+(?:[\w.]+\.)?File(?:Input|Output)Stream\s*\("),
    ("file", r"\bnew\s+(?:[\w.]+\.)?File(?:Reader|Writer)\s*\("),
    ("file", r"\bFiles\s*\.\s*(?:newInputStream|newOutputStream|newBufferedReader|"
             r"newBufferedWriter|readAllLines|readAllBytes|readString|write|copy|move|delete)\s*\("),
    # --- messaging -------------------------------------------------
    ("messaging", r"\bnew\s+Kafka(?:Producer|Consumer)\s*\("),
    ("messaging", r"\b(?:KafkaTemplate|JmsTemplate|RabbitTemplate)\b\s*\.\s*\w+\s*\("),
    ("messaging", r"\.\s*(?:send|publish)\s*\(\s*[^)]*(?:topic|queue|exchange)"),
]

_COMPILED = [(kind, re.compile(rx)) for kind, rx in _PATTERNS]


def detect_io(body: str, masked_body: str, start_line: int) -> List[SparkOperation]:
    ops: List[SparkOperation] = []
    lines = body.splitlines()
    seen = set()
    for kind, rx in _COMPILED:
        for m in rx.finditer(masked_body):
            rel = masked_body.count("\n", 0, m.start())
            line = start_line + rel
            if line in seen:
                continue
            seen.add(line)
            snippet = lines[rel].strip()[:240] if rel < len(lines) else ""
            ops.append(SparkOperation("EXTERNAL_IO", line, f"[{kind}] {snippet}", "MEDIUM"))
    ops.sort(key=lambda o: o.line)
    return ops
