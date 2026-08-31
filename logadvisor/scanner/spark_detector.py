"""Phases 3-8 - Spark operation detection.

Operates on the *masked* method body (string literals / comments blanked) so that
call tokens inside strings do not create false positives. Line numbers returned
are absolute (``method.start_line`` based).
"""
from __future__ import annotations

import re
from typing import Dict, List

from ..models import SparkOperation

# operation_type -> (regex on masked body, deterministic priority)
_PATTERNS: Dict[str, tuple] = {
    "JOB_START": (r"\bSparkSession\s*\.\s*builder\s*\(|\bnew\s+JavaSparkContext\b|\bnew\s+SparkContext\b", "HIGH"),
    "DATASET_READ": (r"\b\w+\s*\.\s*read\s*\(\s*\)|\bspark\s*\.\s*table\s*\(|\bDataFrameReader\b", "HIGH"),
    "DATASET_WRITE": (r"\b\w+\s*\.\s*write\s*\(\s*\)|\bDataFrameWriter\b|\.\s*save\s*\(|\.\s*saveAsTable\s*\(", "HIGH"),
    "JOIN": (r"\.\s*join\s*\(|\.\s*crossJoin\s*\(", "HIGH"),
    "FILTER": (r"\.\s*filter\s*\(|\.\s*where\s*\(", "HIGH"),
    "GROUP_BY": (r"\.\s*groupBy\s*\(|\.\s*groupByKey\s*\(|\.\s*rollup\s*\(|\.\s*cube\s*\(", "HIGH"),
    "AGGREGATION": (r"\.\s*agg\s*\(|\.\s*reduce\s*\(|\.\s*reduceByKey\s*\(", "HIGH"),
    "DEDUPLICATION": (r"\.\s*dropDuplicates\s*\(|\.\s*distinct\s*\(", "HIGH"),
    "REPARTITION": (r"\.\s*repartition\s*\(|\.\s*coalesce\s*\(", "MEDIUM"),
    "SORT": (r"\.\s*sort\s*\(|\.\s*orderBy\s*\(", "MEDIUM"),
    "UNION": (r"\.\s*union\s*\(|\.\s*unionByName\s*\(", "MEDIUM"),
    "MAP": (r"\.\s*map\s*\(|\.\s*flatMap\s*\(|\.\s*mapPartitions\s*\(", "MEDIUM"),
    "WITH_COLUMN": (r"\.\s*withColumn\s*\(|\.\s*withColumnRenamed\s*\(", "LOW"),
    "SELECT": (r"\.\s*select\s*\(|\.\s*selectExpr\s*\(|\.\s*drop\s*\(", "LOW"),
    "SPARK_ACTION": (r"\.\s*(?:count|collect|first|take|show|foreach|saveAsTextFile)\s*\(", "MEDIUM"),
}

# Format literals are blanked in the masked body, so parquet is matched on the
# raw body with a narrow pattern that is unlikely to appear inside a real string.
_FORMAT_PATTERNS = {
    "PARQUET_WRITE": re.compile(r"\.\s*write\b[\s\S]{0,200}?\.\s*parquet\s*\(|\.\s*write\b[\s\S]{0,120}?format\s*\(\s*\"parquet\"\s*\)"),
    "PARQUET_READ": re.compile(r"\.\s*read\s*\(\s*\)[\s\S]{0,200}?\.\s*parquet\s*\(|\.\s*read\s*\(\s*\)[\s\S]{0,120}?format\s*\(\s*\"parquet\"\s*\)"),
}


def detect_spark_operations(body: str, masked_body: str, start_line: int) -> List[SparkOperation]:
    ops: List[SparkOperation] = []
    lines = body.splitlines()

    def add(op_type: str, priority: str, char_pos: int, source: str):
        rel_line = source.count("\n", 0, char_pos)
        snippet = lines[rel_line].strip() if rel_line < len(lines) else ""
        ops.append(SparkOperation(op_type, start_line + rel_line, snippet[:240], priority))

    for op_type, (pattern, priority) in _PATTERNS.items():
        for m in re.finditer(pattern, masked_body):
            add(op_type, priority, m.start(), masked_body)

    for op_type, rx in _FORMAT_PATTERNS.items():
        for m in rx.finditer(body):
            add(op_type, "HIGH", m.start(), body)

    # a parquet read/write also trips the generic DATASET_READ/WRITE pattern on
    # the same line - keep only the more specific one.
    parquet_read_lines = {o.line for o in ops if o.operation_type == "PARQUET_READ"}
    parquet_write_lines = {o.line for o in ops if o.operation_type == "PARQUET_WRITE"}
    ops = [
        o for o in ops
        if not (o.operation_type == "DATASET_READ" and o.line in parquet_read_lines)
        and not (o.operation_type == "DATASET_WRITE" and o.line in parquet_write_lines)
    ]

    ops.sort(key=lambda o: (o.line, o.operation_type))
    return ops
