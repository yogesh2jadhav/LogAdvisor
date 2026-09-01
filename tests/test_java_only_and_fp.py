"""Fewer false positives on JDK types + plain-Java project support."""
import textwrap

import pytest

from logadvisor.analyzer import run_scan
from logadvisor.config import Config
from logadvisor.db.database import Database
from logadvisor.report import build_report_document, write_markdown_report
from logadvisor.rules.rule_engine import RuleEngine
from logadvisor.scanner import java_parser as jp
from logadvisor.scanner import treesitter_parser
from logadvisor.scoring import _SPARK_ONLY_BUCKETS


@pytest.fixture(params=["regex"] + (["treesitter"] if treesitter_parser.available() else []))
def backend(request):
    jp.set_backend(request.param)
    yield
    jp.set_backend("auto")


def _parse(tmp_path, src, name="A.java"):
    f = tmp_path / name
    f.write_text(textwrap.dedent(src))
    return jp.parse_java_file(str(f), str(tmp_path))


# --- false positives on JDK types ------------------------------------
def test_java_stream_calls_are_not_spark(tmp_path, backend):
    cf = _parse(tmp_path, """
        package x;
        import java.util.List;
        import java.util.stream.Collectors;
        class Svc {
            List<String> names(List<Order> orders) {
                return orders.stream()
                    .filter(o -> o.active())
                    .map(Order::name)
                    .sorted()
                    .distinct()
                    .collect(Collectors.toList());
            }
        }
    """)
    assert cf.methods[0].spark_operations == []


def test_spring_data_save_is_not_a_dataset_write(tmp_path, backend):
    cf = _parse(tmp_path, """
        package x;
        class OrderRepo {
            void store(Order o) { repository.save(o); }
        }
    """)
    assert not any(op.operation_type == "DATASET_WRITE" for op in cf.methods[0].spark_operations)


def test_spark_filter_is_still_detected(tmp_path, backend):
    cf = _parse(tmp_path, """
        package x;
        import org.apache.spark.sql.Dataset;
        class Job {
            Dataset<Row> run(Dataset<Row> in) {
                Dataset<Row> f = in.filter(in.col("ok"));
                f.write().parquet("/o");
                return f;
            }
        }
    """)
    ops = {op.operation_type for op in cf.methods[0].spark_operations}
    assert "FILTER" in ops and "PARQUET_WRITE" in ops


def test_strong_spark_ops_fire_without_obvious_context(tmp_path, backend):
    # join / groupBy / dropDuplicates don't exist on JDK types -> always emitted
    cf = _parse(tmp_path, """
        package x;
        class J { void r(Object a, Object b) {
            a.join(b, "k").groupBy("d").dropDuplicates("id");
        } }
    """)
    ops = {op.operation_type for op in cf.methods[0].spark_operations}
    assert {"JOIN", "GROUP_BY", "DEDUPLICATION"} <= ops


# --- external I/O detection ----------------------------------------
def test_external_io_detected(tmp_path, backend):
    cf = _parse(tmp_path, """
        package x;
        import java.sql.DriverManager;
        class Dao {
            void go(String url) {
                var c = DriverManager.getConnection(url);
                var f = new java.io.FileInputStream("/tmp/x");
            }
        }
    """)
    io = [op for op in cf.methods[0].spark_operations if op.operation_type == "EXTERNAL_IO"]
    assert len(io) == 2
    findings = RuleEngine().evaluate([cf])
    assert any(f.category == "EXTERNAL_IO" and f.rule_id.startswith("external_io") for f in findings)


# --- plain-Java project -------------------------------------------
def _plain_project(tmp_path):
    root = tmp_path / "proj"
    (root / "src/main/java/com/acme").mkdir(parents=True)
    (root / "pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion><groupId>c</groupId>"
        "<artifactId>a</artifactId><version>1</version></project>")
    (root / "src/main/java/com/acme/Svc.java").write_text(textwrap.dedent("""
        package com.acme;
        import java.sql.DriverManager;
        public class Svc {
            void save(String u) throws java.sql.SQLException {
                DriverManager.getConnection(u);
            }
            void handle() {
                try { risky(); } catch (Exception e) { }
            }
        }
    """))
    return str(root)


def test_plain_java_project_scores_only_applicable_buckets(tmp_path):
    jp.set_backend("auto")
    result = run_scan(_plain_project(tmp_path), Config(), use_llm=False)
    assert result.project.project_type == "java"
    assert result.project.frameworks == []
    assert set(result.scores.not_applicable) == set(_SPARK_ONLY_BUCKETS)
    cats = {f.category for f in result.findings}
    assert cats <= {"EXCEPTION", "EXTERNAL_IO"}
    assert 0 <= result.scores.overall_score <= 100

    doc = build_report_document(result)
    assert doc["project"]["project_type"] == "java"
    assert set(doc["scores"]["not_applicable"]) == set(_SPARK_ONLY_BUCKETS)
    md = write_markdown_report(result, str(tmp_path / "r"))
    text = open(md).read()
    assert "Java (no Spark detected)" in text
    assert "| Job lifecycle | n/a | — |" in text
    assert "## External I/O Boundaries" in text


def test_plain_java_project_type_round_trips_through_db(tmp_path):
    jp.set_backend("auto")
    cfg = Config()
    cfg.data["database"]["path"] = str(tmp_path / "a.db")
    result = run_scan(_plain_project(tmp_path), cfg, use_llm=False)
    db = Database(cfg.database["path"])
    sid = db.save_scan(result)
    loaded = db.load_scan_result(sid)
    db.close()
    assert loaded.project.project_type == "java"
    assert set(loaded.scores.not_applicable) == set(_SPARK_ONLY_BUCKETS)
    assert loaded.scores.overall_score == result.scores.overall_score
