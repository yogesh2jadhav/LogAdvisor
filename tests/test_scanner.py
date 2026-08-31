import os
import textwrap

import pytest

from conftest import FIXTURE_PROJECT
from logadvisor.config import DEFAULT_IGNORE_DIRS
from logadvisor.scanner.java_parser import parse_java_file
from logadvisor.scanner.project_scanner import scan_project

PP = os.path.join(FIXTURE_PROJECT, "src/main/java/com/example/pipeline/PatientProcessor.java")


def test_project_discovery():
    info, java_files = scan_project(FIXTURE_PROJECT, DEFAULT_IGNORE_DIRS)
    assert info.build_system == "Maven"
    assert info.java_version == "17"
    assert info.spark_version == "3.5.1"
    assert "Apache Spark" in info.frameworks
    assert "SLF4J" in info.logging_frameworks
    assert info.java_files == len(java_files) >= 3
    assert info.test_files == 1


def test_parse_methods_and_lines():
    cf = parse_java_file(PP, FIXTURE_PROJECT)
    assert cf.package == "com.example.pipeline"
    assert "PatientProcessor" in cf.classes
    names = {m.name for m in cf.methods}
    assert {"processPatients", "countRecords"} <= names
    m = next(x for x in cf.methods if x.name == "processPatients")
    assert m.start_line < m.end_line
    assert m.class_name == "PatientProcessor"
    assert any("SparkSession" in p or "String" in p for p in m.parameters)


def test_spark_join_filter_write_detected():
    cf = parse_java_file(PP, FIXTURE_PROJECT)
    m = next(x for x in cf.methods if x.name == "processPatients")
    ops = {o.operation_type for o in m.spark_operations}
    assert "JOIN" in ops
    assert "FILTER" in ops
    assert "PARQUET_WRITE" in ops
    assert "PARQUET_READ" in ops
    join = next(o for o in m.spark_operations if o.operation_type == "JOIN")
    assert join.priority == "HIGH"


def test_existing_logging_detected():
    cf = parse_java_file(PP, FIXTURE_PROJECT)
    m = next(x for x in cf.methods if x.name == "processPatients")
    assert len(m.logging_statements) == 1
    assert m.logging_statements[0].level == "INFO"


def test_exception_without_error_logging():
    cf = parse_java_file(PP, FIXTURE_PROJECT)
    m = next(x for x in cf.methods if x.name == "processPatients")
    tc = [e for e in m.exception_boundaries if e.kind == "TRY_CATCH"]
    assert len(tc) == 1
    assert tc[0].has_error_logging is False


def test_exception_with_error_logging(tmp_path):
    src = textwrap.dedent(
        """
        package x;
        class A {
            void go() {
                try { risky(); }
                catch (Exception e) { logger.error("boom {}", e.toString()); }
            }
        }
        """
    )
    f = tmp_path / "A.java"
    f.write_text(src)
    cf = parse_java_file(str(f), str(tmp_path))
    m = cf.methods[0]
    assert m.exception_boundaries[0].has_error_logging is True


def test_sensitive_logging_flagged(tmp_path):
    src = 'package x; class A { void go(Object patient) { logger.info("patient={}", patient); } }'
    f = tmp_path / "A.java"
    f.write_text(src)
    cf = parse_java_file(str(f), str(tmp_path))
    assert cf.methods[0].logging_statements[0].sensitive is True


def test_string_literals_do_not_create_false_ops(tmp_path):
    src = 'package x; class A { String s() { return "call .join( and .filter( here"; } }'
    f = tmp_path / "A.java"
    f.write_text(src)
    cf = parse_java_file(str(f), str(tmp_path))
    assert cf.methods[0].spark_operations == []
