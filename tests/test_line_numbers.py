"""Regression: line numbers for a method with a multi-line signature.

The regex backend counted newlines from the method body's '{' but used the
method-name line as the base, so every operation in a method whose signature
wrapped across lines was reported several lines too early - often landing on a
comment or the signature itself.
"""
import textwrap

import pytest

from logadvisor.scanner import java_parser as jp
from logadvisor.scanner import treesitter_parser

_SRC = textwrap.dedent("""\
    package com.example;
    import org.apache.spark.sql.Dataset;
    import org.apache.spark.sql.Row;
    class CasingService {
        // line 5
        public Dataset<Row> processCasingData(
                Dataset<Row> casings,
                Dataset<Row> meta,
                String runId) {
            // a plain comment on line 10 - must NOT be reported as an op
            Dataset<Row> active = casings.filter(casings.col("status").equalTo("A"));  // 11
            Dataset<Row> joined = active.join(meta, active.col("id").equalTo(meta.col("id")));  // 12
            logger.info("processing casing data");  // line 13
            joined.write().parquet("/out/casing");  // line 14
            return joined;
        }
    }
""")


@pytest.fixture(params=["regex"] + (["treesitter"] if treesitter_parser.available() else []))
def backend(request):
    jp.set_backend(request.param)
    yield request.param
    jp.set_backend("auto")


def _method(tmp_path):
    f = tmp_path / "CasingService.java"
    f.write_text(_SRC)
    return jp.parse_java_file(str(f), str(tmp_path)).methods[0]


def test_operations_land_on_their_real_lines(tmp_path, backend):
    m = _method(tmp_path)
    at = {op.operation_type: op.line for op in m.spark_operations}
    assert at["FILTER"] == 11
    assert at["JOIN"] == 12
    assert at["PARQUET_WRITE"] == 14
    assert m.logging_statements[0].line == 13
    # nothing should be attributed to the comment line or the signature
    assert all(op.line >= 11 for op in m.spark_operations)


def test_method_span_is_sane(tmp_path, backend):
    m = _method(tmp_path)
    assert m.start_line <= 9          # signature starts at line 6, name on 6
    assert m.end_line >= 16
    assert m.name == "processCasingData"
    assert len(m.parameters) == 3
