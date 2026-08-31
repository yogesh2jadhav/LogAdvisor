import json
import textwrap

from conftest import FIXTURE_PROJECT
from logadvisor.analyzer import run_pass1, run_scan
from logadvisor.config import Config
from logadvisor.db.database import Database
from logadvisor.llm.cache import LLMCache
from logadvisor.llm.llm_analyzer import LLMAnalyzer
from logadvisor.rules.rule_engine import RuleEngine
from logadvisor.scanner.java_parser import parse_java_file
from tests.test_new_features import FakeProvider


def _parse(tmp_path, src, name="A.java"):
    f = tmp_path / name
    f.write_text(textwrap.dedent(src))
    return parse_java_file(str(f), str(tmp_path))


# --- lazy evaluation / execution boundary --------------------------------
def test_lazy_transformation_execution_boundary(tmp_path):
    cf = _parse(tmp_path, """
        package x;
        class Job {
            Dataset<Row> run(Dataset<Row> a, Dataset<Row> b) {
                Dataset<Row> j = a.join(b, a.col("k").equalTo(b.col("k")));
                Dataset<Row> f = j.filter(j.col("ok"));
                f.write().parquet("/out");
                return f;
            }
        }
    """)
    m = cf.methods[0]
    join = next(o for o in m.spark_operations if o.operation_type == "JOIN")
    write = next(o for o in m.spark_operations if o.operation_type == "PARQUET_WRITE")
    assert join.lazy is True
    assert join.materialized_at == write.line
    assert write.is_action is True


def test_orphan_transformation_has_no_execution(tmp_path):
    cf = _parse(tmp_path, """
        package x;
        class Job {
            Dataset<Row> build(Dataset<Row> a) {
                return a.filter(a.col("ok")).join(a, "k");
            }
        }
    """)
    m = cf.methods[0]
    join = next(o for o in m.spark_operations if o.operation_type == "JOIN")
    assert join.lazy is True and join.materialized_at is None

    findings = RuleEngine().evaluate([cf])
    jf = next(f for f in findings if f.category == "JOIN")
    assert jf.execution_line is None


def test_finding_carries_execution_line(tmp_path):
    cf = _parse(tmp_path, """
        package x;
        class Job {
            void run(Dataset<Row> a, Dataset<Row> b) {
                Dataset<Row> j = a.join(b, "k");
                j.count();
            }
        }
    """)
    findings = RuleEngine().evaluate([cf])
    jf = next(f for f in findings if f.category == "JOIN")
    assert jf.execution_line is not None and jf.execution_line != jf.line


# --- throws clause -------------------------------------------------------
def test_throws_without_error_logging_is_a_finding(tmp_path):
    cf = _parse(tmp_path, """
        package x;
        class A {
            void risky() throws java.io.IOException {
                doStuff();
            }
        }
    """)
    findings = RuleEngine().evaluate([cf])
    assert any(f.category == "EXCEPTION" for f in findings)
    assert any(e.kind == "THROWS" for m in cf.methods for e in m.exception_boundaries)


def test_throws_with_error_logging_is_not_flagged(tmp_path):
    cf = _parse(tmp_path, """
        package x;
        class A {
            void risky() throws java.io.IOException {
                try { doStuff(); }
                catch (Exception e) { logger.error("failed {}", e.toString()); throw e; }
            }
        }
    """)
    findings = RuleEngine().evaluate([cf])
    assert not any(f.category == "EXCEPTION" for f in findings)


# --- job completion ----------------------------------------------------
def test_job_start_yields_completion_finding(tmp_path):
    cf = _parse(tmp_path, """
        package x;
        class Main {
            void main() {
                SparkSession spark = SparkSession.builder().getOrCreate();
                spark.read().parquet("/in").write().parquet("/out");
            }
        }
    """)
    findings = RuleEngine().evaluate([cf])
    cats = {f.category for f in findings}
    assert "JOB_START" in cats
    assert "JOB_COMPLETION" in cats
    jc = next(f for f in findings if f.category == "JOB_COMPLETION")
    assert jc.priority == "HIGH"
    assert "status" in jc.required_fields and "duration" in jc.required_fields


# --- llm cache index in sqlite --------------------------------------
def test_llm_cache_table_populated(tmp_path):
    cfg = Config()
    cfg.data["database"]["path"] = str(tmp_path / "a.db")
    p1 = run_pass1(FIXTURE_PROJECT, cfg)
    from logadvisor.models import ScanResult
    result = ScanResult(project=p1.project, files=p1.files, findings=p1.findings,
                        scores=p1.scores, llm_enabled=True, llm_provider="fake", llm_model="fake:1b")
    cache = LLMCache(str(tmp_path / "cache"), enabled=True)
    an = LLMAnalyzer(FakeProvider(), "fake:1b", cache)
    an.analyze(p1.project, p1.files, p1.findings, p1.sources, min_priority="high", limit=3)
    result.llm_runs = an.runs

    db = Database(cfg.database["path"])
    scan_id = db.save_scan(result)
    rows = db.conn.execute(
        "SELECT cache_key, model, rule_id, response_path FROM llm_cache WHERE scan_id = ?",
        (scan_id,),
    ).fetchall()
    db.close()
    assert len(rows) == len(an.runs)
    assert all(r["cache_key"] and r["response_path"] for r in rows)


def test_regen_report_keeps_execution_line(tmp_path):
    cfg = Config()
    cfg.data["database"]["path"] = str(tmp_path / "a.db")
    db = Database(cfg.database["path"])
    scan_id = db.save_scan(run_scan(FIXTURE_PROJECT, cfg, use_llm=False))
    loaded = db.load_scan_result(scan_id)
    db.close()
    # execution_line values should survive persistence
    ex_loaded = [f.execution_line for f in loaded.findings if f.execution_line]
    assert ex_loaded  # at least one lazy transformation in the fixture
