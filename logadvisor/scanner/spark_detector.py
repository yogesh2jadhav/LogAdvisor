"""Phases 3-8 - Spark operation detection.

Operates on the *masked* method body (string literals / comments blanked) so that
call tokens inside strings do not create false positives. Line numbers returned
are absolute (base = the method body's opening brace line).

The tool has no type information, so call names that also exist on JDK types
(``stream().filter(...)``, ``Optional.map(...)``, ``repository.save(entity)``)
would otherwise be reported as Spark operations. Those ambiguous names are only
emitted when there is Spark evidence in scope (``spark_context``); Spark-only
names (``join``, ``groupBy``, ``dropDuplicates``, ``write().parquet`` …) are
always emitted.
"""
from __future__ import annotations

import re
from typing import Dict, List

from ..models import SparkOperation

# --- names that essentially only exist on the Spark API --------------------
_STRONG: Dict[str, tuple] = {
    "JOB_START": (r"\bSparkSession\s*\.\s*builder\s*\(|\bnew\s+JavaSparkContext\b|\bnew\s+SparkContext\b", "HIGH"),
    "DATASET_READ": (r"\bspark\s*\.\s*read\s*\(\s*\)|\b\w*[sS]park\w*\s*\.\s*read\s*\(\s*\)|\bspark\s*\.\s*table\s*\(|\bDataFrameReader\b", "HIGH"),
    "DATASET_WRITE": (r"\b\w+\s*\.\s*write\s*\(\s*\)|\bDataFrameWriter\b|\.\s*saveAsTable\s*\(", "HIGH"),
    "JOIN": (r"\.\s*join\s*\(|\.\s*crossJoin\s*\(", "HIGH"),
    "FILTER": (r"\.\s*where\s*\(", "HIGH"),
    "GROUP_BY": (r"\.\s*groupBy\s*\(|\.\s*groupByKey\s*\(|\.\s*rollup\s*\(|\.\s*cube\s*\(", "HIGH"),
    "AGGREGATION": (r"\.\s*agg\s*\(|\.\s*reduceByKey\s*\(", "HIGH"),
    "DEDUPLICATION": (r"\.\s*dropDuplicates\s*\(", "HIGH"),
    "REPARTITION": (r"\.\s*repartition\s*\(|\.\s*coalesce\s*\(", "MEDIUM"),
    "SORT": (r"\.\s*orderBy\s*\(", "MEDIUM"),
    "UNION": (r"\.\s*unionByName\s*\(", "MEDIUM"),
    "MAP": (r"\.\s*mapPartitions\s*\(", "MEDIUM"),
    "WITH_COLUMN": (r"\.\s*withColumn\s*\(|\.\s*withColumnRenamed\s*\(", "LOW"),
    "SELECT": (r"\.\s*selectExpr\s*\(", "LOW"),
    "SPARK_ACTION": (r"\.\s*saveAsTextFile\s*\(", "MEDIUM"),
}

# --- names shared with JDK / common libraries -> need spark_context -------
_AMBIGUOUS: Dict[str, tuple] = {
    "FILTER": (r"\.\s*filter\s*\(", "HIGH"),
    "AGGREGATION": (r"\.\s*reduce\s*\(", "HIGH"),
    "DEDUPLICATION": (r"\.\s*distinct\s*\(", "HIGH"),
    "SORT": (r"\.\s*sort\s*\(", "MEDIUM"),
    "UNION": (r"\.\s*union\s*\(", "MEDIUM"),
    "MAP": (r"\.\s*map\s*\(|\.\s*flatMap\s*\(", "MEDIUM"),
    "SELECT": (r"\.\s*select\s*\(|\.\s*drop\s*\(", "LOW"),
    "DATASET_WRITE": (r"\.\s*save\s*\(\s*\)", "HIGH"),
    "SPARK_ACTION": (r"\.\s*(?:count|collect|first|take|show|foreach)\s*\(", "MEDIUM"),
}

# Format literals are blanked in the masked body, so parquet is matched on the
# raw body with a narrow pattern that is unlikely to appear inside a real string.
_FORMAT_PATTERNS = {
    "PARQUET_WRITE": re.compile(r"\.\s*write\b[\s\S]{0,200}?\.\s*parquet\s*\(|\.\s*write\b[\s\S]{0,120}?format\s*\(\s*\"parquet\"\s*\)"),
    "PARQUET_READ": re.compile(r"\.\s*read\s*\(\s*\)[\s\S]{0,200}?\.\s*parquet\s*\(|\.\s*read\s*\(\s*\)[\s\S]{0,120}?format\s*\(\s*\"parquet\"\s*\)"),
}

# tokens whose presence in a method body is strong evidence of Spark code
_SPARK_TYPE_RE = re.compile(
    r"\b(Dataset|DataFrame|SparkSession|JavaSparkContext|SparkContext|JavaRDD|"
    r"JavaPairRDD|RelationalGroupedDataset|KeyValueGroupedDataset)\b"
    r"|\bfunctions\s*\.|\borg\.apache\.spark\b"
)

# things that clearly are NOT Spark, sitting just before an ambiguous call
_NON_SPARK_RECEIVER_RE = re.compile(
    r"(?:\.\s*stream\s*\(\s*\)|\.\s*parallelStream\s*\(\s*\)|Optional[.<]|"
    r"\.\s*entrySet\s*\(\s*\)|\.\s*keySet\s*\(\s*\)|\.\s*values\s*\(\s*\)|"
    r"Stream\s*\.|Collectors\s*\.|Arrays\s*\.|Collections\s*\.|IntStream\b|List\s*\.\s*of)"
    r"[\s\S]{0,60}$"
)


def method_has_spark_context(masked_body: str, file_has_spark_import: bool) -> bool:
    return file_has_spark_import or bool(_SPARK_TYPE_RE.search(masked_body))


def detect_spark_operations(body: str, masked_body: str, start_line: int,
                            spark_context: bool = True) -> List[SparkOperation]:
    ops: List[SparkOperation] = []
    lines = body.split("\n")  # keep index consistent with masked_body.count("\n")

    def add(op_type: str, priority: str, char_pos: int, source: str):
        rel_line = source.count("\n", 0, char_pos)
        snippet = lines[rel_line].strip() if rel_line < len(lines) else ""
        ops.append(SparkOperation(op_type, start_line + rel_line, snippet[:240], priority))

    for op_type, (pattern, priority) in _STRONG.items():
        for m in re.finditer(pattern, masked_body):
            add(op_type, priority, m.start(), masked_body)

    if spark_context:
        for op_type, (pattern, priority) in _AMBIGUOUS.items():
            for m in re.finditer(pattern, masked_body):
                prefix = masked_body[max(0, m.start() - 80):m.start()]
                if _NON_SPARK_RECEIVER_RE.search(prefix):
                    continue
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

    # de-duplicate (strong + ambiguous can both match e.g. reduce/reduceByKey)
    seen = set()
    uniq = []
    for o in sorted(ops, key=lambda o: (o.line, o.operation_type)):
        key = (o.line, o.operation_type)
        if key not in seen:
            seen.add(key)
            uniq.append(o)
    return uniq
