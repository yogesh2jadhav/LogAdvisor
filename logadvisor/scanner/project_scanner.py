"""Phase 1 - project discovery.

Walks the target repository, classifies the build system, extracts Java / Spark /
logging-framework information and counts source files. Never reads data files
(parquet/csv/json contents) - only build files and source.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Tuple

from ..models import ProjectInfo

SOURCE_EXT = ".java"


def _iter_files(root: str, ignore_dirs: List[str]):
    ignore = set(ignore_dirs)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignore and not d.startswith(".git")]
        for fn in filenames:
            yield os.path.join(dirpath, fn)


def _is_test_path(path: str) -> bool:
    p = path.replace("\\", "/").lower()
    return "/src/test/" in p or p.endswith("test.java") or p.endswith("tests.java") or "/test/" in p


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _detect_build_system(root: str) -> Tuple[str | None, str]:
    if os.path.isfile(os.path.join(root, "pom.xml")):
        return "Maven", _read(os.path.join(root, "pom.xml"))
    for g in ("build.gradle", "build.gradle.kts"):
        if os.path.isfile(os.path.join(root, g)):
            return "Gradle", _read(os.path.join(root, g))
    return None, ""


def _detect_java_version(build_text: str) -> str | None:
    for pat in (
        r"<maven\.compiler\.(?:source|release|target)>\s*([\d.]+)\s*</",
        r"<source>\s*([\d.]+)\s*</source>",
        r"sourceCompatibility\s*=?\s*['\"]?(?:JavaVersion\.VERSION_)?([\d._]+)",
        r"languageVersion\.set\(JavaLanguageVersion\.of\((\d+)\)\)",
    ):
        m = re.search(pat, build_text)
        if m:
            return m.group(1).replace("_", ".")
    return None


def _detect_spark_version(build_text: str) -> str | None:
    m = re.search(r"spark-(?:core|sql)[_-][\d.]+['\"]?\s*[:,]\s*['\"]?([\d.]+)", build_text)
    if m:
        return m.group(1)
    m = re.search(r"<spark\.version>\s*([\d.]+)\s*</spark\.version>", build_text)
    if m:
        return m.group(1)
    m = re.search(r"org\.apache\.spark['\"]?\s*[,:]\s*['\"]?spark-[a-z]+(?:_[\d.]+)?['\"]?\s*[,:]\s*['\"]?([\d.]+)", build_text)
    return m.group(1) if m else None


LOGGING_FRAMEWORK_MARKERS = {
    "SLF4J": [r"org\.slf4j", r"slf4j-api"],
    "Log4j2": [r"org\.apache\.logging\.log4j", r"log4j-core", r"log4j-api"],
    "Log4j": [r"org\.apache\.log4j", r"(?<!logging\.)log4j:log4j"],
    "Logback": [r"ch\.qos\.logback", r"logback-classic"],
    "java.util.logging": [r"java\.util\.logging"],
}


def _detect_logging_frameworks(build_text: str, sample_sources: List[str]) -> List[str]:
    haystack = build_text + "\n" + "\n".join(sample_sources)
    found = []
    for name, markers in LOGGING_FRAMEWORK_MARKERS.items():
        if any(re.search(m, haystack) for m in markers):
            found.append(name)
    return found


def scan_project(root: str, ignore_dirs: List[str]) -> Tuple[ProjectInfo, List[str]]:
    """Return (ProjectInfo, list_of_java_file_paths)."""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise NotADirectoryError(root)

    build_system, build_text = _detect_build_system(root)

    java_files: List[str] = []
    test_files = 0
    for path in _iter_files(root, ignore_dirs):
        if not path.endswith(SOURCE_EXT):
            continue
        java_files.append(path)
        if _is_test_path(path):
            test_files += 1

    sample_sources = [_read(p) for p in java_files[:40]]
    haystack = build_text + "\n" + "\n".join(sample_sources)

    frameworks: List[str] = []
    if re.search(r"org\.apache\.spark|SparkSession|JavaSparkContext|Dataset<Row>", haystack):
        frameworks.append("Apache Spark")
    if re.search(r"spark-sql|org\.apache\.spark\.sql", haystack):
        frameworks.append("Spark SQL")

    info = ProjectInfo(
        project_name=os.path.basename(root),
        path=root,
        language="Java",
        frameworks=frameworks,
        build_system=build_system,
        java_version=_detect_java_version(build_text),
        spark_version=_detect_spark_version(build_text),
        logging_frameworks=_detect_logging_frameworks(build_text, sample_sources),
        java_files=len(java_files),
        test_files=test_files,
    )
    return info, java_files
