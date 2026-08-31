import textwrap

import pytest

from conftest import FIXTURE_PROJECT
from logadvisor.config import DEFAULT_IGNORE_DIRS
from logadvisor.rules.rule_engine import RuleEngine
from logadvisor.scanner import java_parser as jp
from logadvisor.scanner import regex_parser, treesitter_parser
from logadvisor.scanner.project_scanner import scan_project

ts_only = pytest.mark.skipif(not treesitter_parser.available(),
                             reason="tree-sitter / tree-sitter-java not installed")

PP = f"{FIXTURE_PROJECT}/src/main/java/com/example/pipeline/PatientProcessor.java"


@pytest.fixture(autouse=True)
def _reset_backend():
    jp.set_backend("auto")
    yield
    jp.set_backend("auto")


# --- dispatcher ------------------------------------------------------
def test_backend_selection_and_override():
    jp.set_backend("regex")
    assert jp.active_backend() == "regex"
    jp.set_backend("bogus")                      # invalid -> auto
    assert jp.active_backend() in ("treesitter", "regex")


@ts_only
def test_auto_prefers_treesitter():
    jp.set_backend("auto")
    assert jp.active_backend() == "treesitter"


def test_regex_backend_still_works():
    jp.set_backend("regex")
    cf = jp.parse_java_file(PP, FIXTURE_PROJECT)
    assert "PatientProcessor" in cf.classes
    assert {m.name for m in cf.methods} >= {"processPatients", "countRecords"}


# --- equivalence on the fixture ------------------------------------
@ts_only
def test_treesitter_and_regex_agree_on_fixture_findings():
    _, files = scan_project(FIXTURE_PROJECT, DEFAULT_IGNORE_DIRS)

    def findings(backend):
        jp.set_backend(backend)
        parsed = [jp.parse_java_file(p, FIXTURE_PROJECT) for p in files]
        return sorted((f.category, f.file, f.line) for f in RuleEngine().evaluate(parsed))

    assert findings("treesitter") == findings("regex")


# --- cases where the AST backend is more accurate -----------------
_HARD = textwrap.dedent("""
    package com.acme;
    import org.apache.spark.sql.Dataset;
    public class Repo {
        public static <T extends Comparable<T>>
                Dataset<Row> pick(Dataset<Row> a,
                                  java.util.Map<String, java.util.List<T>> idx)
                throws java.io.IOException {
            return a.filter(r -> { return r.getAs("ok"); }).join(a, "k");
        }
        static final class Helper {
            void write(Dataset<Row> d) { d.write().parquet("/x"); }
        }
    }
""")


@ts_only
def test_treesitter_handles_nested_class_and_multiline_generics(tmp_path):
    f = tmp_path / "Repo.java"
    f.write_text(_HARD)
    jp.set_backend("treesitter")
    cf = jp.parse_java_file(str(f), str(tmp_path))

    assert set(cf.classes) == {"Repo", "Helper"}
    pick = next(m for m in cf.methods if m.name == "pick")
    assert pick.class_name == "Repo"
    assert pick.return_type.replace(" ", "") == "Dataset<Row>"
    assert len(pick.parameters) == 2
    assert any(e.kind == "THROWS" for e in pick.exception_boundaries)

    helper = next(m for m in cf.methods if m.name == "write")
    assert helper.class_name == "Helper"          # nested class attribution
    assert {op.operation_type for op in helper.spark_operations} >= {"PARQUET_WRITE"}


@ts_only
def test_string_literals_never_produce_false_spark_ops(tmp_path):
    f = tmp_path / "S.java"
    f.write_text('package x; class S { String s() { return "a .join( b .filter( c"; } }')
    jp.set_backend("treesitter")
    cf = jp.parse_java_file(str(f), str(tmp_path))
    assert cf.methods[0].spark_operations == []
